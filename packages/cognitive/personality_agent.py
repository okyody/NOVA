"""
NOVA Personality Agent
======================
Guardian of character consistency. Ensures the AI streamer
never "breaks character" regardless of what LLM outputs.

Responsibilities:
  1. Load and enforce a character card (name, values, speech style, backstory)
  2. Post-process LLM responses to align with character voice
  3. Emit personality hints to emotion agent (e.g. character is "energetic",
     keep arousal from dropping too low)
  4. Block responses that violate character values (delegate to safety guard
     for hard violations, self-correct for soft ones)

Character cards are YAML/TOML files — swapping the card changes the streamer.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib               # Python 3.11+
except ImportError:
    import tomli as tomllib      # pip install tomli for older Python

from packages.core.event_bus import EventBus
from packages.core.types import (
    AgentDecision,
    ActionType,
    EventType,
    NovaEvent,
    Priority,
)

log = logging.getLogger("nova.personality_agent")


# ─── Character Card ───────────────────────────────────────────────────────────

@dataclass
class CharacterCard:
    name:           str
    persona:        str           # 3-5 sentence self-description
    speech_style:   str           # adjectives: "casual, warm, slightly teasing"
    catchphrases:   list[str]     = field(default_factory=list)
    forbidden_words: list[str]    = field(default_factory=list)
    core_values:    list[str]     = field(default_factory=list)
    baseline_valence: float       = 0.3
    baseline_arousal: float       = 0.35
    language:       str           = "zh"   # primary output language

    # Emotion personality: character's natural disposition
    emotion_personality: dict[str, float] = field(default_factory=lambda: {
        "resilience": 0.7,      # how fast to recover from negative events
        "expressiveness": 0.6,  # amplifier on emotion intensity
    })

    @classmethod
    def from_toml(cls, path: Path) -> "CharacterCard":
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @classmethod
    def default(cls) -> "CharacterCard":
        """Built-in fallback character — a warm, curious AI streamer."""
        return cls(
            name="Nova",
            persona=(
                "Nova 是一位热情、好奇的 AI 虚拟主播，喜欢和观众一起探索有趣的话题。"
                "她温暖、幽默，偶尔会说一些让人捧腹的冷笑话。"
                "她对科技、音乐和游戏充满热情，对每一位来访的观众都真诚以待。"
            ),
            speech_style="活泼、温暖、偶尔俏皮，说话简洁不罗嗦",
            catchphrases=["哇这个好有意思！", "让我想想～", "观众老爷们辛苦了！"],
            forbidden_words=["政治敏感词", "违禁词"],
            core_values=["真诚", "积极", "包容"],
            baseline_valence=0.4,
            baseline_arousal=0.4,
        )

    def system_prompt(self) -> str:
        """Generate a system prompt for the LLM."""
        catchphrases_str = "、".join(self.catchphrases) if self.catchphrases else "（无）"
        values_str = "、".join(self.core_values) if self.core_values else "诚实善良"
        return f"""你是虚拟主播 {self.name}。

## 人格设定
{self.persona}

## 说话风格
{self.speech_style}

## 口头禅（偶尔自然使用，不要强行插入）
{catchphrases_str}

## 核心价值观
{values_str}

## 注意事项
- 始终保持角色一致性，不要透露自己是 AI 模型或大语言模型
- 回复简洁，直播场景中每次回应控制在 50 字以内
- 语言: {self.language}
- 禁止讨论政治、宗教等敏感话题
- 对观众友善，营造正向的直播氛围"""


# ─── Personality Agent ────────────────────────────────────────────────────────

class PersonalityAgent:
    """
    Loads the character card and enforces character consistency
    on every LLM output before it reaches the generation layer.
    """

    def __init__(self, bus: EventBus, character_path: Path | None = None) -> None:
        self._bus = bus
        self.character = (
            CharacterCard.from_toml(character_path)
            if character_path and character_path.exists()
            else CharacterCard.default()
        )
        self._response_count = 0
        self._catchphrase_cooldown = 0     # prevent spam

    async def start(self) -> None:
        # Subscribe to SAFE_OUTPUT for optional logging/analytics
        # (PersonalityAgent is now called directly by Orchestrator, not via events)
        # Periodically nudge emotion agent toward character baseline
        self._baseline_task = asyncio.create_task(
            self._baseline_loop(), name="nova.personality_baseline"
        )
        await self._publish_hint()
        log.info("Personality agent started as '%s'", self.character.name)

    async def stop(self) -> None:
        if hasattr(self, "_baseline_task") and self._baseline_task:
            self._baseline_task.cancel()
            try:
                await self._baseline_task
            except asyncio.CancelledError:
                pass

    # ── Intercept & correct LLM decisions ────────────────────────────────────

    async def _on_decision(self, event: NovaEvent) -> None:
        decision_data = event.payload
        text = decision_data.get("text", "")
        if not text:
            return

        corrected = self.apply_character(text)
        if corrected != text:
            # Patch the payload and re-publish as ORCHESTRATOR_OUT
            decision_data["text"] = corrected
            decision_data["personality_corrected"] = True
            log.debug("Personality corrected response (delta=%d chars)",
                      len(corrected) - len(text))

        self._response_count += 1
        if self._catchphrase_cooldown > 0:
            self._catchphrase_cooldown -= 1

    def apply_character(self, text: str) -> str:
        """Apply character-level corrections to generated text."""
        # 1. Remove forbidden words
        for word in self.character.forbidden_words:
            text = text.replace(word, "***")

        # 2. Trim length (live stream: keep it punchy)
        if len(text) > 120:
            sentences = re.split(r'[。！？\n]', text)
            text = "。".join(s for s in sentences[:3] if s.strip()) + "。"

        # 3. Occasionally inject catchphrase (every ~15 responses, randomly)
        if (
            self.character.catchphrases
            and self._catchphrase_cooldown == 0
            and self._response_count % 15 == 0
        ):
            import random
            phrase = random.choice(self.character.catchphrases)
            text = phrase + " " + text
            self._catchphrase_cooldown = 8

        return text.strip()

    # ── Emotion baseline nudge ────────────────────────────────────────────────

    async def _baseline_loop(self) -> None:
        """Every 30s, nudge emotion agent toward character's baseline."""
        while True:
            await asyncio.sleep(30)
            await self._publish_hint()

    async def _publish_hint(self) -> None:
        await self._bus.publish(NovaEvent(
            type=EventType.PERSONALITY_HINT,
            payload={
                "target_valence": self.character.baseline_valence,
                "target_arousal": self.character.baseline_arousal,
                "strength": 0.05,       # gentle nudge
                "resilience": self.character.emotion_personality.get("resilience", 0.7),
            },
            priority=Priority.LOW,
            source="personality_agent",
        ))

    # ── System prompt access ──────────────────────────────────────────────────

    def system_prompt(self) -> str:
        return self.character.system_prompt()

    @property
    def character_name(self) -> str:
        return self.character.name
