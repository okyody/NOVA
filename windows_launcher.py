"""
Windows launcher for NOVA.

This entrypoint is intended for PyInstaller packaging. It anchors NOVA's
runtime to the executable directory so bundled config and character assets
work when launched by non-technical users on Windows.
"""
from __future__ import annotations

import os
import shutil
import sys
import threading
import time
import webbrowser
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


def _log(message: str) -> None:
    try:
        root = _app_root()
        with (root / "nova-launcher.log").open("a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except OSError:
        pass


def _app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _prepare_runtime_files(root: Path) -> None:
    config_path = root / "nova.config.json"
    config_example = root / "nova.config.example.json"
    if not config_path.exists() and config_example.exists():
        shutil.copyfile(config_example, config_path)

    character_path = root / "characters" / "nova_default.toml"
    if character_path.exists():
        os.environ.setdefault("NOVA_CHARACTER__PATH", str(character_path))

    os.environ.setdefault("NOVA_CONFIG", str(config_path if config_path.exists() else config_example))
    os.environ.setdefault("NOVA_PORT", "8765")
    _log(f"runtime prepared at {root}")


def _should_auto_open_studio() -> bool:
    raw = os.environ.get("NOVA_AUTO_OPEN_STUDIO", "")
    if raw:
        return raw.strip().lower() not in {"0", "false", "no", "off"}
    return bool(getattr(sys, "frozen", False))


def _should_embed_studio() -> bool:
    raw = os.environ.get("NOVA_EMBED_STUDIO", "")
    if raw:
        return raw.strip().lower() not in {"0", "false", "no", "off"}
    return bool(getattr(sys, "frozen", False))


def _studio_url() -> str:
    port = os.environ.get("NOVA_PORT", "8765").strip() or "8765"
    return f"http://127.0.0.1:{port}/studio/"


def _open_studio_when_ready(timeout_s: float = 60.0, poll_s: float = 0.5) -> None:
    deadline = time.monotonic() + timeout_s
    url = _studio_url()
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=2.0) as response:
                if 200 <= getattr(response, "status", 0) < 500:
                    _log(f"studio ready at {url}")
                    webbrowser.open(url)
                    return
        except URLError:
            time.sleep(poll_s)
        except OSError:
            time.sleep(poll_s)


def _run_server() -> None:
    try:
        from apps.nova_server.main import main as nova_main

        _log("server thread starting")
        nova_main()
    except Exception as exc:
        _log(f"server thread failed: {exc!r}")
        raise


def _open_embedded_studio() -> None:
    import webview

    _log("opening embedded studio window")
    webview.create_window(
        "NOVA Studio",
        _studio_url(),
        width=1440,
        height=960,
        min_size=(1100, 720),
    )
    webview.start()


def main() -> None:
    root = _app_root()
    os.chdir(root)
    _prepare_runtime_files(root)
    _log("launcher main entered")

    if _should_embed_studio():
        _log("embed studio mode enabled")
        threading.Thread(
            target=_run_server,
            name="nova.server.thread",
            daemon=True,
        ).start()
        try:
            _open_studio_when_ready(timeout_s=60.0, poll_s=0.5)
            _open_embedded_studio()
        except Exception:
            _log("embedded studio failed, falling back to browser")
            _open_studio_when_ready(timeout_s=60.0, poll_s=0.5)
        return

    if _should_auto_open_studio():
        _log("browser auto-open mode enabled")
        threading.Thread(
            target=_open_studio_when_ready,
            name="nova.studio.autostart",
            daemon=True,
        ).start()

    from apps.nova_server.main import main as nova_main

    nova_main()


if __name__ == "__main__":
    main()
