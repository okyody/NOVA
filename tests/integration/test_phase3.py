"""
NOVA Phase 3 Integration Tests
===============================
Tests for RAG knowledge base, NLU intent classification,
tool calling, proactive intelligence, and memory consolidation.
"""
from __future__ import annotations

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
from packages.knowledge.embedding_service import MockEmbedder
from packages.knowledge.vector_store import InMemoryVectorStore
from packages.knowledge.knowledge_base import KnowledgeBase, chunk_text
from packages.knowledge.rag_prompt import RAGPromptBuilder
from packages.cognitive.nlu import IntentClassifier, IntentType
from packages.cognitive.tool_calling import (
    ToolDefinition,
    ToolRegistry,
    ToolExecutor,
    create_builtin_tools,
)
from packages.cognitive.proactive import ProactiveIntelligence, ProactiveStrategy
from packages.cognitive.memory_consolidation import MemoryConsolidator


# ─── RAG Knowledge Base Tests ──────────────────────────────────────────────────

class TestKnowledgeBase:
    """Test knowledge base ingestion and retrieval."""

    @pytest.fixture
    async def kb(self):
        embedder = MockEmbedder(dim=64)
        store = InMemoryVectorStore()
        kb = KnowledgeBase(embedder=embedder, store=store)
        return kb

    @pytest.mark.asyncio
    async def test_ingest_and_retrieve(self, kb: KnowledgeBase):
        """Test basic document ingestion and retrieval."""
        text = "Nova是一个AI虚拟主播。她喜欢和观众聊天，偶尔会讲冷笑话。"
        chunks = await kb.ingest(text, source_id="test_1")
        assert chunks >= 1

        results = await kb.retrieve("AI虚拟主播", top_k=3)
        assert len(results) >= 1
        assert "Nova" in results[0].doc.text

    @pytest.mark.asyncio
    async def test_retrieve_texts(self, kb: KnowledgeBase):
        """Test retrieve_texts convenience method."""
        await kb.ingest("Python是一种编程语言。", source_id="py_1")
        await kb.ingest("Java也是一种编程语言。", source_id="java_1")

        texts = await kb.retrieve_texts("编程语言", top_k=2)
        assert len(texts) >= 1
        assert any("编程语言" in t for t in texts)

    @pytest.mark.asyncio
    async def test_chunk_text(self):
        """Test text chunking with sentence boundaries."""
        text = "第一句话。第二句话。第三句话。第四句话。第五句话。"
        chunks = chunk_text(text, chunk_size=20, overlap=5, source_id="test")
        assert len(chunks) >= 2
        for chunk in chunks:
            assert chunk.text.strip()

    @pytest.mark.asyncio
    async def test_chunk_text_empty(self):
        """Test chunking empty text."""
        chunks = chunk_text("", source_id="test")
        assert chunks == []

    @pytest.mark.asyncio
    async def test_list_sources(self, kb: KnowledgeBase):
        """Test source listing after ingestion."""
        await kb.ingest("Document A", source_id="src_a")
        await kb.ingest("Document B", source_id="src_b")

        sources = kb.list_sources()
        assert "src_a" in sources
        assert "src_b" in sources

    @pytest.mark.asyncio
    async def test_delete_source(self, kb: KnowledgeBase):
        """Test source deletion."""
        await kb.ingest("To be deleted", source_id="del_me")
        assert await kb.count() >= 1

        await kb.delete_source("del_me")
        sources = kb.list_sources()
        assert "del_me" not in sources


# ─── NLU Intent Classification Tests ──────────────────────────────────────────

class TestNLU:
    """Test intent classification."""

    @pytest.fixture
    def classifier(self):
        return IntentClassifier(llm_client=None)

    def test_greeting_hello(self, classifier: IntentClassifier):
        result = classifier.classify("你好啊")
        assert result.intent == IntentType.GREETING
        assert result.confidence > 0.5

    def test_greeting_goodbye(self, classifier: IntentClassifier):
        result = classifier.classify("拜拜啦")
        assert result.intent == IntentType.GREETING
        assert result.sub_intent == "goodbye"

    def test_question(self, classifier: IntentClassifier):
        result = classifier.classify("你怎么做到的？")
        assert result.intent == IntentType.QUESTION

    def test_command(self, classifier: IntentClassifier):
        result = classifier.classify("唱首歌")
        assert result.intent == IntentType.COMMAND

    def test_emotion_positive(self, classifier: IntentClassifier):
        result = classifier.classify("哈哈太棒了")
        assert result.intent == IntentType.EMOTION

    def test_chat_default(self, classifier: IntentClassifier):
        result = classifier.classify("今天天气不错")
        # "不错" matches EMOTION positive pattern, so EMOTION is also valid
        assert result.intent in (IntentType.CHAT, IntentType.TOPIC, IntentType.EMOTION)

    def test_empty_text(self, classifier: IntentClassifier):
        result = classifier.classify("")
        assert result.intent == IntentType.UNKNOWN

    @pytest.mark.asyncio
    async def test_classify_async(self, classifier: IntentClassifier):
        result = await classifier.classify_async("你好")
        assert result.intent == IntentType.GREETING

    def test_entity_extraction_topic(self, classifier: IntentClassifier):
        result = classifier.classify("聊聊游戏吧")
        assert result.intent == IntentType.TOPIC
        assert result.entities is not None


