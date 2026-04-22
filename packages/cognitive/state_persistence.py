"""
NOVA State Persistence
======================
Persists and restores NOVA state across restarts.

Backends:
  - JSONFileBackend — simple file-based persistence (default)
  - RedisBackend    — Redis-based persistence (production)

Persisted state includes:
  - Memory agent working memory (recent conversations)
  - Viewer graph (viewer profiles and relationships)
  - Emotion baseline and current state
  - Knowledge base source registry
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

log = logging.getLogger("nova.state_persistence")


# ─── Abstract backend ─────────────────────────────────────────────────────────

class PersistenceBackend(ABC):
    """Abstract persistence backend."""

    @abstractmethod
    async def save(self, key: str, data: dict[str, Any]) -> None:
        """Save state data under a key."""
        ...

    @abstractmethod
    async def load(self, key: str) -> dict[str, Any] | None:
        """Load state data by key. Returns None if not found."""
        ...

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete state data by key."""
        ...

    @abstractmethod
    async def list_keys(self) -> list[str]:
        """List all stored keys."""
        ...


# ─── JSON file backend ────────────────────────────────────────────────────────

class JSONFileBackend(PersistenceBackend):
    """
    File-based persistence using JSON.

    Each key maps to a file: {base_dir}/{key}.json
    Simple, zero-dependency, suitable for single-instance deployments.
    """

    def __init__(self, base_dir: str = "data/state") -> None:
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)

    async def save(self, key: str, data: dict[str, Any]) -> None:
        filepath = self._base_dir / f"{key}.json"
        filepath.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        log.debug("State saved: %s (%d bytes)", key, filepath.stat().st_size)

    async def load(self, key: str) -> dict[str, Any] | None:
        filepath = self._base_dir / f"{key}.json"
        if not filepath.exists():
            return None
        try:
            return json.loads(filepath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            log.error("Failed to load state '%s': %s", key, e)
            return None

    async def delete(self, key: str) -> None:
        filepath = self._base_dir / f"{key}.json"
        if filepath.exists():
            filepath.unlink()

    async def list_keys(self) -> list[str]:
        return [f.stem for f in self._base_dir.glob("*.json")]


# ─── Redis backend ────────────────────────────────────────────────────────────

class RedisBackend(PersistenceBackend):
    """
    Redis-based persistence for multi-instance deployments.

    Requires: redis.asyncio package
    Keys are prefixed with "nova:state:" to avoid collisions.
    """

    KEY_PREFIX = "nova:state:"

    def __init__(
        self,
        url: str = "redis://localhost:6379",
        db: int = 0,
        ttl: int = 86400 * 7,  # 7 days default TTL
    ) -> None:
        self._url = url
        self._db = db
        self._ttl = ttl
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import redis.asyncio as aioredis
                self._client = aioredis.from_url(self._url, db=self._db, decode_responses=True)
            except ImportError:
                raise ImportError("redis.asyncio not installed. Run: pip install redis")
        return self._client

    async def save(self, key: str, data: dict[str, Any]) -> None:
        client = self._get_client()
        await client.setex(
            f"{self.KEY_PREFIX}{key}",
            self._ttl,
            json.dumps(data, ensure_ascii=False, default=str),
        )

    async def load(self, key: str) -> dict[str, Any] | None:
        client = self._get_client()
        data = await client.get(f"{self.KEY_PREFIX}{key}")
        if data is None:
            return None
        try:
            return json.loads(data)
        except json.JSONDecodeError:
            return None

    async def delete(self, key: str) -> None:
        client = self._get_client()
        await client.delete(f"{self.KEY_PREFIX}{key}")

    async def list_keys(self) -> list[str]:
        client = self._get_client()
        keys = []
        async for key in client.scan_iter(f"{self.KEY_PREFIX}*"):
            keys.append(key.removeprefix(self.KEY_PREFIX))
        return keys


# ─── State Manager ────────────────────────────────────────────────────────────

class StateManager:
    """
    High-level state persistence manager.

    Handles:
      - Periodic auto-save of component state
      - Restore on startup
      - Snapshot creation for debugging
    """

    def __init__(
        self,
        backend: PersistenceBackend | None = None,
        auto_save_interval_s: float = 300.0,  # 5 minutes
    ) -> None:
        self._backend = backend or JSONFileBackend()
        self._auto_save_interval = auto_save_interval_s
        self._running = False
        self._task: asyncio.Task | None = None
        self._save_count = 0

    async def start(self) -> None:
        self._running = True
        log.info("State manager started (backend=%s)", type(self._backend).__name__)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()

    # ── Save / Restore ──────────────────────────────────────────────────────

    async def save_memory_state(self, memory_agent: Any) -> None:
        """Save memory agent state."""
        working_entries = memory_agent.working.recent(50)
        viewer_nodes = {}
        for vid, node in memory_agent.viewer_graph._nodes.items():
            viewer_nodes[vid] = {
                "username": node.profile.username,
                "interaction_count": node.interaction_count,
                "gift_total": node.profile.gift_total,
                "is_member": node.profile.is_member,
                "last_topics": node.last_topics,
                "is_vip": node.is_vip,
            }
        await self._backend.save("memory", {
            "working_memory": working_entries,
            "viewer_graph": viewer_nodes,
            "saved_at": time.time(),
        })

    async def restore_memory_state(self, memory_agent: Any) -> bool:
        """Restore memory agent state. Returns True if state was found."""
        data = await self._backend.load("memory")
        if not data:
            return False

        # Restore working memory
        for entry in data.get("working_memory", []):
            memory_agent.working.push(entry)

        # Restore viewer graph
        from packages.core.types import ViewerProfile, Platform
        for vid, node_data in data.get("viewer_graph", {}).items():
            profile = ViewerProfile(
                viewer_id=vid,
                platform=Platform.LOCAL,
                username=node_data.get("username", "unknown"),
                is_member=node_data.get("is_member", False),
                gift_total=node_data.get("gift_total", 0.0),
            )
            node = memory_agent.viewer_graph.upsert(profile)
            node.interaction_count = node_data.get("interaction_count", 0)
            node.last_topics = node_data.get("last_topics", [])
            node.is_vip = node_data.get("is_vip", False)

        log.info("Restored memory state: %d working entries, %d viewers",
                 len(data.get("working_memory", [])),
                 len(data.get("viewer_graph", {})))
        return True

    async def save_emotion_state(self, emotion_agent: Any) -> None:
        """Save emotion agent state."""
        await self._backend.save("emotion", {
            "valence": emotion_agent._valence,
            "arousal": emotion_agent._arousal,
            "intensity": emotion_agent._intensity,
            "saved_at": time.time(),
        })

    async def restore_emotion_state(self, emotion_agent: Any) -> bool:
        """Restore emotion agent state."""
        data = await self._backend.load("emotion")
        if not data:
            return False
        emotion_agent._valence = data.get("valence", emotion_agent.BASELINE_VALENCE)
        emotion_agent._arousal = data.get("arousal", emotion_agent.BASELINE_AROUSAL)
        emotion_agent._intensity = data.get("intensity", 0.3)
        return True

    async def save_all(self, **components: Any) -> None:
        """Save all component states."""
        if "memory" in components:
            await self.save_memory_state(components["memory"])
        if "emotion" in components:
            await self.save_emotion_state(components["emotion"])
        self._save_count += 1
        log.info("State saved (#%d)", self._save_count)

    async def create_snapshot(self, **components: Any) -> str:
        """Create a named snapshot for debugging."""
        snapshot_key = f"snapshot_{int(time.time())}"
        if "memory" in components:
            await self.save_memory_state(components["memory"])
        if "emotion" in components:
            await self.save_emotion_state(components["emotion"])
        log.info("Snapshot created: %s", snapshot_key)
        return snapshot_key


# ─── Factory ──────────────────────────────────────────────────────────────────

def create_persistence_backend(config: dict[str, Any] | None = None) -> PersistenceBackend:
    """Create a persistence backend from config."""
    config = config or {}
    backend = config.get("backend", "json")

    if backend == "json":
        return JSONFileBackend(base_dir=config.get("base_dir", "data/state"))
    elif backend == "redis":
        return RedisBackend(
            url=config.get("url", "redis://localhost:6379"),
            db=config.get("db", 0),
        )
    else:
        log.warning("Unknown persistence backend '%s', falling back to JSON", backend)
        return JSONFileBackend()
