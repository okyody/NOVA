"""
NOVA Voice Pipeline
===================
Converts text + emotion state → streaming audio.

2026 design: end-to-end voice model preferred (GPT-4o Audio, CosyVoice 2).
Fallback chain: E2E model → edge-tts (lowest latency, always available).

The pipeline:
  1. Receives ORCHESTRATOR_OUT event
  2. Applies emotion → prosody parameters
  3. Streams audio chunks to VOICE_CHUNK events as they arrive
  4. Concurrently drives avatar via AVATAR_COMMAND events

Audio is delivered as raw PCM (24kHz, mono, int16) for maximum flexibility.
The stream compositor converts to whatever the output needs.
"""
from __future__ import annotations

import asyncio
import io
import logging
import struct
import time
from dataclasses import dataclass
from typing import AsyncIterator

from packages.core.event_bus import EventBus
from packages.core.types import (
    AvatarCommand,
    EmotionLabel,
    EmotionState,
    EventType,
    NovaEvent,
    Priority,
    VoiceChunk,
)

log = logging.getLogger("nova.voice_pipeline")


# ─── Prosody parameters ───────────────────────────────────────────────────────

@dataclass
class ProsodyParams:
    rate:   str   = "+0%"      # edge-tts format: "+10%" = 10% faster
    pitch:  str   = "+0Hz"     # "+5Hz" shifts up
    volume: str   = "+0%"

    @classmethod
    def from_emotion(cls, emotion: EmotionState) -> "ProsodyParams":
        p = emotion.to_prosody_params()
        rate_pct  = int((p["speaking_rate"] - 1.0) * 100)
        pitch_hz  = int(p["pitch_shift"] * 8)     # semitones → ~Hz offset
        vol_pct   = int((p["energy"] - 1.0) * 20)

        return cls(
            rate   = f"{rate_pct:+d}%",
            pitch  = f"{pitch_hz:+d}Hz",
            volume = f"{vol_pct:+d}%",
        )


# ─── TTS Backend interface ────────────────────────────────────────────────────

class TTSBackend:
    """Abstract TTS backend. Implementations yield PCM bytes."""

    async def synthesize(
        self,
        text: str,
        voice: str,
        prosody: ProsodyParams,
    ) -> AsyncIterator[bytes]:
        raise NotImplementedError


class EdgeTTSBackend(TTSBackend):
    """
    edge-tts backend — free, low-latency, decent quality.
    Install: pip install edge-tts
    """

    async def synthesize(
        self,
        text: str,
        voice: str = "zh-CN-XiaoyiNeural",
        prosody: ProsodyParams = ProsodyParams(),
    ) -> AsyncIterator[bytes]:
        try:
            import edge_tts
        except ImportError:
            log.error("edge-tts not installed. Run: pip install edge-tts")
            return

        communicate = edge_tts.Communicate(
            text=text,
            voice=voice,
            rate=prosody.rate,
            pitch=prosody.pitch,
            volume=prosody.volume,
        )
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                yield chunk["data"]


