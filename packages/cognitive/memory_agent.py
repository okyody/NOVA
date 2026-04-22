"""
NOVA Memory Agent
=================
Three-tier memory system:

  1. WorkingMemory   — last N interactions (in-process deque, instant access)
  2. EpisodicMemory  — vector store for semantic search (Qdrant)
  3. ViewerGraph     — relationship map per viewer (dict-based, upgradable to Neo4j)

The agent listens to platform events and cognitive outputs,
automatically consolidates short-term memory into long-term storage
every N events or every T minutes.

External agents call recall() to get relevant context before generation.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from packages.core.event_bus import EventBus
from packages.core.types import (
    EventType,
    MemoryEntry,
    NovaEvent,
    Priority,
    ViewerProfile,
)

log = logging.getLogger("nova.memory_agent")


# ─── Working Memory ───────────────────────────────────────────────────────────

class WorkingMemory:
    """Fixed-size sliding window of recent events. O(1) ops."""

    def __init__(self, maxlen: int = 40) -> None:
        self._buffer: deque[dict[str, Any]] = deque(maxlen=maxlen)

    def push(self, entry: dict[str, Any]) -> None:
        entry.setdefault("ts", datetime.utcnow().isoformat())
        self._buffer.appendleft(entry)

    def recent(self, n: int = 10) -> list[dict[str, Any]]:
        return list(self._buffer)[:n]

    def to_context_string(self, n: int = 8) -> str:
        """Format recent memory as a compact context string for the LLM."""
        items = self.recent(n)
        if not items:
            return "(no recent context)"
        lines = []
        for item in reversed(items):
            role = item.get("role", "?")
            text = item.get("text", "")
            viewer = item.get("viewer", "")
            if viewer:
                lines.append(f"[{viewer}]: {text}")
            else:
                lines.append(f"[{role}]: {text}")
        return "\n".join(lines)

    def clear(self) -> None:
        self._buffer.clear()


# ─── Episodic Memory (vector store stub, ready for Qdrant) ───────────────────

class EpisodicMemory:
    """
    Persistent semantic memory backed by a vector store.

    In production: replace _store with a Qdrant client.
    The interface stays identical — swap the backend, not the API.

    qdrant_client = QdrantClient(url="http://localhost:6333")
    """

    def __init__(self) -> None:
        # Stub: in-memory list. Production: Qdrant collection
        self._store: list[MemoryEntry] = []

    async def store(self, entry: MemoryEntry) -> None:
        """Persist a memory with its embedding."""
        # Production:
        # await qdrant_client.upsert(
        #     collection_name="nova_episodic",
        #     points=[PointStruct(id=entry.memory_id, vector=entry.embedding, payload=...)]
        # )
        self._store.append(entry)
        log.debug("Episodic stored: %s (importance=%.2f)", entry.memory_id, entry.importance)

    async def search(
        self, query_embedding: list[float], top_k: int = 5, min_importance: float = 0.0
    ) -> list[MemoryEntry]:
        """
        Semantic search. Returns top_k most relevant memories.
        Stub: returns recent high-importance entries.
        Production: Qdrant ANN search.
        """
        now = datetime.utcnow()
        candidates = [
            e for e in self._store
            if e.effective_importance(now) >= min_importance
        ]
        candidates.sort(key=lambda e: e.effective_importance(now), reverse=True)
        return candidates[:top_k]

    async def consolidate(self, entries: list[dict[str, Any]]) -> None:
        """Batch-convert working memory items into episodic memories."""
        for item in entries:
            text = item.get("text", "")
            if not text:
                continue
            entry = MemoryEntry(
                content=text,
                importance=_estimate_importance(item),
                metadata={
                    "viewer": item.get("viewer", ""),
                    "event":  item.get("event_type", ""),
                    "ts":     item.get("ts", ""),
                },
            )
            await self.store(entry)


def _estimate_importance(item: dict[str, Any]) -> float:
    """Heuristic importance score for auto-consolidation."""
    base = 0.3
    # Super chats and gifts are highly memorable
    if item.get("event_type") in ("platform.super_chat", "platform.gift_received"):
        base += 0.4
    if item.get("is_member"):
        base += 0.1
    # Long messages have more content
    text_len = len(item.get("text", ""))
    base += min(0.2, text_len / 500)
    return min(1.0, base)


# ─── Viewer Graph ─────────────────────────────────────────────────────────────

@dataclass
class ViewerNode:
    profile:       ViewerProfile
    interaction_count: int   = 0
    last_topics:   list[str] = field(default_factory=list)
    sentiment_avg: float     = 0.0    # rolling average sentiment
    is_vip:        bool      = False

    def update_from_event(self, event_type: str, text: str = "") -> None:
        self.interaction_count += 1
        if text:
            self.last_topics = ([text[:50]] + self.last_topics)[:5]


class ViewerGraph:
    """
    In-memory viewer relationship graph.
    Production: swap for Neo4j via neo4j-driver.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, ViewerNode] = {}    # viewer_id → node

    def upsert(self, profile: ViewerProfile) -> ViewerNode:
        if profile.viewer_id not in self._nodes:
            self._nodes[profile.viewer_id] = ViewerNode(profile=profile)
        return self._nodes[profile.viewer_id]

    def get(self, viewer_id: str) -> ViewerNode | None:
        return self._nodes.get(viewer_id)

    def top_viewers(self, n: int = 5) -> list[ViewerNode]:
        return sorted(
            self._nodes.values(),
            key=lambda v: v.profile.gift_total + v.interaction_count * 0.1,
            reverse=True,
        )[:n]

    def summary(self) -> str:
        """One-liner for LLM context injection."""
        top = self.top_viewers(3)
        if not top:
            return "No notable viewers yet."
        names = ", ".join(v.profile.username for v in top)
        return f"Top viewers: {names}. Total unique viewers: {len(self._nodes)}."