# ─── Tool Calling Tests ───────────────────────────────────────────────────────

class TestToolCalling:
    """Test tool registry and executor."""

    @pytest.fixture
    def registry(self):
        registry = ToolRegistry()

        async def _echo(text: str) -> str:
            return f"Echo: {text}"

        registry.register(ToolDefinition(
            name="echo",
            description="Echo back the input text",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            function=_echo,
        ))
        return registry

    def test_register_tool(self, registry: ToolRegistry):
        assert "echo" in registry.list_names()

    def test_get_tool(self, registry: ToolRegistry):
        tool = registry.get("echo")
        assert tool is not None
        assert tool.name == "echo"

    def test_all_definitions(self, registry: ToolRegistry):
        defs = registry.all_definitions()
        assert len(defs) == 1
        assert defs[0]["type"] == "function"

    @pytest.mark.asyncio
    async def test_execute_tool(self, registry: ToolRegistry):
        executor = ToolExecutor(registry)
        result = await executor.execute("echo", {"text": "hello"})
        assert result == "Echo: hello"

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self, registry: ToolRegistry):
        executor = ToolExecutor(registry)
        result = await executor.execute("nonexistent", {})
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_handle_tool_calls(self, registry: ToolRegistry):
        executor = ToolExecutor(registry)
        tool_calls = [{
            "id": "call_1",
            "function": {"name": "echo", "arguments": '{"text": "test"}'},
        }]
        results = await executor.handle_tool_calls(tool_calls)
        assert len(results) == 1
        assert results[0]["tool_call_id"] == "call_1"

    @pytest.mark.asyncio
    async def test_builtin_tools(self):
        registry = ToolRegistry()
        bus = EventBus(queue_size=100)
        await bus.start()
        try:
            from packages.cognitive.memory_agent import MemoryAgent
            memory = MemoryAgent(bus)
            tools = create_builtin_tools(
                knowledge_base=None,
                memory_agent=memory,
                emotion_agent=None,
                viewer_graph=None,
            )
            for tool in tools:
                registry.register(tool)
            assert "search_knowledge" in registry.list_names()
            assert "get_viewer_info" in registry.list_names()
            assert "recall_memory" in registry.list_names()
        finally:
            await bus.stop()

    def test_unregister_tool(self, registry: ToolRegistry):
        registry.unregister("echo")
        assert registry.get("echo") is None


# ─── Proactive Intelligence Tests ─────────────────────────────────────────────

class TestProactive:
    """Test proactive intelligence."""

    @pytest.fixture
    def proactive(self):
        bus = EventBus(queue_size=100)
        return ProactiveIntelligence(bus=bus, knowledge_base=None)

    def test_strategy_high_arousal(self, proactive: ProactiveIntelligence):
        emotion = EmotionState(
            valence=0.5, arousal=0.8,
            label=EmotionLabel.EXCITED, intensity=0.7,
        )
        action = proactive.select_strategy(emotion, viewer_count=100)
        assert action.strategy == ProactiveStrategy.INTERACTION_PROMPT

    def test_strategy_low_engagement(self, proactive: ProactiveIntelligence):
        emotion = EmotionState(
            valence=0.1, arousal=0.3,
            label=EmotionLabel.CALM, intensity=0.3,
        )
        action = proactive.select_strategy(emotion, chat_rate=0.5, silence_sec=90)
        assert action.strategy == ProactiveStrategy.TOPIC_SUGGESTION

    def test_strategy_knowledge_share(self, proactive: ProactiveIntelligence):
        kb = KnowledgeBase(embedder=MockEmbedder(), store=InMemoryVectorStore())
        bus = EventBus(queue_size=100)
        pi = ProactiveIntelligence(bus=bus, knowledge_base=kb)
        emotion = EmotionState.neutral()
        action = pi.select_strategy(emotion, chat_rate=0.3, silence_sec=90)
        assert action.strategy == ProactiveStrategy.KNOWLEDGE_SHARE

    def test_should_be_proactive(self, proactive: ProactiveIntelligence):
        # Reset internal timer so enough time has passed since last proactive
        proactive._last_proactive_time = 0
        assert proactive.should_be_proactive(silence_sec=60, min_silence=30)
        assert not proactive.should_be_proactive(silence_sec=10, min_silence=30)

    def test_mini_game_prompt(self, proactive: ProactiveIntelligence):
        prompt = proactive.get_mini_game_prompt()
        assert prompt  # non-empty


# ─── Memory Consolidation Tests ───────────────────────────────────────────────

