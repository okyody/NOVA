"""
NOVA LipSync Engine
====================
Real-time lip sync from audio energy analysis.

Approach: FFT-based energy mapping → mouth_open parameter.
Simple but effective for Live2D lip sync.

For more precise sync, consider OVR LipSync or Azure Viseme API
(which would be Phase 3+ additions).
"""
from __future__ import annotations

import asyncio
import logging
import math
import struct
from typing import Any

from packages.core.event_bus import EventBus
from packages.core.types import EventType, NovaEvent, Priority

log = logging.getLogger("nova.generation.lip_sync")


class LipSyncEngine:
    """
    Generates mouth_open values from audio energy.

    Subscribes to VOICE_CHUNK events and publishes refined
    AVATAR_COMMAND events with precise mouth sync.

    The engine uses a simple RMS energy calculation on audio
    chunks to determine mouth opening. A smoothing filter
    prevents jitter.
    """

    def __init__(
        self,
        bus: EventBus,
        sample_rate: int = 24000,
        smoothing: float = 0.3,
        min_open: float = 0.05,
        max_open: float = 0.9,
        silence_threshold: float = 0.01,
    ) -> None:
        self._bus = bus
        self._sample_rate = sample_rate
        self._smoothing = smoothing
        self._min_open = min_open
        self._max_open = max_open
        self._silence_threshold = silence_threshold

        self._prev_open = 0.0
        self._is_speaking = False

    async def start(self) -> None:
        self._bus.subscribe(
            EventType.VOICE_CHUNK, self._on_voice_chunk, sub_id="lipsync"
        )
        log.info("LipSync engine started")

    async def stop(self) -> None:
        pass

    async def _on_voice_chunk(self, event: NovaEvent) -> None:
        """Process a voice chunk and emit lip sync command."""
        is_final = event.payload.get("is_final", False)

        if is_final:
            # Mouth closed
            self._is_speaking = False
            self._prev_open = 0.0
            await self._bus.publish(NovaEvent(
                type=EventType.AVATAR_COMMAND,
                payload={
                    "expression": "neutral",
                    "mouth_open": 0.0,
                    "blend_time_ms": 100,
                },
                priority=Priority.HIGH,
                source="lip_sync",
                trace_id=event.payload.get("trace_id", ""),
            ))
            return

        audio_bytes = event.payload.get("audio_bytes", b"")
        if not audio_bytes:
            return

        # Calculate RMS energy
        mouth_open = self._audio_to_mouth(audio_bytes)

        # Apply smoothing (low-pass filter)
        mouth_open = self._prev_open + self._smoothing * (mouth_open - self._prev_open)
        self._prev_open = mouth_open

        # Clamp
        mouth_open = max(self._min_open if mouth_open > self._silence_threshold else 0.0,
                        min(mouth_open, self._max_open))

        self._is_speaking = mouth_open > 0.0

        await self._bus.publish(NovaEvent(
            type=EventType.AVATAR_COMMAND,
            payload={
                "expression": "talking" if mouth_open > 0.1 else "neutral",
                "mouth_open": round(mouth_open, 3),
                "blend_time_ms": 50,  # fast blend for lip sync
            },
            priority=Priority.HIGH,
            source="lip_sync",
            trace_id=event.payload.get("trace_id", ""),
        ))

    def _audio_to_mouth(self, audio_bytes: bytes) -> float:
        """
        Convert audio PCM bytes to a mouth_open value (0..1).

        Uses RMS energy normalization.
        """
        if len(audio_bytes) < 2:
            return 0.0

        # Parse as 16-bit PCM
        sample_count = len(audio_bytes) // 2
        samples = struct.unpack(f"<{sample_count}h", audio_bytes[:sample_count * 2])

        # Calculate RMS
        sum_sq = sum(s * s for s in samples)
        rms = math.sqrt(sum_sq / sample_count) if sample_count > 0 else 0.0

        # Normalize to 0..1 range (16-bit audio: max ~32768)
        # Typical speech RMS is 1000-8000, so we map accordingly
        normalized = min(rms / 5000.0, 1.0)

        # Apply non-linear mapping for more natural movement
        # Quiet sounds still show some movement, loud sounds saturate
        return math.pow(normalized, 0.7)
