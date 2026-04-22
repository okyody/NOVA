"""
NOVA Silence Detector
=====================
Monitors the event stream and publishes SILENCE_DETECTED
when no CHAT_MESSAGE has arrived for N seconds.

Triggers proactive speech from the Orchestrator.
Configurable threshold (default 45s) with reset after Nova speaks.
"""
from __future__ import annotations

import asyncio
import logging
import time

from packages.core.event_bus import EventBus
from packages.core.types import EventType, NovaEvent, Priority

log = logging.getLogger("nova.silence_detector")


class SilenceDetector:
    """
    Detects silence in the chat stream and publishes SILENCE_DETECTED events.

    The silence timer resets when:
      - A new CHAT_MESSAGE arrives
      - Nova just spoke (SAFE_OUTPUT event)

    This prevents double-triggering: Nova won't speak over herself.
    """

    def __init__(
        self,
        bus: EventBus,
        silence_sec: float = 45.0,
        check_interval: float = 5.0,
    ) -> None:
        self._bus = bus
        self._silence_sec = silence_sec
        self._check_interval = check_interval
        self._last_chat_time = time.monotonic()
        self._last_speech_time = time.monotonic()
        self._running = False
        self._task: asyncio.Task | None = None
        self._silence_published = False   # prevent repeat publish

    async def start(self) -> None:
        self._running = True
        self._bus.subscribe(
            EventType.CHAT_MESSAGE, self._on_chat, sub_id="silence_chat"
        )
        self._bus.subscribe(
            EventType.GIFT_RECEIVED, self._on_activity, sub_id="silence_gift"
        )
        self._bus.subscribe(
            EventType.SUPER_CHAT, self._on_activity, sub_id="silence_superchat"
        )
        self._bus.subscribe(
            EventType.SAFE_OUTPUT, self._on_nova_speech, sub_id="silence_speech"
        )
        self._task = asyncio.create_task(
            self._check_loop(), name="nova.silence_detector"
        )
        log.info("Silence detector started (threshold=%.0fs)", self._silence_sec)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()

    # ── Event handlers ─────────────────────────────────────────────────────

    async def _on_chat(self, event: NovaEvent) -> None:
        self._last_chat_time = time.monotonic()
        self._silence_published = False

    async def _on_activity(self, event: NovaEvent) -> None:
        """Gifts and super chats also count as activity."""
        self._last_chat_time = time.monotonic()
        self._silence_published = False

    async def _on_nova_speech(self, event: NovaEvent) -> None:
        """Reset silence timer after Nova speaks to avoid immediate re-trigger."""
        self._last_speech_time = time.monotonic()
        self._last_chat_time = time.monotonic()
        self._silence_published = False

    # ── Check loop ─────────────────────────────────────────────────────────

    async def _check_loop(self) -> None:
        while self._running:
            await asyncio.sleep(self._check_interval)
            now = time.monotonic()
            silence = now - self._last_chat_time

            if silence >= self._silence_sec and not self._silence_published:
                log.info("Silence detected (%.0fs)", silence)
                await self._bus.publish(NovaEvent(
                    type=EventType.SILENCE_DETECTED,
                    payload={"silence_sec": silence},
                    priority=Priority.LOW,
                    source="silence_detector",
                ))
                self._silence_published = True
