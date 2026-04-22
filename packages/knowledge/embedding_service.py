"""
NOVA Embedding Service
======================
Pluggable embedding generation for RAG.

Backends:
  - OllamaEmbedder  — local Ollama /embeddings endpoint (default)
  - OpenAIEmbedder  — OpenAI / compatible API (text-embedding-3-small)
  - MockEmbedder    — random vectors for testing
"""
from __future__ import annotations

import hashlib
import logging
import struct
from abc import ABC, abstractmethod
from typing import Any

import httpx

log = logging.getLogger("nova.embedding")


# ─── Abstract interface ──────────────────────────────────────────────────────

class EmbeddingService(ABC):
    """Embedding generation interface. All backends implement this."""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a batch of texts."""
        ...

    @abstractmethod
    async def embed_single(self, text: str) -> list[float]:
        """Generate embedding for a single text."""
        ...

    @property
    @abstractmethod
    def dim(self) -> int:
        """Embedding dimensionality."""
        ...


# ─── Ollama backend ──────────────────────────────────────────────────────────

class OllamaEmbedder(EmbeddingService):
    """
    Ollama /embeddings endpoint.
    Works with any Ollama model that supports embeddings (nomic-embed-text, mxbai-embed-large, etc.)
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "nomic-embed-text",
        timeout: float = 30.0,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
        )
        self._model = model
        self._dim: int | None = None

    @property
    def dim(self) -> int:
        if self._dim is None:
            # Default dimensions for known models
            _KNOWN_DIMS: dict[str, int] = {
                "nomic-embed-text": 768,
                "mxbai-embed-large": 1024,
                "all-minilm": 384,
                "snowflake-arctic-embed": 1024,
            }
            self._dim = _KNOWN_DIMS.get(self._model, 768)
        return self._dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = {"model": self._model, "input": texts}
        resp = await self._client.post("/api/embed", json=payload)
        resp.raise_for_status()
        data = resp.json()
        embeddings = data.get("embeddings", [])
        if embeddings and self._dim is None:
            self._dim = len(embeddings[0])
        return embeddings

    async def embed_single(self, text: str) -> list[float]:
        results = await self.embed([text])
        return results[0] if results else [0.0] * self.dim

    async def close(self) -> None:
        await self._client.aclose()


# ─── OpenAI-compatible backend ───────────────────────────────────────────────

class OpenAIEmbedder(EmbeddingService):
    """
    OpenAI /v1/embeddings endpoint.
    Works with OpenAI, Azure OpenAI, and any compatible API.
    """

    def __init__(
        self,
        base_url: str = "https://api.openai.com/v1",
        api_key: str = "",
        model: str = "text-embedding-3-small",
        timeout: float = 30.0,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )
        self._model = model
        self._dim: int | None = None

    @property
    def dim(self) -> int:
        if self._dim is None:
            _KNOWN_DIMS: dict[str, int] = {
                "text-embedding-3-small": 1536,
                "text-embedding-3-large": 3072,
                "text-embedding-ada-002": 1536,
            }
            self._dim = _KNOWN_DIMS.get(self._model, 1536)
        return self._dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = {"model": self._model, "input": texts}
        resp = await self._client.post("/embeddings", json=payload)
        resp.raise_for_status()
        data = resp.json()
        embeddings = [d["embedding"] for d in data["data"]]
        if embeddings and self._dim is None:
            self._dim = len(embeddings[0])
        return embeddings

    async def embed_single(self, text: str) -> list[float]:
        results = await self.embed([text])
        return results[0] if results else [0.0] * self.dim

    async def close(self) -> None:
        await self._client.aclose()


# ─── Mock backend (testing) ──────────────────────────────────────────────────

class MockEmbedder(EmbeddingService):
    """
    Deterministic pseudo-random embeddings for testing.
    Same text always produces the same vector.
    """

    def __init__(self, dim: int = 64) -> None:
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    def _hash_to_vector(self, text: str) -> list[float]:
        """Generate a deterministic pseudo-random vector from text hash."""
        h = hashlib.sha256(text.encode()).digest()
        vector = []
        for i in range(self._dim):
            # Use 4 bytes at a time, normalize to [-1, 1]
            idx = (i * 4) % len(h)
            val = struct.unpack("f", h[idx:idx+4].ljust(4, b'\x00'))[0]
            vector.append(val if abs(val) <= 1.0 else val / abs(val))
        return vector

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._hash_to_vector(t) for t in texts]

    async def embed_single(self, text: str) -> list[float]:
        return self._hash_to_vector(text)

    async def close(self) -> None:
        pass


# ─── Factory ─────────────────────────────────────────────────────────────────

def create_embedder(config: dict[str, Any] | None = None) -> EmbeddingService:
    """Create an embedding service from config dict."""
    config = config or {}
    backend = config.get("backend", "ollama")

    if backend == "ollama":
        return OllamaEmbedder(
            base_url=config.get("base_url", "http://localhost:11434"),
            model=config.get("model", "nomic-embed-text"),
        )
    elif backend == "openai":
        return OpenAIEmbedder(
            base_url=config.get("base_url", "https://api.openai.com/v1"),
            api_key=config.get("api_key", ""),
            model=config.get("model", "text-embedding-3-small"),
        )
    elif backend == "mock":
        return MockEmbedder(dim=config.get("dim", 64))
    else:
        log.warning("Unknown embedder backend '%s', falling back to Ollama", backend)
        return OllamaEmbedder()
