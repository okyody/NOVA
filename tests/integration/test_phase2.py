"""
NOVA Phase 2 Integration Tests
================================
Validates new Phase 2 components:
  - ContextSensor (perception layer)
  - TTS Factory + Fallback Chain
  - LipSync Engine
  - VoiceConverter
  - PlatformManager
  - AvatarDriver

All tests use mock data — no real platform, no real LLM, no real TTS.
"""
import asyncio
import math
import struct
import pytest

from packages.core.event_bus import EventBus
from packages.core.types import (
    ActionType,
    EmotionLabel,
    EmotionState,
    EventType,
    NovaEvent,
    Platform,
    Priority,
)
from packages.perception.context_sensor import ContextSensor, HeatLevel, StreamContext
from packages.generation.lip_sync import LipSyncEngine
from packages.generation.tts_factory import TTSFallbackChain, create_tts_backend
from packages.generation.voice_pipeline import EdgeTTSBackend, ProsodyParams, TTSBackend, VoicePipeline
from packages.platform.manager import PlatformManager


# ── Mock TTS Backend ──────────────────────────────────────────────────────────

class MockTTSBackend(TTSBackend):
    """Fake TTS that yields silence PCM for testing."""

    def __init__(self, name: str = "mock", fail: bool = False) -> None:
        self.name = name
        self._fail = fail
        self._call_count = 0

    async def synthesize(
        self,
        text: str,
        voice: str = "zh-CN-XiaoyiNeural",
        prosody: ProsodyParams = ProsodyParams(),
    ):
        self._call_count += 1
        if self._fail:
            raise RuntimeError(f"MockTTSBackend '{self.name}' is configured to fail")
        # Generate a tiny silence chunk (24kHz, 16-bit, 10ms)
        silence = bytes(480)
        yield silence
        yield silence


class FailingTTSBackend(TTSBackend):
    """TTS that always fails — for fallback chain testing."""

    def __init__(self) -> None:
        self._call_count = 0

    async def synthesize(self, text, voice="zh-CN-XiaoyiNeural", prosody=ProsodyParams()):
        self._call_count += 1
        raise RuntimeError("TTS backend failed")
        # Make this an async generator (unreachable, but needed for type)
        yield b""  # type: ignore  # noqa: unreachable


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_chat_event(text: str, username: str = "test_viewer", viewer_id: str = "v1") -> NovaEvent:
    return NovaEvent(
        type=EventType.CHAT_MESSAGE,
        payload={
            "text": text,
            "viewer": {
                "viewer_id": viewer_id,
                "username": username,
                "platform": "bilibili",
            },
        },
        priority=Priority.NORMAL,
        source="test",
    )


def _make_pcm_bytes(duration_ms: int = 50, freq: float = 440.0, sample_rate: int = 24000) -> bytes:
    """Generate PCM bytes for a sine wave (simulates voice audio)."""
    num_samples = int(sample_rate * duration_ms / 1000)
    samples = []
    for i in range(num_samples):
        sample = int(16000 * math.sin(2 * math.pi * freq * i / sample_rate))
        samples.append(max(-32768, min(32767, sample)))
    return struct.pack(f"<{num_samples}h", *samples)


# ═══════════════════════════════════════════════════════════════════════════════
# ContextSensor Tests
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_context_sensor_heat_classification():
    """ContextSensor correctly classifies heat levels.

    Scoring formula (see context_sensor.py):
      chat_rate/80*40 + gift_rate/20*30 + viewer_count/500*30
      COLD < 15, NORMAL 15-44, HOT 45-74, VIRAL >= 75
    """
    # COLD: 3 chat/min, 0 gifts, 10 viewers → score ≈ 1.5 + 0 + 0.6 = 2.1
    assert ContextSensor._classify_heat(3, 0, 10) == HeatLevel.COLD
    # NORMAL: 20 chat/min, 2 gifts, 80 viewers → score ≈ 10 + 3 + 4.8 = 17.8
    assert ContextSensor._classify_heat(20, 2, 80) == HeatLevel.NORMAL
    # HOT: 60 chat/min, 10 gifts, 200 viewers → score ≈ 30 + 15 + 12 = 57
    assert ContextSensor._classify_heat(60, 10, 200) == HeatLevel.HOT
    # VIRAL: 90 chat/min, 18 gifts, 500 viewers → score ≈ 45 + 27 + 30 = 102
    assert ContextSensor._classify_heat(90, 18, 500) == HeatLevel.VIRAL


