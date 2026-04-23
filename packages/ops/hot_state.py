"""Hot runtime state backends for cross-process observability and control."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from abc import ABC, abstractmethod
from typing import Any


log = logging.getLogger("nova.hot_state")


class HotStateBackend(ABC):
    @abstractmethod
    async def set_json(self, key: str, value: dict[str, Any], ttl: int | None = None) -> None:
        ...

    @abstractmethod
    async def get_json(self, key: str) -> dict[str, Any] | None:
        ...

    @abstractmethod
    async def delete(self, key: str) -> None:
        ...

    @abstractmethod
    async def list_json(self, prefix: str) -> dict[str, dict[str, Any]]:
        ...

    @abstractmethod
    async def set_if_absent_json(self, key: str, value: dict[str, Any], ttl: int | None = None) -> bool:
        ...


class InMemoryHotStateBackend(HotStateBackend):
    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}
        self._expiries: dict[str, float] = {}

    def _cleanup(self) -> None:
        now = time.time()
        expired = [k for k, ts in self._expiries.items() if ts <= now]
        for key in expired:
            self._store.pop(key, None)
            self._expiries.pop(key, None)

    async def set_json(self, key: str, value: dict[str, Any], ttl: int | None = None) -> None:
        self._cleanup()
        self._store[key] = value
        if ttl:
            self._expiries[key] = time.time() + ttl
        else:
            self._expiries.pop(key, None)

    async def get_json(self, key: str) -> dict[str, Any] | None:
        self._cleanup()
        return self._store.get(key)

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)
        self._expiries.pop(key, None)

    async def list_json(self, prefix: str) -> dict[str, dict[str, Any]]:
        self._cleanup()
        return {k: v for k, v in self._store.items() if k.startswith(prefix)}

    async def set_if_absent_json(self, key: str, value: dict[str, Any], ttl: int | None = None) -> bool:
        self._cleanup()
        if key in self._store:
            return False
        await self.set_json(key, value, ttl=ttl)
        return True


class RedisHotStateBackend(HotStateBackend):
    PREFIX = "nova:hot:"

    def __init__(self, url: str = "redis://localhost:6379", db: int = 0) -> None:
        self._url = url
        self._db = db
        self._client: Any = None

    def _client_or_raise(self) -> Any:
        if self._client is None:
            try:
                import redis.asyncio as aioredis
            except ImportError as exc:
                raise ImportError("redis.asyncio not installed. Run: pip install redis") from exc
            self._client = aioredis.from_url(self._url, db=self._db, decode_responses=True)
        return self._client

    async def set_json(self, key: str, value: dict[str, Any], ttl: int | None = None) -> None:
        client = self._client_or_raise()
        payload = json.dumps(value, ensure_ascii=False, default=str)
        namespaced = f"{self.PREFIX}{key}"
        if ttl:
            await client.setex(namespaced, ttl, payload)
        else:
            await client.set(namespaced, payload)

    async def get_json(self, key: str) -> dict[str, Any] | None:
        client = self._client_or_raise()
        raw = await client.get(f"{self.PREFIX}{key}")
        if raw is None:
            return None
        return json.loads(raw)

    async def delete(self, key: str) -> None:
        client = self._client_or_raise()
        await client.delete(f"{self.PREFIX}{key}")

    async def list_json(self, prefix: str) -> dict[str, dict[str, Any]]:
        client = self._client_or_raise()
        result: dict[str, dict[str, Any]] = {}
        async for key in client.scan_iter(f"{self.PREFIX}{prefix}*"):
            value = await client.get(key)
            if value is not None:
                result[key.removeprefix(self.PREFIX)] = json.loads(value)
        return result

    async def set_if_absent_json(self, key: str, value: dict[str, Any], ttl: int | None = None) -> bool:
        client = self._client_or_raise()
        payload = json.dumps(value, ensure_ascii=False, default=str)
        namespaced = f"{self.PREFIX}{key}"
        result = await client.set(namespaced, payload, ex=ttl, nx=True)
        return bool(result)


class HotStateSync:
    """Periodically exports runtime state to an external backend."""

    def __init__(
        self,
        backend: HotStateBackend,
        *,
        interval_s: float = 5.0,
        ttl_s: int = 30,
        runtime_name: str = "default",
    ) -> None:
        self._backend = backend
        self._interval_s = interval_s
        self._ttl_s = ttl_s
        self._runtime_name = runtime_name
        self._running = False
        self._task: asyncio.Task | None = None
        self._providers: dict[str, Any] = {}

    def bind(self, **providers: Any) -> None:
        self._providers.update(providers)

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="nova.hot_state_sync")
        log.info("Hot state sync started (backend=%s)", type(self._backend).__name__)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
        for suffix in ("runtime", "context", "emotion", "platforms"):
            await self._backend.delete(f"{self._runtime_name}:{suffix}")

    async def publish_once(self) -> None:
        runtime_provider = self._providers.get("runtime")
        context_provider = self._providers.get("context")
        emotion_provider = self._providers.get("emotion")
        platforms_provider = self._providers.get("platforms")

        runtime_payload = runtime_provider() if callable(runtime_provider) else {}
        context_payload = context_provider() if callable(context_provider) else {}
        emotion_payload = emotion_provider() if callable(emotion_provider) else {}
        platforms_payload = platforms_provider() if callable(platforms_provider) else {}

        await self._backend.set_json(f"{self._runtime_name}:runtime", runtime_payload, ttl=self._ttl_s)
        await self._backend.set_json(f"{self._runtime_name}:context", context_payload, ttl=self._ttl_s)
        await self._backend.set_json(f"{self._runtime_name}:emotion", emotion_payload, ttl=self._ttl_s)
        await self._backend.set_json(f"{self._runtime_name}:platforms", platforms_payload, ttl=self._ttl_s)

    async def _loop(self) -> None:
        while self._running:
            try:
                await self.publish_once()
            except Exception as exc:
                log.warning("Hot state sync publish failed: %s", exc)
            await asyncio.sleep(self._interval_s)


class RuntimeStateProjector:
    """Project live viewer/session events into hot state storage."""

    def __init__(
        self,
        backend: HotStateBackend,
        *,
        runtime_name: str = "default",
        ttl_s: int = 300,
    ) -> None:
        self._backend = backend
        self._runtime_name = runtime_name
        self._ttl_s = ttl_s
        self._summary = {
            "message_count": 0,
            "gift_count": 0,
            "super_chat_count": 0,
            "follow_count": 0,
            "viewer_join_count": 0,
            "output_count": 0,
            "last_output_text": "",
            "last_activity_at": 0.0,
        }

    async def project_event(self, event_type: str, payload: dict[str, Any]) -> None:
        now = time.time()
        self._summary["last_activity_at"] = now

        viewer = payload.get("viewer") or {}
        viewer_id = str(viewer.get("viewer_id", "")).strip()
        if viewer_id:
            viewer_key = f"{self._runtime_name}:viewers:{viewer_id}"
            existing = await self._backend.get_json(viewer_key) or {
                "viewer_id": viewer_id,
                "username": viewer.get("username", "anonymous"),
                "platform": viewer.get("platform", "unknown"),
                "interaction_count": 0,
                "gift_total": 0.0,
                "is_member": bool(viewer.get("is_member", False)),
            }
            existing["username"] = viewer.get("username", existing.get("username", "anonymous"))
            existing["platform"] = viewer.get("platform", existing.get("platform", "unknown"))
            existing["is_member"] = bool(viewer.get("is_member", existing.get("is_member", False)))
            existing["last_seen_at"] = now
            existing["last_event_type"] = event_type
            existing["interaction_count"] = int(existing.get("interaction_count", 0)) + 1
            if event_type in {"platform.gift_received", "platform.super_chat"}:
                existing["gift_total"] = float(existing.get("gift_total", 0.0)) + float(payload.get("amount", 0.0))
            if payload.get("text"):
                existing["last_message"] = payload.get("text")
            await self._backend.set_json(viewer_key, existing, ttl=self._ttl_s)

        if event_type == "platform.chat_message":
            self._summary["message_count"] += 1
        elif event_type == "platform.gift_received":
            self._summary["gift_count"] += 1
        elif event_type == "platform.super_chat":
            self._summary["super_chat_count"] += 1
        elif event_type == "platform.follow":
            self._summary["follow_count"] += 1
        elif event_type == "platform.viewer_join":
            self._summary["viewer_join_count"] += 1
        elif event_type == "cognitive.safe_output":
            self._summary["output_count"] += 1
            self._summary["last_output_text"] = str(payload.get("text", ""))[:200]

        await self._backend.set_json(
            f"{self._runtime_name}:summary",
            dict(self._summary),
            ttl=self._ttl_s,
        )

    async def get_summary(self) -> dict[str, Any] | None:
        return await self._backend.get_json(f"{self._runtime_name}:summary")

    async def get_viewer(self, viewer_id: str) -> dict[str, Any] | None:
        return await self._backend.get_json(f"{self._runtime_name}:viewers:{viewer_id}")

    async def list_viewers(self) -> dict[str, dict[str, Any]]:
        prefix = f"{self._runtime_name}:viewers:"
        return await self._backend.list_json(prefix)


class RuntimeSessionState:
    """Redis-friendly runtime session state with idempotency and online viewers."""

    def __init__(
        self,
        backend: HotStateBackend,
        *,
        runtime_name: str = "default",
        session_id: str = "default",
        ttl_s: int = 300,
        idempotency_ttl_s: int = 600,
    ) -> None:
        self._backend = backend
        self._runtime_name = runtime_name
        self._session_id = session_id
        self._ttl_s = ttl_s
        self._idempotency_ttl_s = idempotency_ttl_s

    def _session_key(self) -> str:
        return f"{self._runtime_name}:sessions:{self._session_id}"

    def _viewer_key(self, viewer_id: str) -> str:
        return f"{self._runtime_name}:sessions:{self._session_id}:viewers:{viewer_id}"

    def _idem_key(self, event_id: str) -> str:
        return f"{self._runtime_name}:sessions:{self._session_id}:idempotency:{event_id}"

    async def mark_session_started(self, metadata: dict[str, Any]) -> None:
        payload = {
            "session_id": self._session_id,
            "runtime_name": self._runtime_name,
            "status": "running",
            "started_at": time.time(),
            "last_activity_at": time.time(),
            "message_count": 0,
            "gift_count": 0,
            "super_chat_count": 0,
            "follow_count": 0,
            "viewer_join_count": 0,
            "output_count": 0,
            "last_output_text": "",
            **metadata,
        }
        await self._backend.set_json(self._session_key(), payload, ttl=self._ttl_s)

    async def mark_session_stopped(self) -> None:
        existing = await self._backend.get_json(self._session_key()) or {"session_id": self._session_id}
        existing["status"] = "stopped"
        existing["stopped_at"] = time.time()
        await self._backend.set_json(self._session_key(), existing, ttl=self._ttl_s)

    async def project_event(self, event_id: str, event_type: str, payload: dict[str, Any]) -> bool:
        accepted = await self._backend.set_if_absent_json(
            self._idem_key(event_id),
            {"event_id": event_id, "event_type": event_type, "accepted_at": time.time()},
            ttl=self._idempotency_ttl_s,
        )
        if not accepted:
            return False

        session = await self._backend.get_json(self._session_key()) or {
            "session_id": self._session_id,
            "runtime_name": self._runtime_name,
            "status": "running",
            "started_at": time.time(),
            "message_count": 0,
            "gift_count": 0,
            "super_chat_count": 0,
            "follow_count": 0,
            "viewer_join_count": 0,
            "output_count": 0,
            "last_output_text": "",
        }
        session["last_activity_at"] = time.time()

        if event_type == "platform.chat_message":
            session["message_count"] = int(session.get("message_count", 0)) + 1
        elif event_type == "platform.gift_received":
            session["gift_count"] = int(session.get("gift_count", 0)) + 1
        elif event_type == "platform.super_chat":
            session["super_chat_count"] = int(session.get("super_chat_count", 0)) + 1
        elif event_type == "platform.follow":
            session["follow_count"] = int(session.get("follow_count", 0)) + 1
        elif event_type == "platform.viewer_join":
            session["viewer_join_count"] = int(session.get("viewer_join_count", 0)) + 1
        elif event_type == "cognitive.safe_output":
            session["output_count"] = int(session.get("output_count", 0)) + 1
            session["last_output_text"] = str(payload.get("text", ""))[:200]

        viewer = payload.get("viewer") or {}
        viewer_id = str(viewer.get("viewer_id", "")).strip()
        if viewer_id:
            viewer_state = await self._backend.get_json(self._viewer_key(viewer_id)) or {
                "viewer_id": viewer_id,
                "username": viewer.get("username", "anonymous"),
                "platform": viewer.get("platform", "unknown"),
                "is_member": bool(viewer.get("is_member", False)),
                "gift_total": 0.0,
                "interaction_count": 0,
            }
            viewer_state["username"] = viewer.get("username", viewer_state.get("username", "anonymous"))
            viewer_state["platform"] = viewer.get("platform", viewer_state.get("platform", "unknown"))
            viewer_state["is_member"] = bool(viewer.get("is_member", viewer_state.get("is_member", False)))
            viewer_state["last_seen_at"] = time.time()
            viewer_state["online"] = True
            viewer_state["last_event_type"] = event_type
            viewer_state["interaction_count"] = int(viewer_state.get("interaction_count", 0)) + 1
            if event_type in {"platform.gift_received", "platform.super_chat"}:
                viewer_state["gift_total"] = float(viewer_state.get("gift_total", 0.0)) + float(payload.get("amount", 0.0))
            if payload.get("text"):
                viewer_state["last_message"] = payload.get("text")
            await self._backend.set_json(self._viewer_key(viewer_id), viewer_state, ttl=self._ttl_s)

        await self._backend.set_json(self._session_key(), session, ttl=self._ttl_s)
        return True

    async def get_session(self, session_id: str | None = None) -> dict[str, Any] | None:
        key = self._session_key() if session_id is None else f"{self._runtime_name}:sessions:{session_id}"
        return await self._backend.get_json(key)

    async def list_viewers(self) -> dict[str, dict[str, Any]]:
        prefix = f"{self._runtime_name}:sessions:{self._session_id}:viewers:"
        return await self._backend.list_json(prefix)

    async def get_viewer(self, viewer_id: str) -> dict[str, Any] | None:
        return await self._backend.get_json(self._viewer_key(viewer_id))

    async def list_sessions(self, all_instances: bool = False) -> dict[str, dict[str, Any]]:
        prefix = "" if all_instances else f"{self._runtime_name}:sessions:"
        all_entries = await self._backend.list_json(prefix)
        result: dict[str, dict[str, Any]] = {}
        for key, value in all_entries.items():
            if ":viewers:" in key or ":idempotency:" in key:
                continue
            if ":sessions:" in key and key.count(":") == 2:
                result[key] = value
        return result


def create_hot_state_backend(config: dict[str, Any] | None = None) -> HotStateBackend:
    config = config or {}
    backend = config.get("backend", "memory")

    if backend == "redis":
        return RedisHotStateBackend(
            url=config.get("url", "redis://localhost:6379"),
            db=config.get("db", 0),
        )
    return InMemoryHotStateBackend()
