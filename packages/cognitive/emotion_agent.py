"""
NOVA Emotion Agent
==================
Maintains a continuous 2D emotion state (valence × arousal).
Drives voice prosody, avatar expressions, and response tone.

The state machine uses exponential smoothing so emotions
decay naturally rather than snapping between states.

Emotion transitions are driven by:
  - Platform events (gift → excited, mean comment → sad)
  - Semantic clusters from perception layer
  - Time-based decay back toward baseline
  - Inter-agent signals from personality agent
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from packages.core.event_bus import EventBus
from packages.core.types import (
    EmotionLabel,
    EmotionState,
    EventType,
    NovaEvent,
    Priority,
)

log = logging.getLogger("nova.emotion_agent")


# ─── Emotion transition rules ─────────────────────────────────────────────────

@dataclass
class EmotionTrigger:
    """Maps an event condition to a target emotion delta."""
    valence_delta: float    # how much to shift valence (-1..+1)
    arousal_delta: float    # how much to shift arousal
    intensity:     float    # strength of this trigger
    label_hint:    EmotionLabel | None = None


_EVENT_TRIGGERS: dict[EventType, EmotionTrigger] = {
    EventType.GIFT_RECEIVED:   EmotionTrigger( 0.3,  0.4, 0.8, EmotionLabel.EXCITED),
    EventType.SUPER_CHAT:      EmotionTrigger( 0.4,  0.5, 0.9, EmotionLabel.EXCITED),
    EventType.FOLLOW:          EmotionTrigger( 0.2,  0.2, 0.5, EmotionLabel.HAPPY),
    EventType.VIEWER_JOIN:     EmotionTrigger( 0.1,  0.1, 0.3, EmotionLabel.HAPPY),
    EventType.SILENCE_DETECTED:EmotionTrigger(-0.1, -0.2, 0.4, EmotionLabel.CALM),
}

_SENTIMENT_MAP: dict[str, EmotionTrigger] = {
    "positive":  EmotionTrigger( 0.25,  0.15, 0.5),
    "negative":  EmotionTrigger(-0.3,   0.2,  0.6, EmotionLabel.SAD),
    "excited":   EmotionTrigger( 0.2,   0.4,  0.6, EmotionLabel.EXCITED),
    "aggressive":EmotionTrigger(-0.2,   0.5,  0.7, EmotionLabel.ANXIOUS),
    "curious":   EmotionTrigger( 0.1,   0.1,  0.4, EmotionLabel.CURIOUS),
}


def _classify(valence: float, arousal: float) -> EmotionLabel:
    """Map 2D coordinates to the nearest named emotion."""
    if valence > 0.3 and arousal > 0.5:
        return EmotionLabel.EXCITED
    if valence > 0.3 and arousal <= 0.5:
        return EmotionLabel.HAPPY
    if valence < -0.3 and arousal > 0.5:
        return EmotionLabel.ANXIOUS
    if valence < -0.3 and arousal <= 0.5:
        return EmotionLabel.SAD
    if arousal > 0.6:
        return EmotionLabel.SURPRISED
    if valence > 0.1:
        return EmotionLabel.CURIOUS
    if arousal < 0.2:
        return EmotionLabel.CALM
    return EmotionLabel.NEUTRAL


class EmotionAgent:
    """
    Manages the streamer's emotional state.

    Publishes EventType.EMOTION_STATE on every significant change (>0.05 delta).
    Other agents read this to modulate their behavior.
    """

    # Baseline personality (can be tuned per character)
    BASELINE_VALENCE = 0.3     # slightly positive default
    BASELINE_AROUSAL = 0.35
    DECAY_RATE       = 0.08    # per second, exponential pull toward baseline
    SMOOTHING        = 0.3     # EMA alpha for incoming triggers (0=ignore, 1=instant)
    PUBLISH_THRESHOLD = 0.04   # minimum delta to publish state update

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._valence  = self.BASELINE_VALENCE
        self._arousal  = self.BASELINE_AROUSAL
        self._intensity = 0.3
        self._last_update = time.monotonic()
        self._decay_task: asyncio.Task | None = None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def start(self) -> None:
        # Subscribe to platform and perception events
        for et in _EVENT_TRIGGERS:
            self._bus.subscribe(et, self._on_event, sub_id=f"emotion_{et.name}")

        self._bus.subscribe(
            EventType.SEMANTIC_CLUSTER, self._on_cluster, sub_id="emotion_cluster"
        )
        self._bus.subscribe(
            EventType.PERSONALITY_HINT, self._on_personality, sub_id="emotion_personality"
        )

        self._decay_task = asyncio.create_task(
            self._decay_loop(), name="nova.emotion_decay"
        )
        log.info("Emotion agent started (baseline v=%.2f a=%.2f)",
                 self.BASELINE_VALENCE, self.BASELINE_AROUSAL)

    async def stop(self) -> None:
        if self._decay_task:
            self._decay_task.cancel()

    # ── Event handlers ───────────────────────────────────────────────────────

    async def _on_event(self, event: NovaEvent) -> None:
        trigger = _EVENT_TRIGGERS.get(event.type)
        if trigger:
            self._apply(trigger, triggered_by=event.type.value)

    async def _on_cluster(self, event: NovaEvent) -> None:
        """Respond to semantic cluster sentiment signals."""
        sentiment = event.payload.get("dominant_sentiment", "")
        trigger = _SENTIMENT_MAP.get(sentiment)
        if trigger:
            # Scale by cluster confidence
            confidence = float(event.payload.get("confidence", 0.5))
            scaled = EmotionTrigger(
                trigger.valence_delta * confidence,
                trigger.arousal_delta * confidence,
                trigger.intensity    * confidence,
                trigger.label_hint,
            )
            self._apply(scaled, triggered_by=f"cluster:{sentiment}")

    async def _on_personality(self, event: NovaEvent) -> None:
        """Personality agent can nudge emotion toward character-appropriate state."""
        target_valence = float(event.payload.get("target_valence", self._valence))
        target_arousal = float(event.payload.get("target_arousal", self._arousal))
        nudge_strength = float(event.payload.get("strength", 0.1))

        trigger = EmotionTrigger(
            (target_valence - self._valence) * nudge_strength,
            (target_arousal - self._arousal) * nudge_strength,
            nudge_strength,
        )
        self._apply(trigger, triggered_by="personality_correction")

    # ── State mutation ───────────────────────────────────────────────────────

    def _apply(self, trigger: EmotionTrigger, triggered_by: str = "") -> None:
        prev_v, prev_a = self._valence, self._arousal

        # EMA blend
        self._valence  = self._valence  + self.SMOOTHING * trigger.valence_delta
        self._arousal  = self._arousal  + self.SMOOTHING * trigger.arousal_delta
        self._intensity = self._intensity + self.SMOOTHING * (trigger.intensity - self._intensity)

        # Clamp to valid range
        self._valence  = max(-1.0, min(1.0, self._valence))
        self._arousal  = max(0.0,  min(1.0, self._arousal))
        self._intensity = max(0.0, min(1.0, self._intensity))

        delta = abs(self._valence - prev_v) + abs(self._arousal - prev_a)
        if delta >= self.PUBLISH_THRESHOLD:
            self._bus.publish_sync(self._build_event(triggered_by))
            log.debug(
                "Emotion: v=%.2f a=%.2f (%s) ← %s",
                self._valence, self._arousal, self.current_label.value, triggered_by
            )

    async def _decay_loop(self) -> None:
        """Continuously decay toward baseline (runs every 0.5s)."""
        while True:
            await asyncio.sleep(0.5)
            now = time.monotonic()
            dt  = now - self._last_update
            self._last_update = now

            # Exponential decay toward baseline
            factor = (1 - self.DECAY_RATE) ** dt
            self._valence  = self._valence  * factor + self.BASELINE_VALENCE  * (1 - factor)
            self._arousal  = self._arousal  * factor + self.BASELINE_AROUSAL  * (1 - factor)
            self._intensity = max(0.3, self._intensity * factor)

    # ── State access ─────────────────────────────────────────────────────────

    @property
    def current_state(self) -> EmotionState:
        return EmotionState(
            valence=self._valence,
            arousal=self._arousal,
            label=self.current_label,
            intensity=self._intensity,
        )

    @property
    def current_label(self) -> EmotionLabel:
        return _classify(self._valence, self._arousal)

    def _build_event(self, triggered_by: str) -> NovaEvent:
        state = self.current_state
        return NovaEvent(
            type=EventType.EMOTION_STATE,
            payload={
                "valence":      state.valence,
                "arousal":      state.arousal,
                "label":        state.label.value,
                "intensity":    state.intensity,
                "prosody":      state.to_prosody_params(),
                "triggered_by": triggered_by,
            },
            priority=Priority.HIGH,
            source="emotion_agent",
        )