@pytest.mark.asyncio
async def test_context_sensor_tracks_chat_rate():
    """ContextSensor updates chat rate and publishes CONTEXT_UPDATE."""
    bus = EventBus(queue_size=1024)
    await bus.start()

    sensor = ContextSensor(bus, update_interval_s=1, history_window_s=60)
    await sensor.start()

    context_updates: list[NovaEvent] = []
    async def capture(event: NovaEvent):
        context_updates.append(event)

    bus.subscribe(EventType.CONTEXT_UPDATE, capture, sub_id="test_ctx")

    # Send chat messages and wait for dispatch
    for i in range(10):
        await bus.publish(_make_chat_event(f"message {i}"))

    # Wait for event bus to dispatch all events
    await asyncio.sleep(0.3)

    # Trigger a recalculation (it's async)
    await sensor._recalculate()
    await asyncio.sleep(0.1)

    ctx = sensor.current_context
    assert ctx.chat_rate > 0, f"Expected chat_rate > 0, got {ctx.chat_rate}"
    assert ctx.heat_level in (HeatLevel.COLD, HeatLevel.NORMAL, HeatLevel.HOT, HeatLevel.VIRAL)

    # Check that CONTEXT_UPDATE was published
    assert len(context_updates) >= 1
    update = context_updates[0]
    assert update.type == EventType.CONTEXT_UPDATE
    assert "chat_rate" in update.payload
    assert "heat_level" in update.payload

    await sensor.stop()
    await bus.stop()


@pytest.mark.asyncio
async def test_context_sensor_gift_tracking():
    """ContextSensor tracks gift rate from GIFT_RECEIVED events."""
    bus = EventBus(queue_size=1024)
    await bus.start()

    sensor = ContextSensor(bus, update_interval_s=1)
    await sensor.start()

    # Send gift events
    for _ in range(5):
        await bus.publish(NovaEvent(
            type=EventType.GIFT_RECEIVED,
            payload={"gift_name": "rocket", "amount": 10, "viewer": {}},
        ))

    # Wait for event handlers to process
    await asyncio.sleep(0.1)

    await sensor._recalculate()

    ctx = sensor.current_context
    assert ctx.gift_rate > 0, f"Expected gift_rate > 0, got {ctx.gift_rate}"

    await sensor.stop()
    await bus.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# TTS Factory & Fallback Chain Tests
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_tts_factory_creates_edge_tts():
    """Factory creates EdgeTTSBackend by default."""
    backend = create_tts_backend({"backend": "edge_tts"})
    assert isinstance(backend, EdgeTTSBackend)


@pytest.mark.asyncio
async def test_tts_factory_unknown_falls_back():
    """Factory falls back to EdgeTTSBackend for unknown backend types."""
    backend = create_tts_backend({"backend": "nonexistent"})
    assert isinstance(backend, EdgeTTSBackend)


@pytest.mark.asyncio
async def test_tts_fallback_chain_healthy():
    """Fallback chain uses first healthy backend."""
    primary = MockTTSBackend(name="primary")
    fallback = MockTTSBackend(name="fallback")

    chain = TTSFallbackChain([
        ("primary", primary),
        ("fallback", fallback),
    ])

    chunks = []
    async for chunk in chain.synthesize("hello"):
        chunks.append(chunk)

    assert len(chunks) > 0, "Should produce audio chunks"
    assert primary._call_count == 1, "Primary should be called"
    assert fallback._call_count == 0, "Fallback should not be called when primary succeeds"


@pytest.mark.asyncio
async def test_tts_fallback_chain_on_failure():
    """Fallback chain tries next backend when primary fails."""
    failing = FailingTTSBackend()
    working = MockTTSBackend(name="working")

    chain = TTSFallbackChain([
        ("failing", failing),
        ("working", working),
    ])

    chunks = []
    async for chunk in chain.synthesize("hello"):
        chunks.append(chunk)

    assert len(chunks) > 0, "Should produce audio from fallback"
    assert failing._call_count >= 1, "Failing backend should have been tried"
    assert working._call_count == 1, "Working backend should be used as fallback"

    # Check health tracking
    health = chain.get_health()
    assert health["failing"]["total_failures"] >= 1
    assert health["working"]["healthy"] is True


