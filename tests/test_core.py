"""
NOVA Core Tests
===============
Run: pytest tests/ -v --asyncio-mode=auto
"""
import asyncio
import pytest

from packages.core.event_bus import EventBus
from packages.core.types import (
    EmotionLabel,
    EventType,
    NovaEvent,
    Priority,
)
from packages.cognitive.emotion_agent import EmotionAgent


# ─── Event Bus Tests ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_event_bus_basic_pubsub():
    """Events reach subscribers."""
    bus = EventBus()
    await bus.start()

    received = []
    async def handler(event: NovaEvent):
        received.append(event)

    bus.subscribe(EventType.CHAT_MESSAGE, handler, sub_id="test_h")
    await bus.publish(NovaEvent(
        type=EventType.CHAT_MESSAGE,
        payload={"text": "hello"},
    ))
    await asyncio.sleep(0.05)

    assert len(received) == 1
    assert received[0].payload["text"] == "hello"
    await bus.stop()


@pytest.mark.asyncio
async def test_event_bus_priority_order():
    """CRITICAL events arrive before NORMAL events."""
    bus = EventBus()
    await bus.start()

    order = []
    async def capture(event: NovaEvent):
        order.append(event.priority)

    bus.subscribe(EventType.CHAT_MESSAGE, capture, sub_id="prio_test")
    await bus.publish(NovaEvent(type=EventType.CHAT_MESSAGE, payload={}, priority=Priority.NORMAL))
    await bus.publish(NovaEvent(type=EventType.CHAT_MESSAGE, payload={}, priority=Priority.CRITICAL))
    await asyncio.sleep(0.1)

    # CRITICAL (0) should come before NORMAL (2)
    assert order[0] == Priority.CRITICAL
    await bus.stop()


@pytest.mark.asyncio
async def test_event_bus_wildcard():
    """Wildcard subscriptions receive all matching events."""
    bus = EventBus()
    await bus.start()

    seen = []
    async def handler(event: NovaEvent):
        seen.append(event.type)

    bus.subscribe("platform.*", handler, sub_id="wildcard_test")
    await bus.publish(NovaEvent(type=EventType.CHAT_MESSAGE,  payload={}))
    await bus.publish(NovaEvent(type=EventType.GIFT_RECEIVED, payload={}))
    await bus.publish(NovaEvent(type=EventType.EMOTION_STATE, payload={"valence": 0, "arousal": 0, "label": "neutral", "intensity": 0}))
    await asyncio.sleep(0.1)

    assert EventType.CHAT_MESSAGE  in seen
    assert EventType.GIFT_RECEIVED in seen
    assert EventType.EMOTION_STATE not in seen   # not a platform event
    await bus.stop()


@pytest.mark.asyncio
async def test_event_bus_dlq():
    """Events with no subscriber go to the dead letter queue."""
    bus = EventBus()
    await bus.start()

    await bus.publish(NovaEvent(type=EventType.HEALTH_CHECK, payload={}))
    await asyncio.sleep(0.05)

    dlq = bus.dlq_drain()
    assert len(dlq) == 1
    assert dlq[0].type == EventType.HEALTH_CHECK
    await bus.stop()


# ─── Emotion Agent Tests ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_emotion_gift_triggers_excited():
    """Receiving a gift should push emotion toward excited."""
    bus = EventBus()
    await bus.start()
    agent = EmotionAgent(bus)
    await agent.start()

    initial_valence = agent._valence
    await bus.publish(NovaEvent(
        type=EventType.GIFT_RECEIVED,
        payload={"gift_name": "rocket", "amount": 30, "viewer": {}},
        priority=Priority.HIGH,
    ))
    await asyncio.sleep(0.1)

    assert agent._valence > initial_valence, "Gift should increase valence"
    assert agent._arousal > 0.35, "Gift should increase arousal"
    await agent.stop()
    await bus.stop()


