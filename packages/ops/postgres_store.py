"""Postgres persistence for conversation and safety runtime events."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from packages.core.types import EventType, NovaEvent


log = logging.getLogger("nova.postgres_store")


class PostgresRuntimeStore:
    def __init__(
        self,
        dsn: str,
        *,
        schema: str = "public",
        persist_conversations: bool = True,
        persist_safety: bool = True,
    ) -> None:
        self._dsn = dsn
        self._schema = schema
        self._persist_conversations = persist_conversations
        self._persist_safety = persist_safety
        self._pool: Any = None

    async def start(self) -> None:
        import asyncpg

        self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=5)
        await self._ensure_schema()
        log.info("Postgres runtime store started (schema=%s)", self._schema)

    async def stop(self) -> None:
        if self._pool is not None:
            await self._pool.close()

    async def _ensure_schema(self) -> None:
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            await conn.execute(f'create schema if not exists "{self._schema}"')
            await conn.execute(
                f'''
                create table if not exists "{self._schema}".conversation_turns (
                    id text primary key,
                    event_type text not null,
                    source text not null,
                    trace_id text,
                    ts timestamptz not null,
                    role text not null,
                    viewer_id text,
                    viewer_name text,
                    text_content text,
                    payload_json jsonb not null default '{{}}'::jsonb
                )
                '''
            )
            await conn.execute(
                f'''
                create table if not exists "{self._schema}".safety_events (
                    id text primary key,
                    trace_id text,
                    ts timestamptz not null,
                    category text not null,
                    reason text,
                    blocked_text text,
                    payload_json jsonb not null default '{{}}'::jsonb
                )
                '''
            )

    async def persist_event(self, event: NovaEvent) -> None:
        if event.type == EventType.SAFETY_BLOCK and self._persist_safety:
            await self.persist_safety_event(event)
        elif event.type in {EventType.CHAT_MESSAGE, EventType.SAFE_OUTPUT} and self._persist_conversations:
            await self.persist_conversation_turn(event)

    async def persist_conversation_turn(self, event: NovaEvent) -> None:
        if self._pool is None:
            return
        payload = event.payload or {}
        viewer = payload.get("viewer") or {}
        role = "assistant" if event.type == EventType.SAFE_OUTPUT else "viewer"

        async with self._pool.acquire() as conn:
            await conn.execute(
                f'''
                insert into "{self._schema}".conversation_turns
                (id, event_type, source, trace_id, ts, role, viewer_id, viewer_name, text_content, payload_json)
                values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb)
                on conflict (id) do nothing
                ''',
                event.event_id,
                event.type.value,
                event.source,
                event.trace_id,
                event.timestamp,
                role,
                viewer.get("viewer_id"),
                viewer.get("username"),
                payload.get("text"),
                json.dumps(payload, ensure_ascii=False, default=str),
            )

    async def persist_safety_event(self, event: NovaEvent) -> None:
        if self._pool is None:
            return
        payload = event.payload or {}
        async with self._pool.acquire() as conn:
            await conn.execute(
                f'''
                insert into "{self._schema}".safety_events
                (id, trace_id, ts, category, reason, blocked_text, payload_json)
                values ($1,$2,$3,$4,$5,$6,$7::jsonb)
                on conflict (id) do nothing
                ''',
                event.event_id,
                event.trace_id,
                event.timestamp,
                payload.get("category", "unknown"),
                payload.get("reason"),
                payload.get("blocked_text"),
                json.dumps(payload, ensure_ascii=False, default=str),
            )

    async def list_conversation_turns(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if self._pool is None:
            return []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f'''
                select id, event_type, source, trace_id, ts, role, viewer_id, viewer_name, text_content, payload_json
                from "{self._schema}".conversation_turns
                order by ts desc
                limit $1
                ''',
                limit,
            )
        return [dict(r) for r in rows]

    async def list_safety_events(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if self._pool is None:
            return []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f'''
                select id, trace_id, ts, category, reason, blocked_text, payload_json
                from "{self._schema}".safety_events
                order by ts desc
                limit $1
                ''',
                limit,
            )
        return [dict(r) for r in rows]
