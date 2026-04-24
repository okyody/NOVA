"""Role-based NOVA worker entrypoint."""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.nova_runtime.bootstrap import configure_worker_environment


async def _run(role: str) -> None:
    configure_worker_environment(role)

    from packages.core.config import load_settings
    from apps.nova_server.main import NovaApp

    settings = load_settings()
    app = NovaApp(settings)

    stop_event = asyncio.Event()

    def _request_stop() -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:
            pass

    await app.startup()
    try:
        await stop_event.wait()
    finally:
        await app.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=["perception", "cognitive", "generation"])
    args = parser.parse_args()
    asyncio.run(_run(args.role))


if __name__ == "__main__":
    main()
