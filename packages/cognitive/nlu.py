"""
NOVA Intent Classifier (NLU)
=============================
Classifies user intent from chat messages to improve response quality.

Intent categories:
  - QUESTION    — asking for information
  - CHAT        — casual conversation
  - COMMAND     — direct instruction (e.g., "唱首歌")
  - GREETING    — hello/goodbye
  - EMOTION     — expressing feelings (positive or negative)
  - TOPIC       — introducing a new topic
  - REQUEST     — asking for an action (e.g., "play a game")
  - UNKNOWN     — cannot classify
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

log = logging.getLogger("nova.nlu")


# ─── Intent types ────────────────────────────────────────────────────────────

class IntentType(str, Enum):
    QUESTION  = "question"
    CHAT      = "chat"
    COMMAND   = "command"
    GREETING  = "greeting"
    EMOTION   = "emotion"
    TOPIC     = "topic"
    REQUEST   = "request"
    UNKNOWN   = "unknown"


@dataclass
class IntentResult:
    """Result of intent classification."""
    intent: IntentType
    confidence: float       # 0..1
    sub_intent: str = ""    # more specific label (e.g., "greeting.hello")
    entities: dict[str, str] | None = None  # extracted entities


# ─── Rule-based classifier ───────────────────────────────────────────────────

# Pattern-based rules: (compiled_regex, intent, sub_intent, confidence)
_RULES: list[tuple[re.Pattern, IntentType, str, float]] = [
    # Greetings
    (re.compile(r'^(你好|嗨|hi|hello|hey|早上好|晚上好|早安|晚安|大家好|你们好)', re.I),
     IntentType.GREETING, "hello", 0.9),
    (re.compile(r'(再见|拜拜|bye|晚安|走了|下了|溜了)', re.I),
     IntentType.GREETING, "goodbye", 0.85),

    # Questions
    (re.compile(r'(什么是|怎么|如何|为什么|哪里|哪个|多少|什么时候|谁能|会不会|是不是|吗[？?]?$)'),
     IntentType.QUESTION, "", 0.8),
    (re.compile(r'[?？]{1,3}\s*$'),
     IntentType.QUESTION, "", 0.6),

    # Commands
    (re.compile(r'^(唱|跳|画|玩|讲|说|演|来|做)', re.I),
     IntentType.COMMAND, "", 0.75),
    (re.compile(r'(来一首|唱首歌|讲个笑话|玩个游戏|做个动作)'),
     IntentType.COMMAND, "", 0.85),

    # Emotion expressions
    (re.compile(r'(哈哈|嘻嘻|太好了|好棒|好厉害|不错|棒|赞|666|nb|牛逼|牛)'),
     IntentType.EMOTION, "positive", 0.7),
    (re.compile(r'(无聊|讨厌|烦|差|垃圾|难看|不好|不行|失望)'),
     IntentType.EMOTION, "negative", 0.7),
    (re.compile(r'(爱|喜欢|可爱|漂亮|帅|美|好看|心动)'),
     IntentType.EMOTION, "affection", 0.7),

    # Topic introduction
    (re.compile(r'(听说|据说|你们知道吗|有没有人|大家觉得|聊聊|说说|讨论)'),
     IntentType.TOPIC, "", 0.7),

    # Requests
    (re.compile(r'(能.*吗|可以.*吗|请|帮我|能不能|可不可以|希望)'),
     IntentType.REQUEST, "", 0.65),
]


class IntentClassifier:
    """
    Classifies user message intent.

    Uses a two-stage approach:
      1. Fast rule-based matching (regex patterns)
      2. Optional LLM-based fallback for ambiguous cases

    In production, the LLM stage is used only for low-confidence rule results.
    """

    def __init__(self, llm_client: Any = None, llm_threshold: float = 0.5) -> None:
        """
        Args:
            llm_client: Optional LLMClient for ambiguous classification.
            llm_threshold: If rule confidence < this, fall back to LLM.
        """
        self._llm = llm_client
        self._llm_threshold = llm_threshold

    def classify(self, text: str) -> IntentResult:
        """
        Classify the intent of a text message.
        Returns IntentResult with intent type and confidence.
        """
        if not text or not text.strip():
            return IntentResult(intent=IntentType.UNKNOWN, confidence=0.0)

        # Stage 1: Rule-based matching
        best_match = self._rule_classify(text)

        # Stage 2: LLM fallback for low-confidence results
        if best_match.confidence < self._llm_threshold and self._llm is not None:
            llm_result = self._llm_classify_sync(text)
            if llm_result.confidence > best_match.confidence:
                return llm_result

        # Extract entities
        best_match.entities = self._extract_entities(text, best_match.intent)
        return best_match

    async def classify_async(self, text: str) -> IntentResult:
        """Async version that can use LLM for classification."""
        if not text or not text.strip():
            return IntentResult(intent=IntentType.UNKNOWN, confidence=0.0)

        best_match = self._rule_classify(text)

        if best_match.confidence < self._llm_threshold and self._llm is not None:
            llm_result = await self._llm_classify(text)
            if llm_result.confidence > best_match.confidence:
                return llm_result

        best_match.entities = self._extract_entities(text, best_match.intent)
        return best_match

    def _rule_classify(self, text: str) -> IntentResult:
        """Rule-based intent classification."""
        best = IntentResult(intent=IntentType.CHAT, confidence=0.3)

        for pattern, intent, sub_intent, confidence in _RULES:
            if pattern.search(text):
                if confidence > best.confidence:
                    best = IntentResult(
                        intent=intent,
                        confidence=confidence,
                        sub_intent=sub_intent,
                    )

        # Default: short messages → chat, longer → chat with moderate confidence
        if best.intent == IntentType.CHAT:
            if len(text) <= 5:
                best.confidence = 0.5
            else:
                best.confidence = 0.4

        return best

    async def _llm_classify(self, text: str) -> IntentResult:
        """LLM-based intent classification for ambiguous cases."""
        prompt = f"""Classify the intent of this Chinese chat message from a livestream.
