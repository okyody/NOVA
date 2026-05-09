from __future__ import annotations

import asyncio

import pytest

from packages.cognitive.memory_agent import MemoryAgent
from packages.core.event_bus import EventBus
from packages.core.types import EventType, NovaEvent, Priority


@pytest.mark.asyncio
async def test_memory_agent_skips_consolidation_when_runtime_not_idle() -> None:
    bus = EventBus(queue_size=64)
    await bus.start()
    try:
        agent = MemoryAgent(
            bus,
            consolidate_every_n=1,
            consolidate_every_s=1,
            can_consolidate=lambda: False,
        )
        await agent.start()
        await bus.publish(
            NovaEvent(
                type=EventType.CHAT_MESSAGE,
                payload={"text": "hello", "viewer": {"viewer_id": "v1", "username": "alice", "platform": "local"}},
                priority=Priority.NORMAL,
                source="test",
            )
        )
        await asyncio.sleep(0.1)
        assert len(agent.episodic._store) == 0
        await agent.stop()
    finally:
        await bus.stop()
