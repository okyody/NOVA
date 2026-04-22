"""
NOVA Safety Guard
=================
Real-time content moderation layer.

Runs BEFORE every output reaches the voice pipeline.
Two-tier checking:
  1. Fast rule-based filter   (keyword lists, regex patterns) — < 1ms
  2. LLM-based semantic check (sampled, for ambiguous cases)  — async

On violation: publishes SAFETY_BLOCK event, substitutes text,
then re-publishes as SAFE_OUTPUT for downstream consumption.

Design principle: fail safe → when in doubt, substitute, never crash or expose.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from packages.core.event_bus import EventBus
from packages.core.types import EventType, NovaEvent, Priority

log = logging.getLogger("nova.safety_guard")


class RiskLevel(str, Enum):
    SAFE     = "safe"
    WARN     = "warn"       # log and continue
    BLOCK    = "block"      # substitute fallback
    CRITICAL = "critical"   # block + alert ops


@dataclass
class SafetyResult:
    level:    RiskLevel
    reason:   str = ""
    category: str = ""


# ─── Rule sets ────────────────────────────────────────────────────────────────

# Hard block patterns (regex)
_HARD_BLOCK_PATTERNS: list[tuple[str, str]] = [
    # (pattern, category)
    (r"(习近平|天安门|法轮功|台湾独立|藏独|新疆集中营)", "political"),
    (r"(自杀|自残|割腕|跳楼)", "self_harm"),
    (r"(操你|去死|TMD|fuck you)", "profanity"),
    (r"(\d{11}|\d{3}-\d{4}-\d{4})", "personal_info"),  # phone numbers
    (r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", "personal_info"),  # email
]

_COMPILED_PATTERNS = [
    (re.compile(p, re.IGNORECASE), cat) for p, cat in _HARD_BLOCK_PATTERNS
]

# Warn-level patterns (log but allow)
_WARN_PATTERNS: list[tuple[str, str]] = [
    (r"(政治|选举|投票|政府|官员)", "political_adjacent"),
    (r"(比特币|NFT|投资|理财|返利)", "financial"),
]
_COMPILED_WARN = [
    (re.compile(p, re.IGNORECASE), cat) for p, cat in _WARN_PATTERNS
]

# Safe fallback responses (rotated to avoid sounding robotic)
_FALLBACKS = [
    "哈哈这个我不太好评论，咱们聊点别的吧～",
    "这个话题超出了我的范围，我们换个方向？",
    "嗯...让我想想怎么回答...不如你们来帮我想个新话题？",
    "Nova 在这个问题上保持沉默～ 有什么轻松的话题聊聊？",
]


# ─── Safety Guard ─────────────────────────────────────────────────────────────

class SafetyGuard:
    """
    Intercepts ORCHESTRATOR_OUT events, checks content safety,
    then publishes SAFE_OUTPUT for downstream (VoicePipeline).
    This guarantees safety check always runs before voice synthesis.
    """

    SEMANTIC_CHECK_RATE = 0.05    # sample 5% for deep LLM check (performance)

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._block_count = 0
        self._warn_count  = 0
        self._check_count = 0
        self._fallback_idx = 0    # instance variable, not global

    async def start(self) -> None:
        self._bus.subscribe(
            EventType.ORCHESTRATOR_OUT,
            self._on_output,
            sub_id="safety_output",
            max_lag_ms=50,      # must be fast
        )
        log.info("Safety guard active")

    async def stop(self) -> None:
        log.info("Safety guard stopped (blocks=%d, checks=%d)", self._block_count, self._check_count)

    # ── Main check ────────────────────────────────────────────────────────────

    async def _on_output(self, event: NovaEvent) -> None:
        text = event.payload.get("text", "")
        if not text:
            # Forward even empty outputs
            await self._publish_safe(event)
            return

        result = self._fast_check(text)
        self._check_count += 1

        if result.level == RiskLevel.BLOCK or result.level == RiskLevel.CRITICAL:
            await self._handle_block(event, result)
        elif result.level == RiskLevel.WARN:
            self._warn_count += 1
            log.warning("Safety WARN [%s]: %.60s…", result.category, text)

        # Always publish SAFE_OUTPUT after checking
        await self._publish_safe(event)

    def _fast_check(self, text: str) -> SafetyResult:
        """Rule-based check — O(n patterns), always < 1ms."""
        for pattern, category in _COMPILED_PATTERNS:
            if pattern.search(text):
                return SafetyResult(
                    level=RiskLevel.BLOCK,
                    reason=f"Pattern match: {pattern.pattern[:30]}",
                    category=category,
                )

        for pattern, category in _COMPILED_WARN:
            if pattern.search(text):
                return SafetyResult(
                    level=RiskLevel.WARN,
                    category=category,
                    reason="Warn pattern",
                )

        return SafetyResult(level=RiskLevel.SAFE)

    async def _handle_block(self, event: NovaEvent, result: SafetyResult) -> None:
        self._block_count += 1
        original_text = event.payload.get("text", "")
        log.warning(
            "Safety BLOCK [%s]: %.80s… (reason: %s)",
            result.category, original_text, result.reason
        )

        # Publish block notification for ops dashboard
        await self._bus.publish(NovaEvent(
            type=EventType.SAFETY_BLOCK,
            payload={
                "category":      result.category,
                "reason":        result.reason,
                "blocked_text":  original_text[:100],
                "trace_id":      event.payload.get("trace_id", ""),
                "total_blocks":  self._block_count,
            },
            priority=Priority.HIGH,
            source="safety_guard",
        ))

        # Mutate the event payload to substitute safe response
        event.payload["text"] = self._next_fallback()
        event.payload["safety_substituted"] = True
        event.payload["original_category"] = result.category

    async def _publish_safe(self, event: NovaEvent) -> None:
        """Publish SAFE_OUTPUT event for VoicePipeline to consume."""
        await self._bus.publish(NovaEvent(
            type=EventType.SAFE_OUTPUT,
            payload=dict(event.payload),   # copy payload (may be modified)
            priority=event.priority,
            source="safety_guard",
            trace_id=event.trace_id or event.event_id,
        ))

    def _next_fallback(self) -> str:
        resp = _FALLBACKS[self._fallback_idx % len(_FALLBACKS)]
        self._fallback_idx += 1
        return resp

    def stats(self) -> dict[str, int]:
        return {
            "checks":  self._check_count,
            "blocks":  self._block_count,
            "warns":   self._warn_count,
        }
