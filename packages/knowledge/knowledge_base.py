"""
NOVA Knowledge Base
===================
Document ingestion + retrieval pipeline for RAG.

Supports:
  - Text chunking (fixed-size with overlap)
  - Automatic embedding generation
  - Vector store upsert + search
  - Source tracking and metadata
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from packages.knowledge.embedding_service import EmbeddingService
from packages.knowledge.vector_store import (
    InMemoryVectorStore,
    SearchResult,
    VectorDocument,
    VectorStore,
    create_vector_store,
)

log = logging.getLogger("nova.knowledge_base")


# ─── Chunking ────────────────────────────────────────────────────────────────

@dataclass
class TextChunk:
    """A chunk of text extracted from a source document."""
    text: str
    chunk_index: int
    source_id: str
    metadata: dict[str, Any] = field(default_factory=dict)


def chunk_text(
    text: str,
    chunk_size: int = 500,
    overlap: int = 100,
    source_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> list[TextChunk]:
    """
    Split text into overlapping chunks of approximately `chunk_size` characters.
    Tries to break at sentence boundaries (Chinese/English punctuation).
    """
    if not text.strip():
        return []

    metadata = metadata or {}
    chunks: list[TextChunk] = []
    start = 0
    idx = 0

    while start < len(text):
        end = start + chunk_size

        # If not at the end, try to break at a sentence boundary
        if end < len(text):
            # Look for the last sentence-ending punctuation in the chunk
            search_start = max(start, end - overlap)
            boundary = -1
            for punct in ['。', '！', '？', '；', '.', '!', '?', ';', '\n']:
                pos = text.rfind(punct, search_start, end)
                if pos > boundary:
                    boundary = pos
            if boundary > start:
                end = boundary + 1

        chunk_text = text[start:end].strip()
        if chunk_text:
            chunks.append(TextChunk(
                text=chunk_text,
                chunk_index=idx,
                source_id=source_id,
                metadata={**metadata, "chunk_index": idx},
            ))
            idx += 1

        start = end - overlap if end < len(text) else end

    return chunks


# ─── Knowledge Base ──────────────────────────────────────────────────────────

class KnowledgeBase:
    """
    High-level RAG knowledge base.

    Ingestion flow:
      1. Split document into chunks
      2. Generate embeddings for all chunks
      3. Store chunks + embeddings in vector store

    Retrieval flow:
      1. Embed the query
      2. Search vector store for top-k similar chunks
      3. Return results with metadata
    """

    def __init__(
        self,
        embedder: EmbeddingService,
        store: VectorStore | None = None,
        chunk_size: int = 500,
        chunk_overlap: int = 100,
    ) -> None:
        self._embedder = embedder
        self._store = store or InMemoryVectorStore()
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._source_registry: dict[str, dict[str, Any]] = {}

    # ── Ingestion ────────────────────────────────────────────────────────────

    async def ingest(
        self,
        text: str,
        source_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """
        Ingest a text document into the knowledge base.
        Returns the number of chunks created.
        """
        source_id = source_id or str(uuid.uuid4())
        metadata = metadata or {}

        # Register source
        self._source_registry[source_id] = {
            "chunk_count": 0,
            "ingested_at": __import__("datetime").datetime.utcnow().isoformat(),
            **metadata,
        }

        # 1. Chunk
        chunks = chunk_text(
            text,
            chunk_size=self._chunk_size,
            overlap=self._chunk_overlap,
            source_id=source_id,
            metadata=metadata,
        )
        if not chunks:
            log.warning("No chunks produced for source '%s' (empty text?)", source_id)
            return 0

        # 2. Embed
        texts = [c.text for c in chunks]
        embeddings = await self._embedder.embed(texts)
        if len(embeddings) != len(chunks):
            log.error(
                "Embedding count mismatch: %d chunks vs %d embeddings",
                len(chunks), len(embeddings),
            )
            return 0

        # 3. Store
        docs = [
            VectorDocument(
                doc_id=f"{source_id}__{c.chunk_index}",
                text=c.text,
                vector=emb,
                metadata={**c.metadata, "source_id": source_id},
            )
            for c, emb in zip(chunks, embeddings)
        ]
        await self._store.upsert(docs)

        # Update registry
        self._source_registry[source_id]["chunk_count"] = len(chunks)
        log.info("Ingested source '%s': %d chunks", source_id, len(chunks))
        return len(chunks)

    async def ingest_documents(
        self,
        documents: list[dict[str, Any]],
    ) -> int:
        """
        Batch ingest multiple documents.
        Each document dict should have: text, source_id (optional), metadata (optional).
        Returns total chunks created.
        """
        total = 0
        for doc in documents:
            total += await self.ingest(
                text=doc["text"],
                source_id=doc.get("source_id"),
                metadata=doc.get("metadata"),
            )
        return total

    # ── Retrieval ────────────────────────────────────────────────────────────

    async def retrieve(
        self,
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.3,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        """
        Retrieve relevant chunks for a query.
        Returns SearchResult objects sorted by similarity score.
        """
        query_embedding = await self._embedder.embed_single(query)
        results = await self._store.search(
            query_vector=query_embedding,
            top_k=top_k,
            score_threshold=score_threshold,
            filters=filters,
        )
        log.debug("Retrieved %d results for query: %.50s…", len(results), query)
        return results

    async def retrieve_texts(
        self,
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.3,
    ) -> list[str]:
        """Convenience: retrieve just the text strings for a query."""
        results = await self.retrieve(query, top_k, score_threshold)
        return [r.doc.text for r in results]

    # ── Management ───────────────────────────────────────────────────────────

    async def delete_source(self, source_id: str) -> None:
        """Delete all chunks for a given source."""
        info = self._source_registry.get(source_id, {})
        chunk_count = info.get("chunk_count", 0)
        doc_ids = [f"{source_id}__{i}" for i in range(chunk_count)]
        await self._store.delete(doc_ids)
        self._source_registry.pop(source_id, None)
        log.info("Deleted source '%s' (%d chunks)", source_id, chunk_count)

    async def count(self) -> int:
        """Total documents in the vector store."""
        return await self._store.count()

    def list_sources(self) -> dict[str, dict[str, Any]]:
        """Return metadata about all ingested sources."""
        return dict(self._source_registry)

    @property
    def embedder(self) -> EmbeddingService:
        return self._embedder

    @property
    def store(self) -> VectorStore:
        return self._store
