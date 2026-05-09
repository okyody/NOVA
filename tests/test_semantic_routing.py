from __future__ import annotations

import asyncio

import pytest

from packages.cognitive.nlu import IntentResult, IntentType
from packages.cognitive.orchestrator import Orchestrator
from packages.core.event_bus import EventBus
from packages.core.types import ActionType, EmotionLabel, EmotionState, EventType, NovaEvent, Priority
from packages.perception.semantic_aggregator import SemanticAggregator


class SemanticTestEmbedder:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        mapping = {
            "awesome": [1.0, 0.0, 0.0],
            "so impressive": [0.98, 0.02, 0.0],
            "really strong": [0.96, 0.04, 0.0],
            "this game is too hard": [0.0, 1.0, 0.0],
        }
        return [mapping.get(text, [0.0, 0.0, 1.0]) for text in texts]


class FakeMemory:
    async def recall(self, query: str, viewer_id: str | None = None) -> dict:
        return {
            "recent": "viewer: hi",
            "viewer_summary": "loyal viewer",
            "episodic_hints": ["likes challenge runs"],
        }


class FakeEmotionAgent:
    def __init__(self, state: EmotionState) -> None:
        self._state = state

    @property
    def current_state(self) -> EmotionState:
        return self._state


class FakePersonality:
    def system_prompt(self) -> str:
        return "Stay in character."

    def apply_character(self, text: str) -> str:
        return text


class FakeKnowledgeBase:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, float]] = []

    async def retrieve_texts(self, query: str, top_k: int, score_threshold: float) -> list[str]:
        self.calls.append((query, top_k, score_threshold))
        return ["Knowledge: answer with facts"]


class FakeNLU:
    def __init__(self, result: IntentResult) -> None:
        self._result = result

    async def classify_async(self, text: str) -> IntentResult:
        return self._result


class RecordingLLM:
    def __init__(self) -> None:
        self.model = "recording-llm"
        self.calls: list[dict] = []

    async def stream_completion(
        self,
        messages,
        max_tokens: int = 200,
        temperature: float = 0.85,
        tools=None,
    ):
        self.calls.append(
            {
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "tools": tools,
            }
        )
        yield {"type": "text", "content": "received."}
        yield {"type": "done", "finish_reason": "stop"}

    async def close(self) -> None:
        return None


class ToolCallOnlyLLM:
    def __init__(self) -> None:
        self.model = "tool-llm"

    async def stream_completion(self, messages, max_tokens: int = 200, temperature: float = 0.85, tools=None):
        yield {
            "type": "tool_call",
            "tool_calls": [
                {
                    "index": 2,
                    "id": "call-2",
                    "function": {"name": "demo", "arguments": "{\"q\":\"x\"}"},
                }
            ],
        }
        yield {"type": "done", "finish_reason": "tool_calls"}

    async def close(self) -> None:
        return None


def _chat_event(text: str) -> NovaEvent:
    return NovaEvent(
        type=EventType.CHAT_MESSAGE,
        payload={
            "text": text,
            "viewer": {
                "viewer_id": "viewer-1",
                "username": "tester",
                "platform": "local",
            },
        },
        priority=Priority.NORMAL,
        source="test",
    )


@pytest.mark.asyncio
async def test_semantic_aggregator_uses_embedding_clusters() -> None:
    bus = EventBus(queue_size=128)
    await bus.start()

    aggregator = SemanticAggregator(
        bus,
        window_ms=80,
        similarity_threshold=0.92,
        embedder=SemanticTestEmbedder(),
    )
    await aggregator.start()

    clusters: list[NovaEvent] = []

    async def capture(event: NovaEvent) -> None:
        clusters.append(event)

    bus.subscribe(EventType.SEMANTIC_CLUSTER, capture, sub_id="semantic-cluster-test")

    await bus.publish(_chat_event("awesome"))
    await bus.publish(_chat_event("so impressive"))
    await bus.publish(_chat_event("really strong"))
    await bus.publish(_chat_event("this game is too hard"))
    await asyncio.sleep(0.2)

    assert clusters
    largest = max(clusters, key=lambda event: event.payload["message_count"])
    assert largest.payload["message_count"] == 3
    assert largest.payload["cluster_similarity"] > 0.95

    await aggregator.stop()
    await bus.stop()