# ─── Memory Agent ─────────────────────────────────────────────────────────────

class MemoryAgent:
    """
    Orchestrates the three memory tiers and exposes recall() to other agents.
    Automatically consolidates working memory → episodic every 30 events or 5 min.
    """

    CONSOLIDATE_EVERY_N = 30
    CONSOLIDATE_EVERY_S = 300     # 5 minutes

    def __init__(self, bus: EventBus) -> None:
        self._bus          = bus
        self.working       = WorkingMemory(maxlen=50)
        self.episodic      = EpisodicMemory()
        self.viewer_graph  = ViewerGraph()
        self._event_count  = 0
        self._last_consolidate = time.monotonic()
        self._consolidate_task: asyncio.Task | None = None

    async def start(self) -> None:
        for et in (
            EventType.CHAT_MESSAGE,
            EventType.GIFT_RECEIVED,
            EventType.SUPER_CHAT,
            EventType.FOLLOW,
            EventType.MEMORY_STORE,
        ):
            self._bus.subscribe(et, self._on_event, sub_id=f"memory_{et.name}")

        self._consolidate_task = asyncio.create_task(
            self._consolidate_loop(), name="nova.memory_consolidate"
        )
        log.info("Memory agent started")

    async def stop(self) -> None:
        if self._consolidate_task:
            self._consolidate_task.cancel()

    # ── Event ingestion ───────────────────────────────────────────────────────

    async def _on_event(self, event: NovaEvent) -> None:
        entry = self._event_to_entry(event)
        self.working.push(entry)

        # Update viewer graph
        viewer_data = event.payload.get("viewer")
        if viewer_data:
            profile = _viewer_from_payload(viewer_data)
            node = self.viewer_graph.upsert(profile)
            node.update_from_event(
                event.type.value,
                event.payload.get("text", ""),
            )

        self._event_count += 1
        if self._event_count % self.CONSOLIDATE_EVERY_N == 0:
            asyncio.create_task(self._consolidate_now())

    def _event_to_entry(self, event: NovaEvent) -> dict[str, Any]:
        p = event.payload
        return {
            "event_type": event.type.value,
            "text":       p.get("text") or p.get("response_text", ""),
            "viewer":     p.get("viewer", {}).get("username", ""),
            "is_member":  p.get("viewer", {}).get("is_member", False),
            "role":       "viewer" if "viewer" in p else "nova",
            "ts":         event.timestamp.isoformat(),
        }

    # ── Consolidation ─────────────────────────────────────────────────────────

    async def _consolidate_loop(self) -> None:
        while True:
            await asyncio.sleep(60)
            if time.monotonic() - self._last_consolidate >= self.CONSOLIDATE_EVERY_S:
                await self._consolidate_now()

    async def _consolidate_now(self) -> None:
        items = self.working.recent(20)
        await self.episodic.consolidate(items)
        self._last_consolidate = time.monotonic()
        log.debug("Consolidated %d working memory items → episodic", len(items))

    # ── Recall API ────────────────────────────────────────────────────────────

    async def recall(
        self,
        query: str,
        viewer_id: str | None = None,
        top_k: int = 5,
    ) -> dict[str, Any]:
        """
        Build a context dict for the orchestrator / LLM.
        Combines recent working memory + episodic search + viewer info.
        """
        recent_context = self.working.to_context_string(n=8)

        # Episodic search (stub: no embedding for now)
        episodic_results = await self.episodic.search(
            query_embedding=[], top_k=top_k, min_importance=0.35
        )
        episodic_texts = [e.content for e in episodic_results]

        viewer_node = self.viewer_graph.get(viewer_id) if viewer_id else None
        viewer_summary = self.viewer_graph.summary()

        return {
            "recent":         recent_context,
            "episodic_hints": episodic_texts,
            "viewer_node":    viewer_node,
            "viewer_summary": viewer_summary,
            "total_viewers":  len(self.viewer_graph._nodes),
        }

    async def publish_recall(self, query: str, viewer_id: str | None = None) -> None:
        """Publish recall result as MEMORY_RECALL event for orchestrator consumption."""
        ctx = await self.recall(query, viewer_id)
        await self._bus.publish(NovaEvent(
            type=EventType.MEMORY_RECALL,
            payload=ctx,
            priority=Priority.HIGH,
            source="memory_agent",
        ))


def _viewer_from_payload(data: dict[str, Any]) -> ViewerProfile:
    from packages.core.types import Platform
    return ViewerProfile(
        viewer_id=data.get("viewer_id", "unknown"),
        platform=Platform(data.get("platform", "local")),
        username=data.get("username", "anonymous"),
        is_member=data.get("is_member", False),
        gift_total=float(data.get("gift_total", 0.0)),
    )