Message: "{text}"

Respond with ONLY a JSON object:
{{"intent": "question|chat|command|greeting|emotion|topic|request|unknown", "confidence": 0.0-1.0, "sub_intent": "optional detail"}}

Valid intents: question, chat, command, greeting, emotion, topic, request, unknown"""

        try:
            response = await self._llm.complete(
                messages=[
                    {"role": "system", "content": "You are an intent classifier for Chinese livestream chat. Respond only with JSON."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=50,
                temperature=0.1,
            )
            import json
            data = json.loads(response.strip())
            return IntentResult(
                intent=IntentType(data.get("intent", "unknown")),
                confidence=float(data.get("confidence", 0.5)),
                sub_intent=data.get("sub_intent", ""),
            )
        except Exception as e:
            log.debug("LLM intent classification failed: %s", e)
            return IntentResult(intent=IntentType.UNKNOWN, confidence=0.0)

    def _llm_classify_sync(self, text: str) -> IntentResult:
        """Sync fallback (just returns unknown — real impl would use asyncio.run)."""
        return IntentResult(intent=IntentType.UNKNOWN, confidence=0.0)

    def _extract_entities(self, text: str, intent: IntentType) -> dict[str, str]:
        """Extract named entities based on intent context."""
        entities: dict[str, str] = {}

        # Extract @mentions
        mentions = re.findall(r'@(\w+)', text)
        if mentions:
            entities["mentions"] = ",".join(mentions)

        # Extract topic keywords for TOPIC intent
        if intent == IntentType.TOPIC:
            # Simple heuristic: look for "关于X" or "X怎么样" patterns
            topic_match = re.search(r'(关于|聊聊|说说|讨论)(.+?)(吧|呢|怎么样|如何|$)', text)
            if topic_match:
                entities["topic"] = topic_match.group(2).strip()

        # Extract question focus for QUESTION intent
        if intent == IntentType.QUESTION:
            q_match = re.search(r'(什么|怎么|如何|为什么|哪里)(.+?)[？?]', text)
            if q_match:
                entities["question_focus"] = q_match.group(0).rstrip("？?")

        return entities


# ─── Batch classifier ────────────────────────────────────────────────────────

class BatchIntentClassifier:
    """Classify intents for multiple messages efficiently."""

    def __init__(self, classifier: IntentClassifier) -> None:
        self._classifier = classifier

    def classify_batch(self, texts: list[str]) -> list[IntentResult]:
        """Classify a batch of messages."""
        return [self._classifier.classify(t) for t in texts]

    async def classify_batch_async(self, texts: list[str]) -> list[IntentResult]:
        """Async classify a batch of messages."""
        results = []
        for text in texts:
            result = await self._classifier.classify_async(text)
            results.append(result)
        return results

    def intent_distribution(self, results: list[IntentResult]) -> dict[str, int]:
        """Get intent distribution from classification results."""
        dist: dict[str, int] = {}
        for r in results:
            key = r.intent.value
            dist[key] = dist.get(key, 0) + 1
        return dict(sorted(dist.items(), key=lambda x: -x[1]))