@pytest.mark.asyncio
async def test_orchestrator_question_route_increases_rag_depth() -> None:
    bus = EventBus(queue_size=128)
    await bus.start()
    try:
        llm = RecordingLLM()
        kb = FakeKnowledgeBase()
        orchestrator = Orchestrator(
            bus=bus,
            llm=llm,
            memory_agent=FakeMemory(),
            emotion_agent=FakeEmotionAgent(EmotionState.neutral()),
            personality_agent=FakePersonality(),
            knowledge_base=kb,
            nlu=FakeNLU(IntentResult(intent=IntentType.QUESTION, confidence=0.93)),
        )

        await orchestrator._pipeline(_chat_event("how does this mechanism work?"), ActionType.RESPOND)

        assert kb.calls
        _, top_k, score_threshold = kb.calls[-1]
        assert top_k == 5
        assert score_threshold == pytest.approx(0.18)
        assert llm.calls[-1]["max_tokens"] == 220
        assert "Intent: question" in llm.calls[-1]["messages"][-1]["content"]
        assert "Style: Answer directly, prioritize factual grounding" in llm.calls[-1]["messages"][-1]["content"]
    finally:
        await bus.stop()


@pytest.mark.asyncio
async def test_orchestrator_command_route_enables_tools_and_emotion_tone() -> None:
    bus = EventBus(queue_size=128)
    await bus.start()
    try:
        llm = RecordingLLM()

        class DummyTools:
            def all_definitions(self):
                return [{"type": "function", "function": {"name": "demo", "description": "demo", "parameters": {"type": "object"}}}]

        emotion = EmotionState(valence=0.8, arousal=0.9, label=EmotionLabel.EXCITED, intensity=0.9)
        orchestrator = Orchestrator(
            bus=bus,
            llm=llm,
            memory_agent=FakeMemory(),
            emotion_agent=FakeEmotionAgent(emotion),
            personality_agent=FakePersonality(),
            tool_registry=DummyTools(),
            nlu=FakeNLU(IntentResult(intent=IntentType.COMMAND, confidence=0.88)),
        )

        await orchestrator._pipeline(_chat_event("help me check the event schedule"), ActionType.RESPOND)

        call = llm.calls[-1]
        assert call["tools"] is not None
        assert call["max_tokens"] == 180
        assert "Tone: energetic and playful" in call["messages"][-1]["content"]
        assert "Route requirement: Treat this as an action request" in call["messages"][-1]["content"]
    finally:
        await bus.stop()


@pytest.mark.asyncio
async def test_orchestrator_does_not_double_apply_personality() -> None:
    bus = EventBus(queue_size=128)
    await bus.start()
    try:
        llm = RecordingLLM()

        class MarkingPersonality(FakePersonality):
            def apply_character(self, text: str) -> str:
                return text + "!"

        emitted: list[NovaEvent] = []

        async def capture(event: NovaEvent) -> None:
            emitted.append(event)

        bus.subscribe(EventType.ORCHESTRATOR_OUT, capture, sub_id="orch-capture")

        orchestrator = Orchestrator(
            bus=bus,
            llm=llm,
            memory_agent=FakeMemory(),
            emotion_agent=FakeEmotionAgent(EmotionState.neutral()),
            personality_agent=MarkingPersonality(),
            nlu=FakeNLU(IntentResult(intent=IntentType.GREETING, confidence=0.91)),
        )

        await orchestrator._pipeline(_chat_event("hello there"), ActionType.RESPOND)
        await asyncio.sleep(0.05)

        assert emitted
        assert emitted[-1].payload["text"] == "received.!"
        assert all("!!" not in event.payload["text"] for event in emitted)
    finally:
        await bus.stop()


@pytest.mark.asyncio
async def test_orchestrator_handles_sparse_tool_call_indexes() -> None:
    bus = EventBus(queue_size=128)
    await bus.start()
    try:
        handled: list[list[dict[str, Any]]] = []

        class DummyTools:
            def all_definitions(self):
                return [{"type": "function", "function": {"name": "demo", "description": "demo", "parameters": {"type": "object"}}}]

        class RecordingExecutor:
            async def handle_tool_calls(self, tool_calls):
                handled.append(tool_calls)
                return [{"tool_call_id": "call-2", "content": "tool ok"}]

        orchestrator = Orchestrator(
            bus=bus,
            llm=ToolCallOnlyLLM(),
            memory_agent=FakeMemory(),
            emotion_agent=FakeEmotionAgent(EmotionState.neutral()),
            personality_agent=FakePersonality(),
            tool_registry=DummyTools(),
            nlu=FakeNLU(IntentResult(intent=IntentType.COMMAND, confidence=0.95)),
        )
        orchestrator._tool_executor = RecordingExecutor()

        await orchestrator._pipeline(_chat_event("check tools"), ActionType.RESPOND)

        assert handled
        assert handled[0][2]["function"]["name"] == "demo"
        assert handled[0][2]["function"]["arguments"] == "{\"q\":\"x\"}"
    finally:
        await bus.stop()
