"""
NOVA Knowledge Module
=====================
RAG (Retrieval-Augmented Generation) knowledge base.

Components:
  - embedding_service.py — Embedding generation (Ollama / OpenAI / local)
  - vector_store.py      — Vector store abstraction (InMemory / Qdrant)
  - knowledge_base.py    — Document ingestion + retrieval pipeline
  - rag_prompt.py        — Prompt builder that injects retrieved context
"""

from packages.knowledge.embedding_service import (
    EmbeddingService,
    MockEmbedder,
    OllamaEmbedder,
    OpenAIEmbedder,
    create_embedder,
)
from packages.knowledge.knowledge_base import KnowledgeBase, TextChunk, chunk_text
from packages.knowledge.rag_prompt import RAGContext, RAGPromptBuilder
from packages.knowledge.vector_store import (
    InMemoryVectorStore,
    QdrantVectorStore,
    SearchResult,
    VectorDocument,
    VectorStore,
    create_vector_store,
)

__all__ = [
    # Embedding
    "EmbeddingService", "OllamaEmbedder", "OpenAIEmbedder", "MockEmbedder", "create_embedder",
    # Vector store
    "VectorStore", "InMemoryVectorStore", "QdrantVectorStore", "VectorDocument", "SearchResult",
    "create_vector_store",
    # Knowledge base
    "KnowledgeBase", "TextChunk", "chunk_text",
    # RAG prompt
    "RAGPromptBuilder", "RAGContext",
]
