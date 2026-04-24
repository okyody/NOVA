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
        runtime_instance: str = "nova",
        session_id: str = "primary",
        persist_conversations: bool = True,
        persist_safety: bool = True,
    ) -> None:
        self._dsn = dsn
        self._schema = schema
        self._runtime_instance = runtime_instance
        self._session_id = session_id
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
                    runtime_instance text not null,
                    session_id text not null,
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
                    runtime_instance text not null,
                    session_id text not null,
                    trace_id text,
                    ts timestamptz not null,
                    category text not null,
                    reason text,
                    blocked_text text,
                    payload_json jsonb not null default '{{}}'::jsonb
                )
                '''
            )
            await conn.execute(
                f'''
                create table if not exists "{self._schema}".runtime_sessions (
                    id text primary key,
                    runtime_instance text not null,
                    status text not null,
                    role text not null,
                    character text,
                    llm_model text,
                    started_at timestamptz not null,
                    stopped_at timestamptz,
                    last_activity_at timestamptz,
                    summary_json jsonb not null default '{{}}'::jsonb
                )
                '''
            )
            await conn.execute(
                f'''
                create table if not exists "{self._schema}".runtime_viewers (
                    id text primary key,
                    runtime_instance text not null,
                    session_id text not null,
                    platform text,
                    username text,
                    is_member boolean not null default false,
                    gift_total double precision not null default 0,
                    interaction_count integer not null default 0,
                    last_seen_at timestamptz,
                    last_event_type text,
                    last_message text,
                    payload_json jsonb not null default '{{}}'::jsonb
                )
                '''
            )
            await conn.execute(
                f'''
                create table if not exists "{self._schema}".audit_logs (
                    id text primary key,
                    runtime_instance text not null,
                    ts timestamptz not null,
                    action text not null,
                    resource_type text not null,
                    resource_id text,
                    detail_json jsonb not null default '{{}}'::jsonb
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
                (id, runtime_instance, session_id, event_type, source, trace_id, ts, role, viewer_id, viewer_name, text_content, payload_json)
                values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12::jsonb)
                on conflict (id) do nothing
                ''',
                event.event_id,
                self._runtime_instance,
                self._session_id,
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
                (id, runtime_instance, session_id, trace_id, ts, category, reason, blocked_text, payload_json)
                values ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb)
                on conflict (id) do nothing
                ''',
                event.event_id,
                self._runtime_instance,
                self._session_id,
                event.trace_id,
                event.timestamp,
                payload.get("category", "unknown"),
                payload.get("reason"),
                payload.get("blocked_text"),
                json.dumps(payload, ensure_ascii=False, default=str),
            )

    async def upsert_runtime_session(self, summary: dict[str, Any], *, status: str = "running") -> None:
        if self._pool is None:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                f'''
                insert into "{self._schema}".runtime_sessions
                (id, runtime_instance, status, role, character, llm_model, started_at, last_activity_at, summary_json)
                values ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb)
                on conflict (id) do update set
                    status = excluded.status,
                    last_activity_at = excluded.last_activity_at,
                    summary_json = excluded.summary_json
                ''',
                self._session_id,
                self._runtime_instance,
                status,
                summary.get("role", "unknown"),
                summary.get("character"),
                summary.get("llm_model"),
                summary.get("started_at", datetime.utcnow()),
                summary.get("last_activity_at", datetime.utcnow()),
                json.dumps(summary, ensure_ascii=False, default=str),
            )

    async def stop_runtime_session(self) -> None:
        if self._pool is None:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                f'''
                update "{self._schema}".runtime_sessions
                set status = 'stopped', stopped_at = $1
                where id = $2
                ''',
                datetime.utcnow(),
                self._session_id,
            )

    async def upsert_runtime_viewer(self, viewer_id: str, payload: dict[str, Any]) -> None:
        if self._pool is None:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                f'''
                insert into "{self._schema}".runtime_viewers
                (id, runtime_instance, session_id, platform, username, is_member, gift_total, interaction_count, last_seen_at, last_event_type, last_message, payload_json)
                values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12::jsonb)
                on conflict (id) do update set
                    username = excluded.username,
                    is_member = excluded.is_member,
                    gift_total = excluded.gift_total,
                    interaction_count = excluded.interaction_count,
                    last_seen_at = excluded.last_seen_at,
                    last_event_type = excluded.last_event_type,
                    last_message = excluded.last_message,
                    payload_json = excluded.payload_json
                ''',
                viewer_id,
                self._runtime_instance,
                self._session_id,
                payload.get("platform"),
                payload.get("username"),
                bool(payload.get("is_member", False)),
                float(payload.get("gift_total", 0.0)),
                int(payload.get("interaction_count", 0)),
                payload.get("last_seen_at", datetime.utcnow()),
                payload.get("last_event_type"),
                payload.get("last_message"),
                json.dumps(payload, ensure_ascii=False, default=str),
            )

    async def write_audit_log(self, action: str, resource_type: str, detail: dict[str, Any], resource_id: str = "") -> None:
        if self._pool is None:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                f'''
                insert into "{self._schema}".audit_logs
                (id, runtime_instance, ts, action, resource_type, resource_id, detail_json)
                values ($1,$2,$3,$4,$5,$6,$7::jsonb)
                ''',
                f"audit-{datetime.utcnow().timestamp()}",
                self._runtime_instance,
                datetime.utcnow(),
                action,
                resource_type,
                resource_id,
                json.dumps(detail, ensure_ascii=False, default=str),
            )

    async def list_conversation_turns(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        trace_id: str | None = None,
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if self._pool is None:
            return []
        clauses = []
        args: list[Any] = []
        if trace_id:
            args.append(trace_id)
            clauses.append(f"trace_id = ${len(args)}")
        if session_id:
            args.append(session_id)
            clauses.append(f"session_id = ${len(args)}")
        where_sql = f"where {' and '.join(clauses)}" if clauses else ""
        args.extend([limit, offset])
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f'''
                select id, runtime_instance, session_id, event_type, source, trace_id, ts, role, viewer_id, viewer_name, text_content, payload_json
                from "{self._schema}".conversation_turns
                {where_sql}
                order by ts desc
                limit ${len(args)-1} offset ${len(args)}
                ''',
                *args,
            )
        return [dict(r) for r in rows]

    async def list_safety_events(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        trace_id: str | None = None,
        session_id: str | None = None,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        if self._pool is None:
            return []
        clauses = []
        args: list[Any] = []
        if trace_id:
            args.append(trace_id)
            clauses.append(f"trace_id = ${len(args)}")
        if session_id:
            args.append(session_id)
            clauses.append(f"session_id = ${len(args)}")
        if category:
            args.append(category)
            clauses.append(f"category = ${len(args)}")
        where_sql = f"where {' and '.join(clauses)}" if clauses else ""
        args.extend([limit, offset])
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f'''
                select id, runtime_instance, session_id, trace_id, ts, category, reason, blocked_text, payload_json
                from "{self._schema}".safety_events
                {where_sql}
                order by ts desc
                limit ${len(args)-1} offset ${len(args)}
                ''',
                *args,
            )
        return [dict(r) for r in rows]
