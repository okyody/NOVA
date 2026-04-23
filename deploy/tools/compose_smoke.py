"""Minimal docker compose smoke runner for NOVA."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "nova.config.json"
BACKUP_PATH = ROOT / "nova.config.json.bak.compose-smoke"


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, cwd=ROOT, check=True)


def _docker_compose() -> list[str]:
    if shutil.which("docker") is None:
        raise RuntimeError("docker is not installed or not on PATH")
    return ["docker", "compose"]


def _write_temp_config() -> None:
    config = {
        "llm": {
            "base_url": "http://localhost:11434/v1",
            "api_key": "ollama",
            "model": "qwen2.5:14b",
            "timeout": 10.0,
            "max_tokens": 64,
            "temperature": 0.2,
        },
        "character": {
            "path": "characters/nova_default.toml",
        },
        "runtime": {
            "role": "api",
            "instance_name": "nova-api",
            "session_id": "primary",
            "hot_state_enabled": False,
            "event_bus_mode": "local",
            "event_bus_backend": "memory",
            "event_bus_stream": "nova:events",
            "event_bus_consumer_group": "nova-workers",
            "event_bus_consumer_name": "nova-consumer-1"
        },
        "knowledge": {"enabled": False},
        "persistence": {"enabled": False},
        "auth": {"enabled": False},
        "observability": {
            "tracing_enabled": False,
            "log_level": "INFO",
            "log_json": False,
        },
        "platforms": [],
    }
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def _wait_for_health(timeout_s: int) -> None:
    deadline = time.time() + timeout_s
    url = "http://127.0.0.1:8765/health"
    last_error: str | None = None

    while time.time() < deadline:
        try:
            with urlopen(url, timeout=2) as response:  # nosec B310 - local smoke check
                body = response.read().decode("utf-8", "replace")
                if response.status == 200 and '"status":"ok"' in body.replace(" ", ""):
                    return
                last_error = f"unexpected response: {response.status} {body[:200]}"
        except URLError as exc:
            last_error = str(exc)
        time.sleep(2)

    raise RuntimeError(f"NOVA health endpoint did not become ready: {last_error}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()

    compose = _docker_compose()

    had_existing = CONFIG_PATH.exists()
    if had_existing:
        shutil.copy2(CONFIG_PATH, BACKUP_PATH)

    try:
        _write_temp_config()
        _run(compose + ["config"])
        _run(compose + ["up", "-d", "--build", "redis", "nova"])
        _wait_for_health(args.timeout)
        print("compose_smoke_ok")
        return 0
    finally:
        try:
            _run(compose + ["down", "--remove-orphans"])
        except Exception:
            pass

        if BACKUP_PATH.exists():
            shutil.move(BACKUP_PATH, CONFIG_PATH)
        elif CONFIG_PATH.exists():
            CONFIG_PATH.unlink()


if __name__ == "__main__":
    sys.exit(main())
