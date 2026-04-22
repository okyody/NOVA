"""
NOVA Memory Consolidation
=========================
LLM-driven memory consolidation and summarization.

Converts raw working memory entries into:
  - Summarized episodic memories
  - Viewer relationship insights
  - Topic extraction and trend detection
  - Memory deduplication and merging
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from packages.core.types import MemoryEntry

log = logging.getLogger("nova.memory_consolidation")


# ─── Consolidation result ────────────────────────────────────────────────────

@dataclass
class ConsolidationResult:
    """Result of a consolidation pass."""
    summaries: list[str] = field(default_factory=list)
    insights: list[str] = field(default_factory=list)
    deduplicated: int = 0
    total_processed: int = 0


# ─── Memory Consolidator ─────────────────────────────────────────────────────

class MemoryConsolidator:
    """
    LLM-driven memory consolidation.

    Periodically:
      1. Takes a batch of working memory entries
      2. Uses LLM to summarize, extract insights, and deduplicate
      3. Stores consolidated results in episodic memory

    This is the "sleep" phase of memory — like human memory consolidation
    during sleep, it organizes and integrates raw experiences.
    """

    def __init__(
        self,
        llm_client: Any = None,
        batch_size: int = 20,
        max_consolidation_interval: float = 300.0,  # 5 minutes
    ) -> None:
        self._llm = llm_client
        self._batch_size = batch_size
        self._interval = max_consolidation_interval
        self._last_consolidation = time.monotonic()
        self._consolidation_count = 0

    async def consolidate(
        self,
        entries: list[dict[str, Any]],
    ) -> ConsolidationResult:
        """
        Consolidate a batch of working memory entries.

        If LLM is available, uses it for intelligent summarization.
        Otherwise, falls back to rule-based consolidation.
        """
        if not entries:
            return ConsolidationResult()

        self._consolidation_count += 1

        if self._llm is not None:
            return await self._llm_consolidate(entries)
        else:
            return self._rule_consolidate(entries)

    async def _llm_consolidate(
        self,
        entries: list[dict[str, Any]],
    ) -> ConsolidationResult:
        """LLM-powered consolidation."""
        # Format entries for LLM
        entries_text = self._format_entries(entries)

        prompt = f"""你是一个记忆整理系统。以下是最近的直播互动记录，请：

1. 生成2-3条精炼的记忆摘要（每条不超过30字）
2. 提取1-2条观众关系洞察（如"观众X喜欢讨论游戏"）
3. 标记重复或相似的内容

互动记录：
{entries_text}

请用JSON格式回复：
{{"summaries": ["摘要1", "摘要2"], "insights": ["洞察1"], "dedup_count": 0}}"""

        try:
            import json
            response = await self._llm.complete(
                messages=[
                    {"role": "system", "content": "你是记忆整理AI，只输出JSON格式。"},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=200,
                temperature=0.3,
            )
            data = json.loads(response.strip())
            result = ConsolidationResult(
                summaries=data.get("summaries", []),
                insights=data.get("insights", []),
                deduplicated=data.get("dedup_count", 0),
                total_processed=len(entries),
            )
            log.info(
                "LLM consolidation #%d: %d entries → %d summaries, %d insights",
                self._consolidation_count, len(entries),
                len(result.summaries), len(result.insights),
            )
            return result

        except Exception as e:
            log.warning("LLM consolidation failed, falling back to rules: %s", e)
            return self._rule_consolidate(entries)

    def _rule_consolidate(
        self,
        entries: list[dict[str, Any]],
    ) -> ConsolidationResult:
        """Rule-based fallback consolidation."""
        summaries = []
        insights = []
        seen_texts: set[str] = set()
        dedup_count = 0

        for entry in entries:
            text = entry.get("text", "")
            if not text:
                continue

            # Deduplication
            text_key = text[:50].lower().strip()
            if text_key in seen_texts:
                dedup_count += 1
                continue
            seen_texts.add(text_key)

            # Simple summarization: take first N characters
            if len(summaries) < 5:
                summary = text[:30] + ("…" if len(text) > 30 else "")
                viewer = entry.get("viewer", "")
                if viewer:
                    summary = f"[{viewer}] {summary}"
                summaries.append(summary)

            # Extract viewer insights
            event_type = entry.get("event_type", "")
            viewer = entry.get("viewer", "")
            if viewer and event_type in ("platform.gift_received", "platform.super_chat"):
                insights.append(f"{viewer}是活跃支持者（有送礼/SC记录）")

        return ConsolidationResult(
            summaries=summaries,
            insights=insights[:3],
            deduplicated=dedup_count,
            total_processed=len(entries),
        )

    def _format_entries(self, entries: list[dict[str, Any]]) -> str:
        """Format working memory entries for LLM input."""
        lines = []
        for entry in entries[-20:]:  # Last 20 entries
            role = entry.get("role", "?")
            text = entry.get("text", "")
            viewer = entry.get("viewer", "")
            event = entry.get("event_type", "")
            ts = entry.get("ts", "")

            if viewer:
                lines.append(f"[{ts}][{event}][{viewer}]: {text}")
            else:
                lines.append(f"[{ts}][{event}][{role}]: {text}")
        return "\n".join(lines)

    def should_consolidate(
        self,
        entry_count: int,
        min_entries: int = 15,
    ) -> bool:
        """Check if consolidation should run."""
        time_ok = time.monotonic() - self._last_consolidation >= self._interval
        count_ok = entry_count >= min_entries
        return time_ok or count_ok

    def mark_consolidated(self) -> None:
        """Mark that consolidation was just performed."""
        self._last_consolidation = time.monotonic()

    @property
    def consolidation_count(self) -> int:
        return self._consolidation_count


# ─── Memory-to-Knowledge bridge ──────────────────────────────────────────────

class MemoryKnowledgeBridge:
    """
    Bridges episodic memory insights into the knowledge base.
    This allows the RAG system to search over consolidated memories.
    """

    def __init__(
        self,
        knowledge_base: Any = None,
        embedder: Any = None,
    ) -> None:
        self._kb = knowledge_base
        self._embedder = embedder

    async def sync_consolidation_result(
        self,
        result: ConsolidationResult,
        source: str = "consolidation",
    ) -> int:
        """Push consolidation summaries into the knowledge base."""
        if self._kb is None:
            return 0

        total = 0
        for i, summary in enumerate(result.summaries):
            source_id = f"{source}_{int(time.time())}_{i}"
            count = await self._kb.ingest(
                text=summary,
                source_id=source_id,
                metadata={"type": "consolidation", "source": source},
            )
            total += count

        for i, insight in enumerate(result.insights):
            source_id = f"{source}_insight_{int(time.time())}_{i}"
            count = await self._kb.ingest(
                text=insight,
                source_id=source_id,
                metadata={"type": "viewer_insight", "source": source},
            )
            total += count

        if total > 0:
            log.info("Synced %d items from consolidation to knowledge base", total)
        return total
