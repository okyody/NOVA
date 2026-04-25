"""
NOVA Semantic Aggregator
========================

Collects chat messages in a short sliding window, groups semantically similar
messages with embeddings, and publishes `SEMANTIC_CLUSTER` events.

The previous implementation used TF-IDF over single-character Chinese tokens.
That was fast but it clustered lexical overlap, not meaning. This version uses
embeddings with centroid-based clustering so short chat variants such as
"好棒" / "太厉害了" can be grouped together.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from packages.core.event_bus import EventBus
from packages.core.types import EventType, NovaEvent, Priority

log = logging.getLogger("nova.semantic_aggregator")


def _tokenize(text: str) -> list[str]:
    """Tokenize text for lightweight sentiment heuristics."""
    import re

    return re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z0-9]+", text.lower())


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _average_vectors(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        return []
    dim = len(vectors[0])
    centroid = [0.0] * dim
    for vector in vectors:
        for idx, value in enumerate(vector):
            centroid[idx] += value
    scale = 1.0 / len(vectors)
    return [value * scale for value in centroid]


def _hashed_embedding(text: str, dim: int = 64) -> list[float]:
    """
    Deterministic fallback embedding.

    It is not as semantically strong as a real embedder, but it keeps the
    aggregator functional in tests or offline mode when an embedding backend
    is not injected.
    """
    tokens = _tokenize(text) or [text.lower()]
    vector = [0.0] * dim
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        slot = int.from_bytes(digest[:2], "big") % dim
        sign = 1.0 if digest[2] % 2 == 0 else -1.0
        weight = 1.0 + (digest[3] / 255.0)
        vector[slot] += sign * weight
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return vector
    return [value / norm for value in vector]


_POSITIVE_WORDS = frozenset({
    "好",
    "喜欢",
    "厉害",
    "真棒",
    "牛",
    "支持",
    "爱",
    "可爱",
    "漂亮",
    "哈哈",
    "666",
    "nb",
})
_NEGATIVE_WORDS = frozenset({
    "差",
    "烂",
    "垃圾",
    "无聊",
    "恶心",
    "退钱",
    "骗",
    "失望",
    "菜",
    "难看",
})


def _classify_sentiment(text: str) -> str:
    lowered = text.lower()
    pos = sum(1 for token in _POSITIVE_WORDS if token in lowered)
    neg = sum(1 for token in _NEGATIVE_WORDS if token in lowered)
    if pos > neg:
        return "positive"
    if neg > pos:
        return "negative"
    return "neutral"


@dataclass
class _WindowMessage:
    text: str
    viewer_name: str
    viewer_id: str
    timestamp: float
    embedding: list[float] = field(default_factory=list)


@dataclass
class _Cluster:
    messages: list[_WindowMessage] = field(default_factory=list)
    centroid: list[float] = field(default_factory=list)
    similarities: list[float] = field(default_factory=list)
    representative: str = ""
    sentiment: str = "neutral"
    confidence: float = 0.0

    def add(self, message: _WindowMessage, similarity: float) -> None:
        self.messages.append(message)
        self.similarities.append(similarity)
        vectors = [item.embedding for item in self.messages if item.embedding]
        self.centroid = _average_vectors(vectors)

    def mean_similarity(self) -> float:
        if not self.similarities:
            return 1.0
        return sum(self.similarities) / len(self.similarities)


class SemanticAggregator:
    """
    Aggregate short chat bursts into semantic clusters.

    Config:
      window_ms: aggregation window in milliseconds
      similarity_threshold: minimum cosine similarity to merge into a cluster
      max_clusters: maximum clusters published per flush
      embedder: object with `embed(list[str]) -> list[list[float]]`
    """

    def __init__(
        self,
        bus: EventBus,
        window_ms: int = 300,
        similarity_threshold: float = 0.72,
        max_clusters: int = 5,
        embedder: Any | None = None,
    ) -> None:
        self._bus = bus
        self._window_ms = window_ms
        self._sim_threshold = similarity_threshold
        self._max_clusters = max_clusters
        self._embedder = embedder

        self._buffer: list[_WindowMessage] = []
        self._running = False
        self._flush_task: asyncio.Task | None = None

    async def start(self) -> None:
        self._running = True
        self._bus.subscribe(EventType.CHAT_MESSAGE, self._on_chat, sub_id="semantic_chat")
        self._flush_task = asyncio.create_task(
            self._flush_loop(),
            name="nova.semantic_aggregator.flush",
        )
        log.info(
            "Semantic aggregator started (window=%dms, threshold=%.2f, embeddings=%s)",
            self._window_ms,
            self._sim_threshold,
            bool(self._embedder),
        )

    async def stop(self) -> None:
        self._running = False
        if self._flush_task:
            self._flush_task.cancel()
        if self._buffer:
            await self._flush()

    async def _on_chat(self, event: NovaEvent) -> None:
        text = event.payload.get("text", "").strip()
        if not text:
            return

        viewer = event.payload.get("viewer", {})
        self._buffer.append(
            _WindowMessage(
                text=text,
                viewer_name=viewer.get("username", "anonymous"),
                viewer_id=viewer.get("viewer_id", "unknown"),
                timestamp=time.monotonic(),
            )
        )

    async def _flush_loop(self) -> None:
        while self._running:
            await asyncio.sleep(self._window_ms / 1000.0)
            if self._buffer:
                await self._flush()

    async def _embed_messages(self, messages: list[_WindowMessage]) -> None:
        texts = [message.text for message in messages]
        embeddings: list[list[float]]

        if self._embedder is not None:
            try:
                embeddings = await self._embedder.embed(texts)
            except Exception:
                log.exception("Embedding generation failed; falling back to hashed embeddings")
                embeddings = [_hashed_embedding(text) for text in texts]
        else:
            embeddings = [_hashed_embedding(text) for text in texts]

        if len(embeddings) != len(messages):
            log.warning(
                "Embedding backend returned %d vectors for %d messages; using fallback vectors",
                len(embeddings),
                len(messages),
            )
            embeddings = [_hashed_embedding(text) for text in texts]

        for message, embedding in zip(messages, embeddings):
            message.embedding = embedding

    async def _flush(self) -> None:
        messages = self._buffer[:]
        self._buffer.clear()
        if not messages:
            return

        await self._embed_messages(messages)

        clusters: list[_Cluster] = []
        for message in messages:
            best_cluster: _Cluster | None = None
            best_similarity = -1.0

            for cluster in clusters:
                similarity = _cosine_similarity(message.embedding, cluster.centroid)
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_cluster = cluster

            if best_cluster is not None and best_similarity >= self._sim_threshold:
                best_cluster.add(message, best_similarity)
                continue

            if len(clusters) < self._max_clusters:
                cluster = _Cluster()
                cluster.add(message, 1.0)
                clusters.append(cluster)
                continue

            fallback_cluster = max(clusters, key=lambda cluster: len(cluster.messages))
            similarity = _cosine_similarity(message.embedding, fallback_cluster.centroid)
            fallback_cluster.add(message, similarity)

        for cluster in clusters:
            cluster.representative = self._pick_representative(cluster)
            sentiments = [_classify_sentiment(message.text) for message in cluster.messages]
            cluster.sentiment = Counter(sentiments).most_common(1)[0][0]
            size_ratio = len(cluster.messages) / max(1, len(messages))
            cohesion = cluster.mean_similarity()
            cluster.confidence = round(min(1.0, 0.4 * size_ratio + 0.6 * cohesion), 3)

        clusters.sort(key=lambda cluster: (len(cluster.messages), cluster.confidence), reverse=True)

        for cluster in clusters:
            viewer_names = list({message.viewer_name for message in cluster.messages})
            await self._bus.publish(
                NovaEvent(
                    type=EventType.SEMANTIC_CLUSTER,
                    payload={
                        "representative": cluster.representative,
                        "message_count": len(cluster.messages),
                        "dominant_sentiment": cluster.sentiment,
                        "confidence": cluster.confidence,
                        "cluster_similarity": round(cluster.mean_similarity(), 3),
                        "viewer_names": viewer_names[:5],
                        "all_texts": [message.text for message in cluster.messages[:10]],
                    },
                    priority=Priority.NORMAL,
                    source="semantic_aggregator",
                )
            )

        log.debug("Aggregated %d messages into %d semantic clusters", len(messages), len(clusters))

    @staticmethod
    def _pick_representative(cluster: _Cluster) -> str:
        if not cluster.messages:
            return ""
        if not cluster.centroid:
            return max(cluster.messages, key=lambda message: len(message.text)).text
        ranked = sorted(
            cluster.messages,
            key=lambda message: (
                _cosine_similarity(message.embedding, cluster.centroid),
                len(message.text),
            ),
            reverse=True,
        )
        return ranked[0].text