class CosyVoice2Backend(TTSBackend):
    """
    CosyVoice 2 local inference backend.
    Requires: CosyVoice2 running at localhost:7860

    Superior emotion-aware voice synthesis — preferred when available.
    """

    def __init__(self, api_url: str = "http://localhost:7860") -> None:
        self._url = api_url

    async def synthesize(
        self,
        text: str,
        voice: str = "default",
        prosody: ProsodyParams = ProsodyParams(),
    ) -> AsyncIterator[bytes]:
        import httpx
        payload = {
            "text":    text,
            "speaker": voice,
            "speed":   1.0 + float(prosody.rate.rstrip("%")) / 100,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            async with client.stream("POST", f"{self._url}/synthesize", json=payload) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes(4096):
                    yield chunk


# ─── Avatar expression mapper ─────────────────────────────────────────────────

_EMOTION_TO_EXPRESSION: dict[EmotionLabel, dict] = {
    EmotionLabel.EXCITED:   {"expression": "excited",   "eye_blink": 0.3, "head_tilt": -5.0},
    EmotionLabel.HAPPY:     {"expression": "smile",     "eye_blink": 0.2, "head_tilt": -3.0},
    EmotionLabel.CURIOUS:   {"expression": "curious",   "eye_blink": 0.1, "head_tilt": 8.0},
    EmotionLabel.SURPRISED: {"expression": "surprised", "eye_blink": 0.5, "head_tilt": 0.0},
    EmotionLabel.SAD:       {"expression": "sad",       "eye_blink": 0.15, "head_tilt": 5.0},
    EmotionLabel.ANXIOUS:   {"expression": "nervous",   "eye_blink": 0.4, "head_tilt": 2.0},
    EmotionLabel.CALM:      {"expression": "calm",      "eye_blink": 0.1, "head_tilt": 0.0},
    EmotionLabel.NEUTRAL:   {"expression": "neutral",   "eye_blink": 0.15, "head_tilt": 0.0},
}


def _build_avatar_command(
    emotion: EmotionState,
    mouth_open: float = 0.0,
    is_speaking: bool = False,
) -> AvatarCommand:
    base = _EMOTION_TO_EXPRESSION.get(emotion.label, {"expression": "neutral"})
    return AvatarCommand(
        expression  = base["expression"],
        mouth_open  = mouth_open if is_speaking else 0.0,
        eye_blink   = base.get("eye_blink", 0.15),
        head_tilt   = base.get("head_tilt", 0.0) * emotion.intensity,
        blend_time_ms = 80,
    )


# ─── Voice Pipeline ───────────────────────────────────────────────────────────

class VoicePipeline:
    """
    Subscribes to SAFE_OUTPUT events and streams voice + avatar commands.

    With streaming orchestrator:
      - Each SAFE_OUTPUT contains one sentence (sentence_index >= 0)
      - TTS synthesis starts immediately per sentence (lower first-byte latency)
      - Audio chunks are streamed as they arrive

    Publishes:
      VOICE_CHUNK    — raw audio bytes (24kHz PCM)
      AVATAR_COMMAND — expression/lip sync commands for avatar driver
    """

    def __init__(
        self,
        bus: EventBus,
        backend: TTSBackend | None = None,
        voice_id: str = "zh-CN-XiaoyiNeural",
    ) -> None:
        self._bus     = bus
        self._backend = backend or EdgeTTSBackend()
        self._voice   = voice_id
        self._current_emotion = EmotionState.neutral()
        self._speak_tasks: dict[str, asyncio.Task] = {}  # trace_id → task

    async def start(self) -> None:
        self._bus.subscribe(
            EventType.SAFE_OUTPUT, self._on_output, sub_id="voice_output"
        )
        self._bus.subscribe(
            EventType.EMOTION_STATE, self._on_emotion, sub_id="voice_emotion"
        )
        log.info("Voice pipeline started (voice=%s)", self._voice)

    async def stop(self) -> None:
        for task in self._speak_tasks.values():
            task.cancel()

    async def _on_emotion(self, event: NovaEvent) -> None:
        """Track current emotion for prosody."""
        from packages.core.types import EmotionLabel
        self._current_emotion = EmotionState(
            valence=event.payload["valence"],
            arousal=event.payload["arousal"],
            label=EmotionLabel(event.payload["label"]),
            intensity=event.payload["intensity"],
        )

    async def _on_output(self, event: NovaEvent) -> None:
        text = event.payload.get("text", "")
        trace_id = event.payload.get("trace_id", event.event_id)
        is_final = event.payload.get("is_final", False)
        sentence_index = event.payload.get("sentence_index", 0)

        if not text:
            # Still emit final chunk marker for this trace if needed
            if is_final or sentence_index == 0:
                await self._emit_final_chunk(trace_id)
                await self._emit_avatar(mouth_open=0.0, is_speaking=False, trace_id=trace_id)
            return

        # For the first sentence of a new trace, cancel any ongoing speech
        if sentence_index == 0 and trace_id in self._speak_tasks:
            old_task = self._speak_tasks[trace_id]
            if not old_task.done():
                old_task.cancel()

        # Start speaking avatar on first sentence
        if sentence_index == 0:
            await self._emit_avatar(mouth_open=0.6, is_speaking=True, trace_id=trace_id)

        # Stream this sentence's audio
        task = asyncio.create_task(
            self._stream_sentence(text, trace_id, is_final),
            name=f"nova.voice.speak.{trace_id[:8]}.{sentence_index}",
        )
        self._speak_tasks[trace_id] = task

        # Cleanup completed tasks
        done_keys = [k for k, v in self._speak_tasks.items() if v.done()]
        for k in done_keys:
            del self._speak_tasks[k]

    async def _stream_sentence(self, text: str, trace_id: str, is_final: bool) -> None:
        """Stream TTS audio for a single sentence."""
        prosody = ProsodyParams.from_emotion(self._current_emotion)
        chunk_index = 0
        t0 = time.monotonic()

        try:
            async for audio_bytes in self._backend.synthesize(text, self._voice, prosody):
                await self._bus.publish(NovaEvent(
                    type=EventType.VOICE_CHUNK,
                    payload={
                        "audio_bytes": audio_bytes,
                        "chunk_index": chunk_index,
                        "is_final":    False,
                        "sample_rate": 24000,
                        "trace_id":    trace_id,
                    },
                    priority=Priority.HIGH,
                    source="voice_pipeline",
                    trace_id=trace_id,
                ))
                chunk_index += 1

        except Exception as exc:
            log.error("TTS synthesis failed for sentence: %s", exc)
        finally:
            if is_final:
                await self._emit_final_chunk(trace_id)
                await self._emit_avatar(mouth_open=0.0, is_speaking=False, trace_id=trace_id)
            elapsed = (time.monotonic() - t0) * 1000
            log.debug("Sentence streamed: %d chunks, %.0f ms", chunk_index, elapsed)

    async def _emit_final_chunk(self, trace_id: str) -> None:
        """Emit the is_final voice chunk to signal end of speech."""
        await self._bus.publish(NovaEvent(
            type=EventType.VOICE_CHUNK,
            payload={"audio_bytes": b"", "is_final": True, "trace_id": trace_id},
            priority=Priority.HIGH,
            source="voice_pipeline",
            trace_id=trace_id,
        ))

    async def _emit_avatar(
        self, mouth_open: float, is_speaking: bool, trace_id: str
    ) -> None:
        cmd = _build_avatar_command(self._current_emotion, mouth_open, is_speaking)
        await self._bus.publish(NovaEvent(
            type=EventType.AVATAR_COMMAND,
            payload={
                "expression":    cmd.expression,
                "mouth_open":    cmd.mouth_open,
                "eye_blink":     cmd.eye_blink,
                "head_tilt":     cmd.head_tilt,
                "blend_time_ms": cmd.blend_time_ms,
            },
            priority=Priority.HIGH,
            source="voice_pipeline",
            trace_id=trace_id,
        ))