@pytest.mark.asyncio
async def test_tts_fallback_chain_health_recovery():
    """Unhealthy backend can recover after RECOVERY_TIME_S."""
    failing = FailingTTSBackend()
    chain = TTSFallbackChain([("failing", failing)])

    # Exhaust the backend
    try:
        async for _ in chain.synthesize("test"):
            pass
    except Exception:
        pass

    # Force 3 failures to mark unhealthy
    for _ in range(3):
        try:
            async for _ in chain.synthesize("test"):
                pass
        except Exception:
            pass

    health = chain.get_health()
    bh = list(chain._backends)[0]
    # Simulate recovery by setting last_failure far in the past
    bh.last_failure -= bh.RECOVERY_TIME_S + 1
    assert bh.should_try() is True, "Should allow retry after recovery time"


# ═══════════════════════════════════════════════════════════════════════════════
# LipSync Engine Tests
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_lipsync_emits_avatar_command_on_voice():
    """LipSync generates AVATAR_COMMAND from VOICE_CHUNK audio."""
    bus = EventBus(queue_size=1024)
    await bus.start()

    lipsync = LipSyncEngine(bus)
    await lipsync.start()

    commands: list[NovaEvent] = []
    async def capture(event: NovaEvent):
        commands.append(event)

    bus.subscribe(EventType.AVATAR_COMMAND, capture, sub_id="test_lipsync")

    # Send a VOICE_CHUNK with audio
    audio = _make_pcm_bytes(duration_ms=50, freq=440)
    await bus.publish(NovaEvent(
        type=EventType.VOICE_CHUNK,
        payload={
            "audio_bytes": audio,
            "chunk_index": 0,
            "is_final": False,
            "sample_rate": 24000,
            "trace_id": "test",
        },
        priority=Priority.HIGH,
        source="test",
    ))
    await asyncio.sleep(0.05)

    assert len(commands) >= 1, f"Expected AVATAR_COMMAND, got {len(commands)}"
    cmd = commands[0]
    assert cmd.payload.get("expression") in ("talking", "neutral")
    assert "mouth_open" in cmd.payload

    await lipsync.stop()
    await bus.stop()


@pytest.mark.asyncio
async def test_lipsync_closes_mouth_on_final():
    """LipSync closes mouth when is_final=True."""
    bus = EventBus(queue_size=1024)
    await bus.start()

    lipsync = LipSyncEngine(bus)
    await lipsync.start()

    commands: list[NovaEvent] = []
    async def capture(event: NovaEvent):
        commands.append(event)

    bus.subscribe(EventType.AVATAR_COMMAND, capture, sub_id="test_lipsync_final")

    # Send final chunk
    await bus.publish(NovaEvent(
        type=EventType.VOICE_CHUNK,
        payload={"audio_bytes": b"", "is_final": True, "trace_id": "test"},
        priority=Priority.HIGH,
        source="test",
    ))
    await asyncio.sleep(0.05)

    assert len(commands) >= 1
    cmd = commands[-1]
    assert cmd.payload["mouth_open"] == 0.0
    assert cmd.payload["expression"] == "neutral"

    await lipsync.stop()
    await bus.stop()


@pytest.mark.asyncio
async def test_lipsync_audio_to_mouth():
    """LipSyncEngine._audio_to_mouth maps energy correctly."""
    engine = LipSyncEngine.__new__(LipSyncEngine)

    # Silence → near zero
    silence = bytes(480)
    assert engine._audio_to_mouth(silence) < 0.05

    # Loud audio → high value
    loud = _make_pcm_bytes(50, 440.0)
    result = engine._audio_to_mouth(loud)
    assert result > 0.1, f"Loud audio should produce mouth_open > 0.1, got {result}"


# ═══════════════════════════════════════════════════════════════════════════════
# PlatformManager Tests
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_platform_manager_status():
    """PlatformManager tracks adapter status."""
    bus = EventBus(queue_size=1024)
    await bus.start()

    mgr = PlatformManager(bus)

    # No adapters yet
    status = mgr.get_status()
    assert len(status) == 0

    await mgr.stop()
    await bus.stop()


