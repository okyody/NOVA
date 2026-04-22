"""
NOVA RAG Prompt Builder
=======================
Constructs LLM prompts with retrieved knowledge context.

Injects relevant document chunks into the system/user message
so the LLM can answer questions grounded in the knowledge base.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from packages.knowledge.knowledge_base import KnowledgeBase, SearchResult

log = logging.getLogger("nova.rag_prompt")


# ─── Prompt templates ────────────────────────────────────────────────────────

_RAG_SYSTEM_TEMPLATE = """你是虚拟主播 {name}。

## 人格设定
{persona}

## 说话风格
{speech_style}

## 核心价值观
{values}

## 知识库参考
以下是从知识库中检索到的相关内容，请基于这些信息回答问题。如果知识与你的角色设定冲突，以角色设定为准。

{knowledge_block}

## 注意事项
- 始终保持角色一致性，不要透露自己是 AI 模型
- 回复简洁，直播场景中每次回应控制在 50 字以内
- 如果知识库中没有相关信息，按你的角色自然回应
- 不要直接引用"知识库说"，要自然地融入回答"""

_RAG_USER_TEMPLATE = """[当前状态]
情绪: {emotion_label} (效价={valence:.2f}, 唤醒={arousal:.2f})
观众概况: {viewer_summary}
[最近对话]
{recent_context}
{gift_info}
[{viewer_name}的消息]: {query}

请以你的角色自然回应。50字以内。"""

_PROACTIVE_RAG_TEMPLATE = """[当前状态]
情绪: {emotion_label} (效价={valence:.2f}, 唤醒={arousal:.2f})
观众概况: {viewer_summary}
[最近对话]
{recent_context}
[相关知识]
{knowledge_block}

直播间已经安静了一段时间，请以你的角色主动发起一段自然的对话，
可以结合上面的相关知识，话题可以是今天的游戏、最近的热点、或者向观众抛出一个有趣的问题。50字以内。"""


# ─── RAG Prompt Builder ──────────────────────────────────────────────────────

@dataclass
class RAGContext:
    """Result of building a RAG-augmented prompt."""
    messages: list[dict[str, str]]
    retrieved: list[SearchResult] = field(default_factory=list)
    knowledge_text: str = ""


class RAGPromptBuilder:
    """
    Builds LLM prompts augmented with retrieved knowledge.

    Two modes:
      1. query mode — user asks something, retrieve relevant knowledge
      2. proactive mode — generate proactive speech, optionally use knowledge
    """

    def __init__(
        self,
        knowledge_base: KnowledgeBase,
        top_k: int = 3,
        score_threshold: float = 0.25,
        max_context_chars: int = 1500,
    ) -> None:
        self._kb = knowledge_base
        self._top_k = top_k
        self._threshold = score_threshold
        self._max_chars = max_context_chars

    async def build_messages(
        self,
        query: str,
        character: Any,  # CharacterCard
        memory_ctx: dict[str, Any],
        emotion: Any,    # EmotionState
        action_type: Any = None,  # ActionType
        trigger: Any = None,  # NovaEvent
    ) -> RAGContext:
        """
        Build complete message list for LLM call with RAG augmentation.
        """
        # Retrieve relevant knowledge
        retrieved = await self._kb.retrieve(
            query=query,
            top_k=self._top_k,
            score_threshold=self._threshold,
        )

        # Format knowledge block
        knowledge_text = self._format_knowledge(retrieved)

        # Build system message
        system_msg = _RAG_SYSTEM_TEMPLATE.format(
            name=character.name,
            persona=character.persona,
            speech_style=character.speech_style,
            values="、".join(character.core_values),
            knowledge_block=knowledge_text,
        )

        # Build user message
        if action_type and action_type.value == "initiate":
            user_msg = _PROACTIVE_RAG_TEMPLATE.format(
                emotion_label=emotion.label.value,
                valence=emotion.valence,
                arousal=emotion.arousal,
                viewer_summary=memory_ctx.get("viewer_summary", "暂无数据"),
                recent_context=memory_ctx.get("recent", "(无)"),
                knowledge_block=knowledge_text,
            )
        else:
            gift_info = ""
            viewer_name = "观众"
            if trigger:
                viewer_name = trigger.payload.get("viewer", {}).get("username", "观众")
                if trigger.type.value in ("platform.gift_received", "platform.super_chat"):
                    amount = trigger.payload.get("amount", 0)
                    gift_name = trigger.payload.get("gift_name", "礼物")
                    gift_info = f"\n[{viewer_name} 送出了 {gift_name}（价值 {amount} 元）]"

            user_msg = _RAG_USER_TEMPLATE.format(
                emotion_label=emotion.label.value,
                valence=emotion.valence,
                arousal=emotion.arousal,
                viewer_summary=memory_ctx.get("viewer_summary", "暂无数据"),
                recent_context=memory_ctx.get("recent", "(无)"),
                gift_info=gift_info,
                viewer_name=viewer_name,
                query=query,
            )

        return RAGContext(
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            retrieved=retrieved,
            knowledge_text=knowledge_text,
        )

    def _format_knowledge(self, results: list[SearchResult]) -> str:
        """Format search results into a readable knowledge block."""
        if not results:
            return "（无相关知识）"

        lines = []
        total_chars = 0
        for i, result in enumerate(results, 1):
            source = result.doc.metadata.get("source_id", "未知来源")
            score = result.score
            text = result.doc.text

            # Truncate individual entries if too long
            if total_chars + len(text) > self._max_chars:
                remaining = self._max_chars - total_chars
                if remaining > 50:
                    text = text[:remaining] + "…"
                    lines.append(f"[{i}] (来源: {source}, 相关度: {score:.2f})\n{text}")
                break
            else:
                lines.append(f"[{i}] (来源: {source}, 相关度: {score:.2f})\n{text}")
                total_chars += len(text)

        return "\n\n".join(lines)

    async def build_simple_rag_context(
        self,
        query: str,
        top_k: int | None = None,
    ) -> str:
        """
        Simple utility: just get formatted RAG context for a query.
        Useful for injecting into existing prompt builders.
        """
        top_k = top_k or self._top_k
        results = await self._kb.retrieve(
            query=query,
            top_k=top_k,
            score_threshold=self._threshold,
        )
        return self._format_knowledge(results)
