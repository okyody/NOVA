"""
NOVA Context Sensor
====================
Monitors live stream context: chat rate, gift frequency,
viewer trends, and overall "heat level".

Publishes CONTEXT_UPDATE events that the Orchestrator uses
to modulate response behavior (more active in hot streams,
more relaxed in cold ones).

Heat levels:
  COLD   — <5 msg/min, few viewers, quiet
  NORMAL — 5-30 msg/min, steady viewership
  HOT    — 30-80 msg/min, high engagement
  VIRAL  — >80 msg/min, gifts flying, explosive growth
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from packages.core.event_bus import EventBus
from packages.core.types import EventType, NovaEvent, Priority

log = logging.getLogger("nova.context_sensor")


# ─── Heat levels ────────────────────────────────────────────────────────────────

class HeatLevel(str, Enum):
    COLD   = "cold"
    NORMAL = "normal"
    HOT    = "hot"
    VIRAL  = "viral"


@dataclass
class StreamContext:
    heat_level:     HeatLevel = HeatLevel.NORMAL
    chat_rate:      float = 0.0      # messages per minute
    gift_rate:      float = 0.0      # gifts per minute
    viewer_count:   int   = 0
    viewer_delta:   int   = 0        # net change in last 60s
    sentiment_ratio: float = 0.5     # 0=all negative, 1=all positive
    last_updated:   float = 0.0


# ─── Context Sensor ────────────────────────────────────────────────────────────

class ContextSensor:
    """
    Aggregates live stream metrics and publishes CONTEXT_UPDATE events.

    Config:
      update_interval_s:  how often to recalculate and publish (default 10s)
      history_window_s:   rolling window for rate calculations (default 60s)
    """

    def __init__(
        self,
        bus: EventBus,
        update_interval_s: int = 10,
        history_window_s: int = 60,
    ) -> None:
        self._bus = bus
        self._update_interval = update_interval_s
        self._window_s = history_window_s

        self._chat_timestamps: deque[float] = deque()
        self._gift_timestamps: deque[float] = deque()
        self._viewer_counts: deque[tuple[float, int]] = deque(maxlen=60)
        self._sentiments: deque[tuple[float, str]] = deque(maxlen=200)

        self._context = StreamContext(last_updated=time.monotonic())
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._running = True
        self._bus.subscribe(
            EventType.CHAT_MESSAGE, self._on_chat, sub_id="ctx_chat"
        )
        self._bus.subscribe(
            EventType.GIFT_RECEIVED, self._on_gift, sub_id="ctx_gift"
        )
        self._bus.subscribe(
            EventType.SUPER_CHAT, self._on_gift, sub_id="ctx_superchat"
        )
        self._bus.subscribe(
            EventType.LIVE_STATS, self._on_stats, sub_id="ctx_stats"
        )
        self._bus.subscribe(
            EventType.SEMANTIC_CLUSTER, self._on_cluster, sub_id="ctx_cluster"
        )
        self._bus.subscribe(
            EventType.VIEWER_JOIN, self._on_join, sub_id="ctx_join"
        )
        self._task = asyncio.create_task(
            self._update_loop(), name="nova.context_sensor.update"
        )
        log.info("Context sensor started (interval=%ds, window=%ds)",
                 self._update_interval, self._window_s)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()

    @property
    def current_context(self) -> StreamContext:
        return self._context

    # ── Event handlers ──────────────────────────────────────────────────────

    async def _on_chat(self, event: NovaEvent) -> None:
        self._chat_timestamps.append(time.monotonic())

    async def _on_gift(self, event: NovaEvent) -> None:
        self._gift_timestamps.append(time.monotonic())

    async def _on_stats(self, event: NovaEvent) -> None:
        count = event.payload.get("online_count", 0)
        self._viewer_counts.append((time.monotonic(), count))

    async def _on_cluster(self, event: NovaEvent) -> None:
        sentiment = event.payload.get("dominant_sentiment", "neutral")
        self._sentiments.append((time.monotonic(), sentiment))

    async def _on_join(self, event: NovaEvent) -> None:
        # Approximate viewer tracking from join events
        pass

    # ── Periodic update ─────────────────────────────────────────────────────

    async def _update_loop(self) -> None:
        while self._running:
            await asyncio.sleep(self._update_interval)
            await self._recalculate()

    async def _recalculate(self) -> None:
        now = time.monotonic()
        cutoff = now - self._window_s

        # Trim old data
        while self._chat_timestamps and self._chat_timestamps[0] < cutoff:
            self._chat_timestamps.popleft()
        while self._gift_timestamps and self._gift_timestamps[0] < cutoff:
            self._gift_timestamps.popleft()

        # Compute rates
        chat_rate = len(self._chat_timestamps) * (60.0 / self._window_s)
        gift_rate = len(self._gift_timestamps) * (60.0 / self._window_s)

        # Viewer count (latest)
        viewer_count = 0
        if self._viewer_counts:
            viewer_count = self._viewer_counts[-1][1]

        # Viewer delta
        viewer_delta = 0
        if len(self._viewer_counts) >= 2:
            viewer_delta = self._viewer_counts[-1][1] - self._viewer_counts[0][1]

        # Sentiment ratio
        recent_sentiments = [s for t, s in self._sentiments if t >= cutoff]
        if recent_sentiments:
            pos = sum(1 for s in recent_sentiments if s == "positive")
            neg = sum(1 for s in recent_sentiments if s == "negative")
            total = pos + neg
            sentiment_ratio = pos / total if total > 0 else 0.5
        else:
            sentiment_ratio = 0.5

        # Determine heat level
        heat = self._classify_heat(chat_rate, gift_rate, viewer_count)

        # Update context
        self._context = StreamContext(
            heat_level=heat,
            chat_rate=chat_rate,
            gift_rate=gift_rate,
            viewer_count=viewer_count,
            viewer_delta=viewer_delta,
            sentiment_ratio=sentiment_ratio,
            last_updated=now,
        )

        # Publish
        await self._bus.publish(NovaEvent(
            type=EventType.CONTEXT_UPDATE,
            payload={
                "heat_level":      heat.value,
                "chat_rate":       round(chat_rate, 1),
                "gift_rate":       round(gift_rate, 1),
                "viewer_count":    viewer_count,
                "viewer_delta":    viewer_delta,
                "sentiment_ratio": round(sentiment_ratio, 2),
            },
            priority=Priority.LOW,
            source="context_sensor",
        ))

    @staticmethod
    def _classify_heat(
        chat_rate: float,
        gift_rate: float,
        viewer_count: int,
    ) -> HeatLevel:
        """Simple rule-based heat classification."""
        # Weighted scoring
        score = 0.0
        score += min(chat_rate / 80.0, 1.0) * 40   # chat contributes up to 40 pts
        score += min(gift_rate / 20.0, 1.0) * 30    # gifts up to 30 pts
        score += min(viewer_count / 500.0, 1.0) * 30 # viewers up to 30 pts

        if score >= 75:
            return HeatLevel.VIRAL
        if score >= 45:
            return HeatLevel.HOT
        if score >= 15:
            return HeatLevel.NORMAL
        return HeatLevel.COLD
