"""
NOVA Proactive Intelligence
============================
Enhanced proactive behavior system.

Goes beyond simple silence detection:
  - Topic suggestion based on knowledge base and trends
  - Interactive prompts (polls, questions, mini-games)
  - Mood-appropriate proactive speech
  - Viewer engagement analysis to optimize timing
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from packages.core.event_bus import EventBus
from packages.core.types import ActionType, EventType, NovaEvent, Priority

log = logging.getLogger("nova.proactive")


# ─── Proactive strategies ────────────────────────────────────────────────────

class ProactiveStrategy(str, Enum):
    TOPIC_SUGGESTION  = "topic_suggestion"   # Suggest a topic based on KB
    AUDIENCE_QUESTION = "audience_question"   # Ask the audience something
    MINI_GAME         = "mini_game"           # Propose a mini-game
    STORY_TELLING     = "story_telling"       # Tell a short story / anecdote
    MOOD_SHIFT        = "mood_shift"          # Shift stream mood
    KNOWLEDGE_SHARE   = "knowledge_share"     # Share interesting knowledge
    INTERACTION_PROMPT = "interaction_prompt"  # Prompt viewers to interact


@dataclass
class ProactiveAction:
    """A generated proactive action."""
    strategy: ProactiveStrategy
    prompt_text: str          # text to feed LLM as context
    priority: Priority = Priority.LOW
    metadata: dict[str, Any] = field(default_factory=dict)


# ─── Topic pool ──────────────────────────────────────────────────────────────

_DEFAULT_TOPICS = [
    "最近有什么好玩的游戏推荐吗？",
    "大家今天心情怎么样？",
    "有没有人想听我唱歌？",
    "最近看了一部超有意思的动漫！",
    "来玩个猜谜游戏怎么样？",
    "大家平时下班后都做什么？",
    "有没有人也在学编程？",
    "最近天气变化好大，大家注意保暖哦～",
    "你们觉得AI未来会怎么样？",
    "今天有人遇到什么有趣的事吗？",
]

_MINI_GAME_PROMPTS = [
    "我们来玩猜数字游戏吧！我想一个1到100的数字，你们来猜！",
    "成语接龙开始了！我先来：一马当先——",
    "真心话大冒险时间！弹幕里打1选真心话，打2选大冒险！",
    "来玩看图猜词！我描述一个东西，你们猜是什么～",
]


# ─── Proactive Intelligence ──────────────────────────────────────────────────

class ProactiveIntelligence:
    """
    Generates intelligent proactive actions based on:
      - Current stream state (viewer count, chat rate, emotion)
      - Knowledge base content
      - Time since last interaction
      - Viewer engagement patterns
    """

    def __init__(
        self,
        bus: EventBus,
        knowledge_base: Any = None,
        llm_client: Any = None,
    ) -> None:
        self._bus = bus
        self._kb = knowledge_base
        self._llm = llm_client
        self._last_proactive_time = time.monotonic()
        self._proactive_count = 0
        self._topic_index = 0

    def select_strategy(
        self,
        emotion: Any,  # EmotionState
        viewer_count: int = 0,
        chat_rate: float = 0.0,
        silence_sec: float = 0.0,
    ) -> ProactiveAction:
        """
        Select the best proactive strategy based on current context.
        """
        # High arousal + high viewers → interactive prompt
        if emotion.arousal > 0.6 and viewer_count > 50:
            return ProactiveAction(
                strategy=ProactiveStrategy.INTERACTION_PROMPT,
                prompt_text="直播间气氛不错！请主动和观众互动，可以抛一个问题或者做个小游戏。30字以内。",
                priority=Priority.NORMAL,
            )

        # Low engagement → knowledge share or topic suggestion
        if chat_rate < 1.0 or silence_sec > 60:
            if self._kb:
                return ProactiveAction(
                    strategy=ProactiveStrategy.KNOWLEDGE_SHARE,
                    prompt_text="直播间比较安静，分享一个有趣的知识点来活跃气氛。30字以内。",
                    priority=Priority.LOW,
                    metadata={"use_knowledge": True},
                )
            return ProactiveAction(
                strategy=ProactiveStrategy.TOPIC_SUGGESTION,
                prompt_text=self._get_next_topic(),
                priority=Priority.LOW,
            )

        # Medium engagement → audience question
        if viewer_count > 20:
            return ProactiveAction(
                strategy=ProactiveStrategy.AUDIENCE_QUESTION,
                prompt_text="向观众抛一个有趣的问题来增加互动。30字以内。",
                priority=Priority.LOW,
            )

        # Small audience → intimate conversation
        if viewer_count <= 20 and viewer_count > 0:
            return ProactiveAction(
                strategy=ProactiveStrategy.TOPIC_SUGGESTION,
                prompt_text="和眼前的观众聊聊天，像朋友一样。可以说说今天的感受。30字以内。",
                priority=Priority.LOW,
            )

        # Default: topic suggestion
        return ProactiveAction(
            strategy=ProactiveStrategy.TOPIC_SUGGESTION,
            prompt_text=self._get_next_topic(),
            priority=Priority.LOW,
        )

    def should_be_proactive(
        self,
        silence_sec: float,
        min_silence: float = 30.0,
        max_interval: float = 120.0,
    ) -> bool:
        """Determine if proactive action is needed."""
        time_since_last = time.monotonic() - self._last_proactive_time
        return silence_sec >= min_silence and time_since_last >= max_interval

    def _get_next_topic(self) -> str:
        """Get the next topic from the rotation."""
        if self._topic_index < len(_DEFAULT_TOPICS):
            topic = _DEFAULT_TOPICS[self._topic_index]
            self._topic_index += 1
        else:
            topic = random.choice(_DEFAULT_TOPICS)
        return f"主动发起话题：{topic} 30字以内。"

    def get_mini_game_prompt(self) -> str:
        """Get a random mini-game prompt."""
        return random.choice(_MINI_GAME_PROMPTS)

    def mark_proactive(self) -> None:
        """Mark that a proactive action was just taken."""
        self._last_proactive_time = time.monotonic()
        self._proactive_count += 1

    @property
    def proactive_count(self) -> int:
        return self._proactive_count