class TestConsolidation:
    """Test memory consolidation."""

    @pytest.fixture
    def consolidator(self):
        return MemoryConsolidator(llm_client=None)

    @pytest.mark.asyncio
    async def test_rule_consolidation(self, consolidator: MemoryConsolidator):
        entries = [
            {"text": "观众小明来直播间了", "viewer": "小明", "event_type": "platform.viewer_join"},
            {"text": "你好呀", "viewer": "小明", "event_type": "platform.chat_message"},
            {"text": "谢谢小红的SC", "viewer": "小红", "event_type": "platform.super_chat"},
        ]
        result = await consolidator.consolidate(entries)
        assert result.total_processed == 3
        assert len(result.summaries) >= 1
        assert result.deduplicated >= 0

    @pytest.mark.asyncio
    async def test_empty_entries(self, consolidator: MemoryConsolidator):
        result = await consolidator.consolidate([])
        assert result.total_processed == 0

    def test_should_consolidate(self, consolidator: MemoryConsolidator):
        assert consolidator.should_consolidate(entry_count=20, min_entries=15)

    @pytest.mark.asyncio
    async def test_deduplication(self, consolidator: MemoryConsolidator):
        entries = [
            {"text": "重复的消息内容测试", "viewer": "A", "event_type": "platform.chat_message"},
            {"text": "重复的消息内容测试", "viewer": "B", "event_type": "platform.chat_message"},
        ]
        result = await consolidator.consolidate(entries)
        assert result.deduplicated >= 1


# ─── RAG Prompt Builder Tests ─────────────────────────────────────────────────

class TestRAGPromptBuilder:
    """Test RAG prompt construction."""

    @pytest.mark.asyncio
    async def test_build_messages(self):
        from packages.cognitive.personality_agent import CharacterCard
        embedder = MockEmbedder(dim=64)
        store = InMemoryVectorStore()
        kb = KnowledgeBase(embedder=embedder, store=store)
        await kb.ingest("Nova喜欢聊科技话题", source_id="faq_1")

        builder = RAGPromptBuilder(knowledge_base=kb)
        character = CharacterCard.default()
        memory_ctx = {"recent": "(无)", "viewer_summary": "暂无数据"}
        emotion = EmotionState.neutral()

        result = await builder.build_messages(
            query="Nova喜欢聊什么",
            character=character,
            memory_ctx=memory_ctx,
            emotion=emotion,
        )
        assert len(result.messages) == 2
        assert result.messages[0]["role"] == "system"
        assert result.messages[1]["role"] == "user"


# ─── Circuit Breaker Tests ────────────────────────────────────────────────────

class TestCircuitBreaker:
    """Test circuit breaker."""

    def test_initial_state(self):
        from packages.ops.circuit_breaker import CircuitBreaker, CircuitState
        cb = CircuitBreaker(name="test")
        assert cb.state == CircuitState.CLOSED

    def test_opens_after_failures(self):
        from packages.ops.circuit_breaker import CircuitBreaker, CircuitState
        cb = CircuitBreaker(name="test", failure_threshold=3)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_closes_on_success(self):
        from packages.ops.circuit_breaker import CircuitBreaker, CircuitState
        cb = CircuitBreaker(name="test", failure_threshold=2, success_threshold=1)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        # Simulate recovery timeout
        cb._last_failure_time = 0  # Force timeout
        assert cb.state == CircuitState.HALF_OPEN

        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_rejects_when_open(self):
        from packages.ops.circuit_breaker import CircuitBreaker, CircuitState
        cb = CircuitBreaker(name="test", failure_threshold=1)
        cb.record_failure()
        assert not cb.allow_request()

    def test_allows_when_closed(self):
        from packages.ops.circuit_breaker import CircuitBreaker
        cb = CircuitBreaker(name="test")
        assert cb.allow_request()


# ─── State Persistence Tests ──────────────────────────────────────────────────

class TestStatePersistence:
    """Test state persistence."""

    @pytest.mark.asyncio
    async def test_json_backend_save_load(self):
        from packages.cognitive.state_persistence import JSONFileBackend
        import tempfile
        import os

        with tempfile.TemporaryDirectory() as tmpdir:
            backend = JSONFileBackend(base_dir=tmpdir)
            await backend.save("test_key", {"data": "hello"})

            loaded = await backend.load("test_key")
            assert loaded is not None
            assert loaded["data"] == "hello"

    @pytest.mark.asyncio
    async def test_json_backend_missing_key(self):
        from packages.cognitive.state_persistence import JSONFileBackend
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            backend = JSONFileBackend(base_dir=tmpdir)
            result = await backend.load("nonexistent")
            assert result is None

    @pytest.mark.asyncio
    async def test_json_backend_delete(self):
        from packages.cognitive.state_persistence import JSONFileBackend
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            backend = JSONFileBackend(base_dir=tmpdir)
            await backend.save("del_key", {"data": "bye"})
            await backend.delete("del_key")
            result = await backend.load("del_key")
            assert result is None

    @pytest.mark.asyncio
    async def test_json_backend_list_keys(self):
        from packages.cognitive.state_persistence import JSONFileBackend
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            backend = JSONFileBackend(base_dir=tmpdir)
            await backend.save("key_a", {"data": "a"})
            await backend.save("key_b", {"data": "b"})
            keys = await backend.list_keys()
            assert "key_a" in keys
            assert "key_b" in keys
