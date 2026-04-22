"""
NOVA Vector Store
=================
Abstraction layer for vector storage + ANN search.

Backends:
  - InMemoryVectorStore  — pure Python, zero deps, for dev/test
  - QdrantVectorStore    — production ANN via Qdrant

Both implement the same interface — swap backend without changing callers.
"""
from __future__ import annotations

import logging
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

log = logging.getLogger("nova.vector_store")


# ─── Data types ──────────────────────────────────────────────────────────────

@dataclass
class VectorDocument:
    """A document stored in the vector store."""
    doc_id: str
    text: str
    vector: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0  # similarity score, filled on retrieval


@dataclass
class SearchResult:
    """Result from a vector similarity search."""
    doc: VectorDocument
    score: float


# ─── Abstract interface ──────────────────────────────────────────────────────

class VectorStore(ABC):
    """Vector store interface. All backends implement this."""

    @abstractmethod
    async def upsert(self, docs: list[VectorDocument]) -> None:
        """Insert or update documents."""
        ...

    @abstractmethod
    async def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
        score_threshold: float = 0.0,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        """Search for similar documents by vector."""
        ...

    @abstractmethod
    async def delete(self, doc_ids: list[str]) -> None:
        """Delete documents by ID."""
        ...

    @abstractmethod
    async def count(self) -> int:
        """Return the total number of stored documents."""
        ...


# ─── Similarity functions ────────────────────────────────────────────────────

def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ─── In-Memory backend ──────────────────────────────────────────────────────

class InMemoryVectorStore(VectorStore):
    """
    Simple in-memory vector store with brute-force cosine search.
    Suitable for development, testing, and small knowledge bases (< 10k docs).
    """

    def __init__(self) -> None:
        self._docs: dict[str, VectorDocument] = {}

    async def upsert(self, docs: list[VectorDocument]) -> None:
        for doc in docs:
            self._docs[doc.doc_id] = doc
        log.debug("InMemory upserted %d docs (total: %d)", len(docs), len(self._docs))

    async def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
        score_threshold: float = 0.0,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        candidates: list[SearchResult] = []
        for doc in self._docs.values():
            # Apply metadata filters
            if filters and not self._match_filters(doc, filters):
                continue
            score = _cosine_similarity(query_vector, doc.vector)
            if score >= score_threshold:
                candidates.append(SearchResult(
                    doc=VectorDocument(
                        doc_id=doc.doc_id,
                        text=doc.text,
                        vector=doc.vector,
                        metadata=doc.metadata,
                        score=score,
                    ),
                    score=score,
                ))
        candidates.sort(key=lambda r: r.score, reverse=True)
        return candidates[:top_k]

    async def delete(self, doc_ids: list[str]) -> None:
        for doc_id in doc_ids:
            self._docs.pop(doc_id, None)

    async def count(self) -> int:
        return len(self._docs)

    @staticmethod
    def _match_filters(doc: VectorDocument, filters: dict[str, Any]) -> bool:
        for key, value in filters.items():
            if doc.metadata.get(key) != value:
                return False
        return True


# ─── Qdrant backend ──────────────────────────────────────────────────────────

class QdrantVectorStore(VectorStore):
    """
    Qdrant vector database backend for production use.
    Requires: qdrant-client package and a running Qdrant instance.
    """

    def __init__(
        self,
        collection_name: str = "nova_knowledge",
        url: str = "http://localhost:6333",
        api_key: str | None = None,
        vector_dim: int = 768,
    ) -> None:
        self._collection = collection_name
        self._url = url
        self._api_key = api_key
        self._vector_dim = vector_dim
        self._client: Any = None

    def _get_client(self) -> Any:
        """Lazy-init Qdrant client."""
        if self._client is None:
            try:
                from qdrant_client import QdrantClient
                self._client = QdrantClient(url=self._url, api_key=self._api_key)
            except ImportError:
                raise ImportError(
                    "qdrant-client not installed. Run: pip install qdrant-client"
                )
        return self._client

    async def _ensure_collection(self) -> None:
        """Create the collection if it doesn't exist."""
        from qdrant_client.models import Distance, VectorParams
        client = self._get_client()
        collections = client.get_collections().collections
        names = [c.name for c in collections]
        if self._collection not in names:
            client.create_collection(
                collection_name=self._collection,
                vectors_config=VectorParams(size=self._vector_dim, distance=Distance.COSINE),
            )
            log.info("Created Qdrant collection '%s' (dim=%d)", self._collection, self._vector_dim)

    async def upsert(self, docs: list[VectorDocument]) -> None:
        from qdrant_client.models import PointStruct
        await self._ensure_collection()
        client = self._get_client()
        points = [
            PointStruct(
                id=doc.doc_id,
                vector=doc.vector,
                payload={"text": doc.text, **doc.metadata},
            )
            for doc in docs
        ]
        client.upsert(collection_name=self._collection, points=points)
        log.debug("Qdrant upserted %d docs to '%s'", len(docs), self._collection)

    async def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
        score_threshold: float = 0.0,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        await self._ensure_collection()
        client = self._get_client()

        qdrant_filter = None
        if filters:
            conditions = [
                FieldCondition(key=k, match=MatchValue(value=v))
                for k, v in filters.items()
            ]
            qdrant_filter = Filter(must=conditions)

        hits = client.search(
            collection_name=self._collection,
            query_vector=query_vector,
            limit=top_k,
            score_threshold=score_threshold,
            query_filter=qdrant_filter,
        )

        results = []
        for hit in hits:
            payload = hit.payload or {}
            text = payload.pop("text", "")
            results.append(SearchResult(
                doc=VectorDocument(
                    doc_id=str(hit.id),
                    text=text,
                    vector=[],  # Don't return vectors from Qdrant to save bandwidth
                    metadata=payload,
                    score=hit.score,
                ),
                score=hit.score,
            ))
        return results

    async def delete(self, doc_ids: list[str]) -> None:
        client = self._get_client()
        from qdrant_client.models import PointIdsList
        client.delete(
            collection_name=self._collection,
            points_selector=PointIdsList(points=doc_ids),
        )

    async def count(self) -> int:
        await self._ensure_collection()
        client = self._get_client()
        info = client.get_collection(self._collection)
        return info.points_count or 0


# ─── Factory ─────────────────────────────────────────────────────────────────

def create_vector_store(config: dict[str, Any] | None = None) -> VectorStore:
    """Create a vector store from config dict."""
    config = config or {}
    backend = config.get("backend", "memory")

    if backend == "memory":
        return InMemoryVectorStore()
    elif backend == "qdrant":
        return QdrantVectorStore(
            collection_name=config.get("collection", "nova_knowledge"),
            url=config.get("url", "http://localhost:6333"),
            api_key=config.get("api_key"),
            vector_dim=config.get("vector_dim", 768),
        )
    else:
        log.warning("Unknown vector store backend '%s', falling back to InMemory", backend)
        return InMemoryVectorStore()
