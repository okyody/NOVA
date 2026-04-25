"""
NOVA End-to-End Integration Test
=================================
Validates the full cognitive pipeline with fake danmaku events.
No real platform, no real LLM — all mocked.

Pipeline: FakeChat → SemanticAggregator → Orchestrator → SafetyGuard → SAFE_OUTPUT
"""
import asyncio
import pytest

from packages.core.event_bus import EventBus
from packages.core.types import (
    ActionType,
    EmotionLabel,
    EmotionState,
    EventType,
    NovaEvent,
    Priority,
)
from packages.cognitive.emotion_agent import EmotionAgent
from packages.cognitive.memory_agent import MemoryAgent
from packages.cognitive.personality_agent import PersonalityAgent
from packages.cognitive.orchestrator import Orchestrator, LLMClient
from packages.ops.safety_guard import SafetyGuard
from packages.perception.semantic_aggregator import SemanticAggregator
from packages.perception.silence_detector import SilenceDetector


# ── Mock LLM ─────────────────────────────────────────────────────────────────

class MockLLMClient:
    """Fake LLM that returns canned responses — no real API call."""

    def __init__(self) -> None:
        self.model = "mock-llm"
        self._call_count = 0

    async def complete(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 200,
        temperature: float = 0.85,
    ) -> str:
        self._call_count += 1
        # Return a simple response based on the last user message
        user_msg = messages[-1]["content"] if messages else ""
        if "礼物" in user_msg or "gift" in user_msg.lower():
            return "谢谢你的礼物！好开心呀～"
        if "安静" in user_msg or "沉默" in user_msg:
            return "嗯，大家都在认真听呢，那我再说说刚才的话题吧～"
        return "哈哈，说得对！我也这么觉得～"

    async def stream_completion(self, messages, max_tokens=200, temperature=0.85, tools=None):
        """Yield chunks in the new dict format matching LLMClient.stream_completion."""
        text = await self.complete(messages, max_tokens, temperature)
        # Simulate sentence-level streaming: split on Chinese punctuation
        import re
        parts = re.split(r'([。！？!?；;]+)', text)
        for i in range(0, len(parts), 2):
            chunk_text = parts[i]
            if i + 1 < len(parts):
                chunk_text += parts[i + 1]
            if chunk_text:
                yield {"type": "text", "content": chunk_text}
        yield {"type": "done", "finish_reason": "stop"}

    async def close(self) -> None:
        pass


class SemanticTestEmbedder:
    """Small deterministic embedder for semantic clustering tests."""

    _vectors = {
        "好棒": [1.0, 0.0, 0.0],
        "太厉害了": [0.98, 0.02, 0.0],
        "真强啊": [0.96, 0.04, 0.0],
        "这个游戏太难了": [0.0, 1.0, 0.0],
    }

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vectors.get(text, [0.0, 0.0, 1.0]) for text in texts]


# ── Helper ───────────────────────────────────────────────────────────────────

def _make_chat_event(text: str, username: str = "test_viewer", viewer_id: str = "v1") -> NovaEvent:
    return NovaEvent(
        type=EventType.CHAT_MESSAGE,
        payload={
            "text": text,
            "viewer": {
                "viewer_id": viewer_id,
                "username": username,
                "platform": "local",
            },
        },
        priority=Priority.NORMAL,
        source="test",
    )


# ── Integration Tests ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_e2e_chat_to_safe_output():
    """
    Full pipeline: fake chat → SemanticAggregator → Orchestrator → SafetyGuard → SAFE_OUTPUT.
    This is the Phase 1 acceptance test.
    """
    bus = EventBus(queue_size=1024)
    await bus.start()

    # Start all components in correct order
    memory = MemoryAgent(bus)
    await memory.start()

    emotion = EmotionAgent(bus)
    await emotion.start()

    personality = PersonalityAgent(bus)
    await personality.start()

    llm = MockLLMClient()
    orchestrator = Orchestrator(
        bus=bus,
        llm=llm,
        memory_agent=memory,
        emotion_agent=emotion,
        personality_agent=personality,
    )
    await orchestrator.start()

    safety = SafetyGuard(bus)
    await safety.start()

    aggregator = SemanticAggregator(bus, window_ms=100)  # short window for test
    await aggregator.start()

    # Collect SAFE_OUTPUT events
    safe_outputs: list[NovaEvent] = []
    async def capture_safe(event: NovaEvent):
        safe_outputs.append(event)

    bus.subscribe(EventType.SAFE_OUTPUT, capture_safe, sub_id="test_e2e")

    # Send multiple chat messages to trigger aggregation
    for i in range(5):
        await bus.publish(_make_chat_event(f"今天天气真好！第{i+1}条"))

    # Wait for aggregation window + orchestrator processing
    await asyncio.sleep(0.5)

    # Should have received at least one SAFE_OUTPUT
    assert len(safe_outputs) >= 1, f"Expected SAFE_OUTPUT, got {len(safe_outputs)} events"
    output = safe_outputs[0]
    assert output.payload.get("text"), "SAFE_OUTPUT should have text"
    assert output.type == EventType.SAFE_OUTPUT

    # Verify LLM was called
    assert llm._call_count >= 1, "LLM should have been called"

    # Cleanup
    await aggregator.stop()
    await safety.stop()
    await orchestrator.stop()
    await memory.stop()
    await emotion.stop()
    await bus.stop()