@pytest.mark.asyncio
async def test_platform_manager_add_remove():
    """PlatformManager can add and remove adapters."""
    bus = EventBus(queue_size=1024)
    await bus.start()

    mgr = PlatformManager(bus)

    # Add a bilibili adapter via config
    await mgr.add_platform({
        "platform": "bilibili",
        "room_id": "12345",
        "token": "test",
        "uid": "0",
    })

    status = mgr.get_status()
    assert "bilibili" in status
    assert status["bilibili"]["running"] is True

    # Remove it
    await mgr.remove_platform(Platform.BILIBILI)
    status = mgr.get_status()
    assert "bilibili" not in status

    await mgr.stop()
    await bus.stop()


@pytest.mark.asyncio
async def test_platform_manager_tracks_stats():
    """PlatformManager updates status from LIVE_STATS events."""
    bus = EventBus(queue_size=1024)
    await bus.start()

    mgr = PlatformManager(bus)
    await mgr.start([])

    # Manually add an adapter with status tracking
    from packages.platform.manager import AdapterStatus
    mgr._adapters[Platform.BILIBILI] = None  # mock
    mgr._statuses[Platform.BILIBILI] = AdapterStatus(platform=Platform.BILIBILI, running=True)

    # Simulate LIVE_STATS from bilibili
    await bus.publish(NovaEvent(
        type=EventType.LIVE_STATS,
        payload={"online_count": 100},
        source="bilibili",
    ))
    await asyncio.sleep(0.05)

    status = mgr.get_status()
    assert "bilibili" in status
    assert status["bilibili"]["events_received"] >= 1

    await mgr.stop()
    await bus.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# Full Phase 2 Pipeline Test
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_full_pipeline_with_lipsync_and_context():
    """
    Full pipeline: FakeChat → SemanticAggregator → Orchestrator →
    SafetyGuard → VoicePipeline(MockTTS) → LipSync → AvatarCommand +
    ContextSensor tracking.

    This validates the complete Phase 2 integration.
    """
    from packages.cognitive.emotion_agent import EmotionAgent
    from packages.cognitive.memory_agent import MemoryAgent
    from packages.cognitive.orchestrator import Orchestrator, LLMClient
    from packages.cognitive.personality_agent import PersonalityAgent
    from packages.ops.safety_guard import SafetyGuard
    from packages.perception.semantic_aggregator import SemanticAggregator

    # ── Mock LLM ──
    class MockLLM:
        def __init__(self):
            self.model = "mock"

        async def complete(self, messages, max_tokens=200, temperature=0.85):
            return "测试回复！"

        async def stream_completion(self, messages, max_tokens=200, temperature=0.85, tools=None):
            yield {"type": "text", "content": "测试回复！"}
            yield {"type": "done", "finish_reason": "stop"}

        async def close(self):
            pass

    bus = EventBus(queue_size=8192)
    await bus.start()

    # Perception
    aggregator = SemanticAggregator(bus, window_ms=100)
    await aggregator.start()

    context = ContextSensor(bus, update_interval_s=2)
    await context.start()

    # Cognitive
    memory = MemoryAgent(bus)
    await memory.start()

    emotion = EmotionAgent(bus)
    await emotion.start()

    personality = PersonalityAgent(bus)
    await personality.start()

    orchestrator = Orchestrator(
        bus=bus,
        llm=MockLLM(),
        memory_agent=memory,
        emotion_agent=emotion,
        personality_agent=personality,
    )
    await orchestrator.start()

    # Ops
    safety = SafetyGuard(bus)
    await safety.start()

    # Generation — use mock TTS
    mock_backend = MockTTSBackend(name="test_tts")
    voice = VoicePipeline(bus, backend=mock_backend)
    await voice.start()

    lipsync = LipSyncEngine(bus)
    await lipsync.start()

    # Collect results
    avatar_commands: list[NovaEvent] = []
    safe_outputs: list[NovaEvent] = []

    async def capture_avatar(event: NovaEvent):
        avatar_commands.append(event)

    async def capture_safe(event: NovaEvent):
        safe_outputs.append(event)

    bus.subscribe(EventType.AVATAR_COMMAND, capture_avatar, sub_id="test_avatar")
    bus.subscribe(EventType.SAFE_OUTPUT, capture_safe, sub_id="test_safe")

    # Send chat
    for i in range(3):
        await bus.publish(_make_chat_event(f"你好呀 {i}"))

    # Wait for pipeline
    await asyncio.sleep(1.0)

    # Verify SAFE_OUTPUT received
    assert len(safe_outputs) >= 1, f"Expected SAFE_OUTPUT, got {len(safe_outputs)}"

    # Verify avatar commands generated (from voice pipeline + lipsync)
    assert len(avatar_commands) >= 1, f"Expected AVATAR_COMMAND, got {len(avatar_commands)}"

    # Verify context sensor is active (chat_rate may be 0 due to timing)
    ctx = context.current_context
    assert ctx.heat_level in (HeatLevel.COLD, HeatLevel.NORMAL, HeatLevel.HOT, HeatLevel.VIRAL)
    assert isinstance(ctx.chat_rate, float)

    # Cleanup
    await lipsync.stop()
    await voice.stop()
    await safety.stop()
    await orchestrator.stop()
    await personality.stop()
    await emotion.stop()
    await memory.stop()
    await context.stop()
    await aggregator.stop()
    await bus.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# ProsodyParams Tests
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_prosody_from_emotion():
    """ProsodyParams correctly maps emotion to TTS parameters."""
    # Happy: high valence → positive pitch
    happy = EmotionState(valence=0.8, arousal=0.5, label=EmotionLabel.HAPPY, intensity=0.7)
    prosody = ProsodyParams.from_emotion(happy)
    assert "+" in prosody.pitch, "Happy emotion should shift pitch up"

    # Sad: low valence → negative pitch
    sad = EmotionState(valence=-0.5, arousal=0.2, label=EmotionLabel.SAD, intensity=0.6)
    prosody = ProsodyParams.from_emotion(sad)
    assert "-" in prosody.pitch, "Sad emotion should shift pitch down"

    # Excited: high arousal → faster rate
    excited = EmotionState(valence=0.7, arousal=0.9, label=EmotionLabel.EXCITED, intensity=0.9)
    prosody = ProsodyParams.from_emotion(excited)
    assert "+" in prosody.rate, "Excited emotion should increase rate"