@pytest.mark.asyncio
async def test_emotion_decay():
    """Emotion decays toward baseline over time."""
    bus = EventBus()
    await bus.start()
    agent = EmotionAgent(bus)
    await agent.start()

    # Force high emotion
    agent._valence = 0.95
    agent._arousal = 0.95

    # Wait for multiple decay cycles
    await asyncio.sleep(2.0)

    assert agent._valence < 0.95, "Valence should decay"
    assert agent._arousal < 0.95, "Arousal should decay"
    await agent.stop()
    await bus.stop()


@pytest.mark.asyncio
async def test_emotion_state_published_on_change():
    """Significant emotion changes publish EMOTION_STATE events."""
    bus = EventBus()
    await bus.start()
    agent = EmotionAgent(bus)
    await agent.start()

    states_received = []
    async def capture(event: NovaEvent):
        states_received.append(event)

    bus.subscribe(EventType.EMOTION_STATE, capture, sub_id="emo_test")

    # Trigger a big emotion change
    await bus.publish(NovaEvent(
        type=EventType.SUPER_CHAT,
        payload={"amount": 100, "viewer": {}},
        priority=Priority.CRITICAL,
    ))
    await asyncio.sleep(0.1)

    assert len(states_received) > 0
    last = states_received[-1]
    assert "valence" in last.payload
    assert "label"   in last.payload
    await agent.stop()
    await bus.stop()


# ─── Safety Guard Tests ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_safety_blocks_forbidden_content():
    """Safety guard substitutes forbidden content and publishes SAFE_OUTPUT."""
    from packages.ops.safety_guard import SafetyGuard

    bus = EventBus()
    await bus.start()
    guard = SafetyGuard(bus)
    await guard.start()

    safe_outputs = []
    async def capture_safe(event: NovaEvent):
        safe_outputs.append(event)

    bus.subscribe(EventType.SAFE_OUTPUT, capture_safe, sub_id="safe_test")

    # Publish safe content
    await bus.publish(NovaEvent(
        type=EventType.ORCHESTRATOR_OUT,
        payload={"text": "这是干净的文本，没有问题。"},
    ))
    await asyncio.sleep(0.05)

    assert len(safe_outputs) == 1
    assert "干净" in safe_outputs[0].payload["text"]

    # Publish blocked content
    safe_outputs.clear()
    await bus.publish(NovaEvent(
        type=EventType.ORCHESTRATOR_OUT,
        payload={"text": "自杀是解脱方式。"},   # triggers self_harm block
    ))
    await asyncio.sleep(0.05)

    assert len(safe_outputs) == 1
    assert "自杀" not in safe_outputs[0].payload["text"]   # original text replaced
    assert guard.stats()["blocks"] == 1
    await bus.stop()


# ─── New Event Types Tests ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_safe_output_event_type():
    """SAFE_OUTPUT event type exists and works."""
    bus = EventBus()
    await bus.start()

    received = []
    async def handler(event: NovaEvent):
        received.append(event)

    bus.subscribe(EventType.SAFE_OUTPUT, handler, sub_id="safe_out_test")
    await bus.publish(NovaEvent(
        type=EventType.SAFE_OUTPUT,
        payload={"text": "test"},
    ))
    await asyncio.sleep(0.05)

    assert len(received) == 1
    await bus.stop()


@pytest.mark.asyncio
async def test_memory_store_event_type():
    """MEMORY_STORE event type exists and works."""
    bus = EventBus()
    await bus.start()

    received = []
    async def handler(event: NovaEvent):
        received.append(event)

    bus.subscribe(EventType.MEMORY_STORE, handler, sub_id="mem_store_test")
    await bus.publish(NovaEvent(
        type=EventType.MEMORY_STORE,
        payload={"text": "remember this", "role": "nova"},
    ))
    await asyncio.sleep(0.05)

    assert len(received) == 1
    await bus.stop()