@pytest.mark.asyncio
async def test_e2e_safety_blocks_dangerous_content():
    """Verify SafetyGuard blocks dangerous LLM output before it reaches voice."""
    bus = EventBus(queue_size=1024)
    await bus.start()

    # We bypass the full pipeline and test SafetyGuard directly
    safety = SafetyGuard(bus)
    await safety.start()

    safe_outputs: list[NovaEvent] = []
    async def capture_safe(event: NovaEvent):
        safe_outputs.append(event)

    bus.subscribe(EventType.SAFE_OUTPUT, capture_safe, sub_id="test_safety_e2e")

    # Simulate Orchestrator output with dangerous content
    await bus.publish(NovaEvent(
        type=EventType.ORCHESTRATOR_OUT,
        payload={"text": "自残不是一个好话题，我们应该避免。"},
    ))
    await asyncio.sleep(0.1)

    assert len(safe_outputs) == 1
    assert "自残" not in safe_outputs[0].payload["text"]
    assert safety.stats()["blocks"] == 1

    await bus.stop()


@pytest.mark.asyncio
async def test_e2e_gift_triggers_emotion_and_memory():
    """Gift → emotion change + memory store."""
    bus = EventBus(queue_size=1024)
    await bus.start()

    emotion = EmotionAgent(bus)
    await emotion.start()

    memory = MemoryAgent(bus)
    await memory.start()

    initial_valence = emotion._valence

    # Send gift event
    await bus.publish(NovaEvent(
        type=EventType.GIFT_RECEIVED,
        payload={
            "gift_name": "rocket",
            "amount": 50,
            "viewer": {
                "viewer_id": "v_gifter",
                "username": "大佬",
                "platform": "bilibili",
            },
        },
        priority=Priority.HIGH,
        source="test",
    ))
    await asyncio.sleep(0.1)

    # Emotion should have changed
    assert emotion._valence > initial_valence, "Gift should increase valence"

    # Memory should have recorded the event
    recent = memory.working.recent(1)
    assert len(recent) == 1
    assert "rocket" in recent[0].get("text", "").lower() or "gift" in recent[0].get("event_type", "")

    await memory.stop()
    await emotion.stop()
    await bus.stop()


@pytest.mark.asyncio
async def test_e2e_silence_detector():
    """SilenceDetector publishes SILENCE_DETECTED after timeout."""
    bus = EventBus(queue_size=1024)
    await bus.start()

    detector = SilenceDetector(bus, silence_sec=0.5, check_interval=0.1)
    await detector.start()

    silence_events: list[NovaEvent] = []
    async def capture(event: NovaEvent):
        silence_events.append(event)

    bus.subscribe(EventType.SILENCE_DETECTED, capture, sub_id="test_silence")

    # No chat messages → should detect silence after 0.5s
    await asyncio.sleep(0.8)

    assert len(silence_events) >= 1, "Should have detected silence"

    # Now send a chat message → silence flag should reset
    silence_events.clear()
    await bus.publish(_make_chat_event("hi"))
    await asyncio.sleep(0.3)

    # Not enough time for silence again
    assert len(silence_events) == 0, "Should not detect silence immediately after chat"

    await detector.stop()
    await bus.stop()


@pytest.mark.asyncio
async def test_semantic_aggregator_clustering():
    """SemanticAggregator uses embeddings to cluster semantically similar chat."""
    bus = EventBus(queue_size=1024)
    await bus.start()

    aggregator = SemanticAggregator(
        bus,
        window_ms=200,
        similarity_threshold=0.92,
        embedder=SemanticTestEmbedder(),
    )
    await aggregator.start()

    clusters: list[NovaEvent] = []
    async def capture(event: NovaEvent):
        clusters.append(event)

    bus.subscribe(EventType.SEMANTIC_CLUSTER, capture, sub_id="test_cluster")

    # Send similar messages
    for i in range(3):
        await bus.publish(_make_chat_event(f"今天天气真好", f"viewer_{i}", f"v{i}"))
    # Send different message
    await bus.publish(_make_chat_event("这个游戏太难了", "viewer_4", "v4"))

    # Wait for aggregation
    await asyncio.sleep(0.4)

    assert len(clusters) >= 1, f"Expected at least 1 cluster, got {len(clusters)}"
    # Verify cluster has the expected structure
    first_cluster = clusters[0]
    assert "representative" in first_cluster.payload
    assert "message_count" in first_cluster.payload
    assert first_cluster.payload["message_count"] >= 1

    await aggregator.stop()
    await bus.stop()