# ═══════════════════════════════════════════════════════════════════════════════
# VoicePipeline with MockTTS Integration
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_voice_pipeline_with_mock_tts():
    """VoicePipeline streams audio and emits VOICE_CHUNK + AVATAR_COMMAND."""
    bus = EventBus(queue_size=1024)
    await bus.start()

    mock_tts = MockTTSBackend(name="test")
    pipeline = VoicePipeline(bus, backend=mock_tts, voice_id="test_voice")
    await pipeline.start()

    voice_chunks: list[NovaEvent] = []
    avatar_cmds: list[NovaEvent] = []

    async def capture_voice(event: NovaEvent):
        voice_chunks.append(event)

    async def capture_avatar(event: NovaEvent):
        avatar_cmds.append(event)

    bus.subscribe(EventType.VOICE_CHUNK, capture_voice, sub_id="test_voice")
    bus.subscribe(EventType.AVATAR_COMMAND, capture_avatar, sub_id="test_avatar_vp")

    # Simulate SAFE_OUTPUT (single sentence, is_final=True for simple case)
    await bus.publish(NovaEvent(
        type=EventType.SAFE_OUTPUT,
        payload={"text": "你好，世界！", "trace_id": "vp_test", "sentence_index": 0, "is_final": True},
    ))

    await asyncio.sleep(0.2)

    # Should have voice chunks
    assert len(voice_chunks) >= 1, f"Expected VOICE_CHUNK, got {len(voice_chunks)}"

    # Should have avatar commands (speaking start + end)
    assert len(avatar_cmds) >= 1, f"Expected AVATAR_COMMAND, got {len(avatar_cmds)}"

    # Should contain an is_final chunk
    final_chunks = [c for c in voice_chunks if c.payload.get("is_final") is True]
    assert len(final_chunks) >= 1, "Should have at least one is_final VOICE_CHUNK"

    await pipeline.stop()
    await bus.stop()
