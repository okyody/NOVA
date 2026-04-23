"""Role-based NOVA worker entrypoint."""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import socket
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _configure_role(role: str) -> None:
    os.environ["NOVA_RUNTIME__ROLE"] = role
    os.environ.setdefault("NOVA_RUNTIME__EVENT_BUS_MODE", "external_consumer")
    os.environ.setdefault("NOVA_RUNTIME__EVENT_BUS_BACKEND", "redis_streams")
    os.environ.setdefault("NOVA_PERSIST__ENABLED", "true")
    os.environ.setdefault("NOVA_PERSIST__BACKEND", "redis")

    hostname = socket.gethostname().lower().replace(".", "-")
    consumer_group_map = {
        "perception": "nova-perception",
        "cognitive": "nova-cognitive",
        "generation": "nova-generation",
    }
    group = consumer_group_map.get(role, "nova-workers")
    os.environ.setdefault("NOVA_RUNTIME__EVENT_BUS_CONSUMER_GROUP", group)
    os.environ.setdefault("NOVA_RUNTIME__EVENT_BUS_CONSUMER_NAME", f"{group}-{hostname}")
    os.environ.setdefault("NOVA_RUNTIME__INSTANCE_NAME", f"{role}-{hostname}")
    os.environ.setdefault("NOVA_RUNTIME__SESSION_ID", "primary")


async def _run(role: str) -> None:
    _configure_role(role)

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
