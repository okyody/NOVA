"""Minimal smoke for EventBus external_consumer mode."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.core.event_bus import EventBus, InMemoryEventTransportBackend
from packages.core.types import EventType, NovaEvent


async def main() -> None:
    bus = EventBus(
        transport_backend=InMemoryEventTransportBackend(),
        mode="external_consumer",
    )
    received: list[NovaEvent] = []

    async def handler(event: NovaEvent) -> None:
        received.append(event)

    bus.subscribe(EventType.CHAT_MESSAGE, handler, sub_id="smoke")
    await bus.start()
    await bus.publish(NovaEvent(type=EventType.CHAT_MESSAGE, payload={"text": "hello"}))
    await asyncio.sleep(0.1)
    await bus.stop()

    if len(received) != 1:
        raise SystemExit("external_consumer_smoke_failed")

    print("external_consumer_smoke_ok")


if __name__ == "__main__":
    asyncio.run(main())
