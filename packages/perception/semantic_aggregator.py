"""
NOVA Semantic Aggregator
========================
The most critical component in the perception layer.

Collects chat messages in a 300ms sliding window, clusters similar
content using lightweight TF-IDF + cosine similarity, extracts
representative questions, computes sentiment distribution, and
publishes SEMANTIC_CLUSTER events.

Why 300ms? Practice-proven sweet spot:
  - Long enough to batch similar messages
  - Short enough to feel responsive
  - Prevents LLM overload in high-traffic streams (100+ msg/min)
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Any

from packages.core.event_bus import EventBus
from packages.core.types import EventType, NovaEvent, Priority

log = logging.getLogger("nova.semantic_aggregator")


# ─── Simple TF-IDF for clustering ─────────────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    """Very simple Chinese-aware tokenizer: split on whitespace + single chars."""
    import re
    # Split on non-alphanumeric/CJK boundaries
    tokens = re.findall(r'[\u4e00-\u9fff]|[a-zA-Z0-9]+', text.lower())
    return tokens


def _tfidf_vector(tokens: list[str], idf: dict[str, float]) -> dict[str, float]:
    """Compute TF-IDF vector as a sparse dict."""
    if not tokens:
        return {}
    tf = Counter(tokens)
    total = len(tokens)
    return {t: (count / total) * idf.get(t, 1.0) for t, count in tf.items()}


def _cosine_sim(a: dict[str, float], b: dict[str, float]) -> float:
    """Cosine similarity between two sparse dicts."""
    common = set(a.keys()) & set(b.keys())
    if not common:
        return 0.0
    dot = sum(a[k] * b[k] for k in common)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ─── Sentiment ────────────────────────────────────────────────────────────────

_POSITIVE_WORDS = frozenset({
    "好", "棒", "厉害", "赞", "牛", "可爱", "漂亮", "哈哈", "喜欢", "加油",
    "666", "秀", "牛批", "真棒", "不错", "支持", "爱", "好看", "有趣",
})
_NEGATIVE_WORDS = frozenset({
    "差", "烂", "垃圾", "无聊", "恶心", "退钱", "骗", "假", "失望", "菜",
    "垃圾", "废物", "菜鸡", "垃圾操作",
})


def _classify_sentiment(text: str) -> str:
    """Simple keyword-based sentiment. Returns 'positive'/'negative'/'neutral'."""
    tokens = set(_tokenize(text))
    pos = len(tokens & _POSITIVE_WORDS)
    neg = len(tokens & _NEGATIVE_WORDS)
    if pos > neg + 1:
        return "positive"
    if neg > pos + 1:
        return "negative"
    return "neutral"


# ─── Cluster data ─────────────────────────────────────────────────────────────

@dataclass
class _WindowMessage:
    text: str
    viewer_name: str
    viewer_id: str
    timestamp: float
    tokens: list[str] = field(default_factory=list)


@dataclass
class _Cluster:
    messages: list[_WindowMessage] = field(default_factory=list)
    representative: str = ""
    sentiment: str = "neutral"
    confidence: float = 0.0


# ─── Semantic Aggregator ─────────────────────────────────────────────────────

class SemanticAggregator:
    """
    Batches chat messages in a sliding window, clusters them,
    and publishes SEMANTIC_CLUSTER events.

    Config:
      window_ms:     aggregation window in ms (default 300)
      similarity_threshold: min cosine sim to merge into a cluster (default 0.5)
      max_clusters:  max clusters per window (default 5)
    """

    def __init__(
        self,
        bus: EventBus,
        window_ms: int = 300,
        similarity_threshold: float = 0.5,
        max_clusters: int = 5,
    ) -> None:
        self._bus = bus
        self._window_ms = window_ms
        self._sim_threshold = similarity_threshold
        self._max_clusters = max_clusters

        self._buffer: list[_WindowMessage] = []
        self._idf: dict[str, float] = {}          # running IDF estimate
        self._doc_count = 0
        self._running = False
        self._flush_task: asyncio.Task | None = None
        self._last_flush = time.monotonic()

    async def start(self) -> None:
        self._running = True
        self._bus.subscribe(
            EventType.CHAT_MESSAGE, self._on_chat, sub_id="semantic_chat"
        )
        self._flush_task = asyncio.create_task(
            self._flush_loop(), name="nova.semantic_aggregator.flush"
        )
        log.info(
            "Semantic aggregator started (window=%dms, threshold=%.2f)",
            self._window_ms, self._sim_threshold
        )

    async def stop(self) -> None:
        self._running = False
        if self._flush_task:
            self._flush_task.cancel()
        # Flush remaining
        if self._buffer:
            await self._flush()

    # ── Event handler ──────────────────────────────────────────────────────

    async def _on_chat(self, event: NovaEvent) -> None:
        text = event.payload.get("text", "").strip()
        if not text:
            return

        viewer = event.payload.get("viewer", {})
        msg = _WindowMessage(
            text=text,
            viewer_name=viewer.get("username", "anonymous"),
            viewer_id=viewer.get("viewer_id", "unknown"),
            timestamp=time.monotonic(),
            tokens=_tokenize(text),
        )
        self._buffer.append(msg)

        # Update running IDF
        self._doc_count += 1
        for t in set(msg.tokens):
            self._idf[t] = self._idf.get(t, 0) + 1

    # ── Flush loop ─────────────────────────────────────────────────────────

    async def _flush_loop(self) -> None:
        while self._running:
            await asyncio.sleep(self._window_ms / 1000.0)
            if self._buffer:
                await self._flush()

    async def _flush(self) -> None:
        """Cluster buffered messages and publish SEMANTIC_CLUSTER events."""
        messages = self._buffer[:]
        self._buffer.clear()
        if not messages:
            return

        # Compute IDF
        idf = {
            t: math.log(self._doc_count / (1 + df))
            for t, df in self._idf.items()
        }

        # Vectorize
        vectors = []
        for msg in messages:
            vec = _tfidf_vector(msg.tokens, idf)
            vectors.append(vec)

        # Simple greedy clustering
        clusters: list[_Cluster] = []
        assigned = [False] * len(messages)

        for i in range(len(messages)):
            if assigned[i]:
                continue
            cluster = _Cluster(messages=[messages[i]])
            assigned[i] = True

            for j in range(i + 1, len(messages)):
                if assigned[j]:
                    continue
                sim = _cosine_sim(vectors[i], vectors[j])
                if sim >= self._sim_threshold:
                    cluster.messages.append(messages[j])
                    assigned[j] = True

            # Pick representative (longest message, tends to be most informative)
            cluster.representative = max(
                cluster.messages, key=lambda m: len(m.text)
            ).text

            # Compute cluster-level sentiment
            sentiments = [_classify_sentiment(m.text) for m in cluster.messages]
            sentiment_counts = Counter(sentiments)
            cluster.sentiment = sentiment_counts.most_common(1)[0][0]
            cluster.confidence = len(cluster.messages) / len(messages)

            clusters.append(cluster)

            if len(clusters) >= self._max_clusters:
                break

        # Publish cluster events (sorted by cluster size, largest first)
        clusters.sort(key=lambda c: len(c.messages), reverse=True)

        for cluster in clusters:
            viewer_names = list({m.viewer_name for m in cluster.messages})
            await self._bus.publish(NovaEvent(
                type=EventType.SEMANTIC_CLUSTER,
                payload={
                    "representative":  cluster.representative,
                    "message_count":   len(cluster.messages),
                    "dominant_sentiment": cluster.sentiment,
                    "confidence":      cluster.confidence,
                    "viewer_names":    viewer_names[:5],
                    "all_texts":       [m.text for m in cluster.messages[:10]],
                },
                priority=Priority.NORMAL,
                source="semantic_aggregator",
            ))

        log.debug(
            "Aggregated %d messages → %d clusters",
            len(messages), len(clusters)
        )
