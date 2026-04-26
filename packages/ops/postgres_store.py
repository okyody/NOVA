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
            await conn.execute(
                f'''
                create table if not exists "{self._schema}".tenants (
                    id text primary key,
                    name text not null,
                    slug text not null unique,
                    status text not null default 'active',
                    plan text not null default 'enterprise',
                    created_at timestamptz not null default now(),
                    updated_at timestamptz not null default now()
                )
                '''
            )
            await conn.execute(
                f'''
                create table if not exists "{self._schema}".roles (
                    id text primary key,
                    tenant_id text not null,
                    name text not null,
                    scope text not null,
                    description text,
                    created_at timestamptz not null default now(),
                    updated_at timestamptz not null default now()
                )
                '''
            )
            await conn.execute(
                f'''
                create table if not exists "{self._schema}".config_revisions (
                    id text primary key,
                    tenant_id text not null,
                    resource_type text not null,
                    resource_id text not null,
                    revision_no integer not null,
                    status text not null default 'draft',
                    config_json jsonb not null default '{{}}'::jsonb,
                    created_at timestamptz not null default now()
                )
                '''
            )
            await conn.execute(
                f'''
                create table if not exists "{self._schema}".permissions (
                    id text primary key,
                    code text not null unique,
                    resource text not null,
                    action text not null,
                    description text,
                    created_at timestamptz not null default now()
                )
                '''
            )
            await conn.execute(
                f'''
                create table if not exists "{self._schema}".role_permissions (
                    role_id text not null,
                    permission_id text not null,
                    created_at timestamptz not null default now(),
                    primary key (role_id, permission_id)
                )
                '''
            )
            await conn.execute(
                f'''
                create table if not exists "{self._schema}".users (
                    id text primary key,
                    tenant_id text not null,
                    email text not null,
                    display_name text,
                    status text not null default 'active',
                    created_at timestamptz not null default now(),
                    updated_at timestamptz not null default now()
                )
                '''
            )
            await conn.execute(
                f'''
                create table if not exists "{self._schema}".user_roles (
                    user_id text not null,
                    role_id text not null,
                    created_at timestamptz not null default now(),
                    primary key (user_id, role_id)
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

    async def list_runtime_sessions(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        status: str | None = None,
        role: str | None = None,
    ) -> list[dict[str, Any]]:
        if self._pool is None:
            return []
        clauses = []
        args: list[Any] = []
        if status:
            args.append(status)
            clauses.append(f"status = ${len(args)}")
        if role:
            args.append(role)
            clauses.append(f"role = ${len(args)}")
        where_sql = f"where {' and '.join(clauses)}" if clauses else ""
        args.extend([limit, offset])
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f'''
                select id, runtime_instance, status, role, character, llm_model, started_at, stopped_at, last_activity_at, summary_json
                from "{self._schema}".runtime_sessions
                {where_sql}
                order by started_at desc
                limit ${len(args)-1} offset ${len(args)}
                ''',
                *args,
            )
        return [dict(r) for r in rows]

    async def list_runtime_viewers(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        session_id: str | None = None,
        platform: str | None = None,
    ) -> list[dict[str, Any]]:
        if self._pool is None:
            return []
        clauses = []
        args: list[Any] = []
        if session_id:
            args.append(session_id)
            clauses.append(f"session_id = ${len(args)}")
        if platform:
            args.append(platform)
            clauses.append(f"platform = ${len(args)}")
        where_sql = f"where {' and '.join(clauses)}" if clauses else ""
        args.extend([limit, offset])
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f'''
                select id, runtime_instance, session_id, platform, username, is_member, gift_total, interaction_count, last_seen_at, last_event_type, last_message, payload_json
                from "{self._schema}".runtime_viewers
                {where_sql}
                order by last_seen_at desc nulls last
                limit ${len(args)-1} offset ${len(args)}
                ''',
                *args,
            )
        return [dict(r) for r in rows]

    async def list_audit_logs(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        action: str | None = None,
        resource_type: str | None = None,
    ) -> list[dict[str, Any]]:
        if self._pool is None:
            return []
        clauses = []
        args: list[Any] = []
        if action:
            args.append(action)
            clauses.append(f"action = ${len(args)}")
        if resource_type:
            args.append(resource_type)
            clauses.append(f"resource_type = ${len(args)}")
        where_sql = f"where {' and '.join(clauses)}" if clauses else ""
        args.extend([limit, offset])
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f'''
                select id, runtime_instance, ts, action, resource_type, resource_id, detail_json
                from "{self._schema}".audit_logs
                {where_sql}
                order by ts desc
                limit ${len(args)-1} offset ${len(args)}
                ''',
                *args,
            )
        return [dict(r) for r in rows]

    async def create_tenant(self, tenant_id: str, name: str, slug: str, plan: str = "enterprise") -> None:
        if self._pool is None:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                f'''
                insert into "{self._schema}".tenants (id, name, slug, status, plan)
                values ($1,$2,$3,'active',$4)
                on conflict (id) do update set
                    name = excluded.name,
                    slug = excluded.slug,
                    plan = excluded.plan,
                    updated_at = now()
                ''',
                tenant_id,
                name,
                slug,
                plan,
            )

    async def update_tenant(
        self,
        tenant_id: str,
        *,
        name: str | None = None,
        slug: str | None = None,
        status: str | None = None,
        plan: str | None = None,
    ) -> None:
        if self._pool is None:
            return
        assignments = []
        args: list[Any] = []
        for column, value in (
            ("name", name),
            ("slug", slug),
            ("status", status),
            ("plan", plan),
        ):
            if value is not None:
                args.append(value)
                assignments.append(f"{column} = ${len(args)}")
        if not assignments:
            return
        assignments.append("updated_at = now()")
        args.append(tenant_id)
        async with self._pool.acquire() as conn:
            await conn.execute(
                f'''
                update "{self._schema}".tenants
                set {", ".join(assignments)}
                where id = ${len(args)}
                ''',
                *args,
            )

    async def list_tenants(self, *, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        if self._pool is None:
            return []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f'''
                select id, name, slug, status, plan, created_at, updated_at
                from "{self._schema}".tenants
                order by created_at desc
                limit $1 offset $2
                ''',
                limit,
                offset,
            )
        return [dict(r) for r in rows]

    async def create_role(self, role_id: str, tenant_id: str, name: str, scope: str, description: str = "") -> None:
        if self._pool is None:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                f'''
                insert into "{self._schema}".roles (id, tenant_id, name, scope, description)
                values ($1,$2,$3,$4,$5)
                on conflict (id) do update set
                    name = excluded.name,
                    scope = excluded.scope,
                    description = excluded.description,
                    updated_at = now()
                ''',
                role_id,
                tenant_id,
                name,
                scope,
                description,
            )

    async def update_role(
        self,
        role_id: str,
        *,
        name: str | None = None,
        scope: str | None = None,
        description: str | None = None,
    ) -> None:
        if self._pool is None:
            return
        assignments = []
        args: list[Any] = []
        for column, value in (
            ("name", name),
            ("scope", scope),
            ("description", description),
        ):
            if value is not None:
                args.append(value)
                assignments.append(f"{column} = ${len(args)}")
        if not assignments:
            return
        assignments.append("updated_at = now()")
        args.append(role_id)
        async with self._pool.acquire() as conn:
            await conn.execute(
                f'''
                update "{self._schema}".roles
                set {", ".join(assignments)}
                where id = ${len(args)}
                ''',
                *args,
            )

    async def list_roles(self, *, tenant_id: str | None = None, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        if self._pool is None:
            return []
        clauses = []
        args: list[Any] = []
        if tenant_id:
            args.append(tenant_id)
            clauses.append(f"tenant_id = ${len(args)}")
        where_sql = f"where {' and '.join(clauses)}" if clauses else ""
        args.extend([limit, offset])
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f'''
                select id, tenant_id, name, scope, description, created_at, updated_at
                from "{self._schema}".roles
                {where_sql}
                order by created_at desc
                limit ${len(args)-1} offset ${len(args)}
                ''',
                *args,
            )
        return [dict(r) for r in rows]

    async def create_permission(
        self,
        permission_id: str,
        code: str,
        resource: str,
        action: str,
        description: str = "",
    ) -> None:
        if self._pool is None:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                f'''
                insert into "{self._schema}".permissions (id, code, resource, action, description)
                values ($1,$2,$3,$4,$5)
                on conflict (id) do update set
                    code = excluded.code,
                    resource = excluded.resource,
                    action = excluded.action,
                    description = excluded.description
                ''',
                permission_id,
                code,
                resource,
                action,
                description,
            )

    async def list_permissions(
        self,
        *,
        resource: str | None = None,
        action: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        if self._pool is None:
            return []
        clauses = []
        args: list[Any] = []
        if resource:
            args.append(resource)
            clauses.append(f"resource = ${len(args)}")
        if action:
            args.append(action)
            clauses.append(f"action = ${len(args)}")
        where_sql = f"where {' and '.join(clauses)}" if clauses else ""
        args.extend([limit, offset])
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f'''
                select id, code, resource, action, description, created_at
                from "{self._schema}".permissions
                {where_sql}
                order by created_at desc
                limit ${len(args)-1} offset ${len(args)}
                ''',
                *args,
            )
        return [dict(r) for r in rows]

    async def set_role_permissions(self, role_id: str, permission_ids: list[str]) -> None:
        if self._pool is None:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                f'''delete from "{self._schema}".role_permissions where role_id = $1''',
                role_id,
            )
            for permission_id in permission_ids:
                await conn.execute(
                    f'''
                    insert into "{self._schema}".role_permissions (role_id, permission_id)
                    values ($1,$2)
                    on conflict (role_id, permission_id) do nothing
                    ''',
                    role_id,
                    permission_id,
                )

    async def list_role_permissions(self, *, role_id: str, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        if self._pool is None:
            return []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f'''
                select rp.role_id, rp.permission_id, p.code, p.resource, p.action, p.description
                from "{self._schema}".role_permissions rp
                join "{self._schema}".permissions p on p.id = rp.permission_id
                where rp.role_id = $1
                order by p.code asc
                limit $2 offset $3
                ''',
                role_id,
                limit,
                offset,
            )
        return [dict(r) for r in rows]

    async def create_user(
        self,
        user_id: str,
        tenant_id: str,
        email: str,
        display_name: str = "",
        status: str = "active",
    ) -> None:
        if self._pool is None:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                f'''
                insert into "{self._schema}".users (id, tenant_id, email, display_name, status)
                values ($1,$2,$3,$4,$5)
                on conflict (id) do update set
                    tenant_id = excluded.tenant_id,
                    email = excluded.email,
                    display_name = excluded.display_name,
                    status = excluded.status,
                    updated_at = now()
                ''',
                user_id,
                tenant_id,
                email,
                display_name,
                status,
            )

    async def update_user(
        self,
        user_id: str,
        *,
        email: str | None = None,
        display_name: str | None = None,
        status: str | None = None,
    ) -> None:
        if self._pool is None:
            return
        assignments = []
        args: list[Any] = []
        for column, value in (
            ("email", email),
            ("display_name", display_name),
            ("status", status),
        ):
            if value is not None:
                args.append(value)
                assignments.append(f"{column} = ${len(args)}")
        if not assignments:
            return
        assignments.append("updated_at = now()")
        args.append(user_id)
        async with self._pool.acquire() as conn:
            await conn.execute(
                f'''
                update "{self._schema}".users
                set {", ".join(assignments)}
                where id = ${len(args)}
                ''',
                *args,
            )

    async def list_users(
        self,
        *,
        tenant_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        if self._pool is None:
            return []
        clauses = []
        args: list[Any] = []
        if tenant_id:
            args.append(tenant_id)
            clauses.append(f"tenant_id = ${len(args)}")
        if status:
            args.append(status)
            clauses.append(f"status = ${len(args)}")
        where_sql = f"where {' and '.join(clauses)}" if clauses else ""
        args.extend([limit, offset])
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f'''
                select id, tenant_id, email, display_name, status, created_at, updated_at
                from "{self._schema}".users
                {where_sql}
                order by created_at desc
                limit ${len(args)-1} offset ${len(args)}
                ''',
                *args,
            )
        return [dict(r) for r in rows]

    async def get_user(
        self,
        *,
        user_id: str | None = None,
        email: str | None = None,
    ) -> dict[str, Any] | None:
        if self._pool is None:
            return None
        if not user_id and not email:
            return None
        async with self._pool.acquire() as conn:
            if user_id:
                rows = await conn.fetch(
                    f'''
                    select id, tenant_id, email, display_name, status, created_at, updated_at
                    from "{self._schema}".users
                    where id = $1
                    limit 1
                    ''',
                    user_id,
                )
            else:
                rows = await conn.fetch(
                    f'''
                    select id, tenant_id, email, display_name, status, created_at, updated_at
                    from "{self._schema}".users
                    where email = $1
                    limit 1
                    ''',
                    email,
                )
        return dict(rows[0]) if rows else None

    async def set_user_roles(self, user_id: str, role_ids: list[str]) -> None:
        if self._pool is None:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                f'''delete from "{self._schema}".user_roles where user_id = $1''',
                user_id,
            )
            for role_id in role_ids:
                await conn.execute(
                    f'''
                    insert into "{self._schema}".user_roles (user_id, role_id)
                    values ($1,$2)
                    on conflict (user_id, role_id) do nothing
                    ''',
                    user_id,
                    role_id,
                )

    async def list_user_roles(self, *, user_id: str, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        if self._pool is None:
            return []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f'''
                select ur.user_id, ur.role_id, r.tenant_id, r.name, r.scope, r.description
                from "{self._schema}".user_roles ur
                join "{self._schema}".roles r on r.id = ur.role_id
                where ur.user_id = $1
                order by r.name asc
                limit $2 offset $3
                ''',
                user_id,
                limit,
                offset,
            )
        return [dict(r) for r in rows]

    async def user_has_permission(self, user_id: str, permission_code: str) -> bool:
        if self._pool is None:
            return False
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f'''
                select p.code
                from "{self._schema}".user_roles ur
                join "{self._schema}".role_permissions rp on rp.role_id = ur.role_id
                join "{self._schema}".permissions p on p.id = rp.permission_id
                where ur.user_id = $1 and p.code = $2
                limit 1
                ''',
                user_id,
                permission_code,
            )
        return bool(rows)

    async def get_user_auth_context(self, *, user_id: str | None = None, email: str | None = None) -> dict[str, Any] | None:
        user = await self.get_user(user_id=user_id, email=email)
        if not user:
            return None

        roles = await self.list_user_roles(user_id=user["id"], limit=200, offset=0)
        tenant_ids = sorted({user["tenant_id"], *[role.get("tenant_id") for role in roles if role.get("tenant_id")]})
        role_names = sorted({role.get("name") for role in roles if role.get("name")})

        permission_codes: set[str] = set()
        for role in roles:
            role_id = role.get("role_id")
            if role_id:
                role_permissions = await self.list_role_permissions(role_id=role_id, limit=200, offset=0)
                permission_codes.update(
                    permission.get("code")
                    for permission in role_permissions
                    if permission.get("code")
                )

        return {
            "user": user,
            "roles": role_names,
            "permissions": sorted(permission_codes),
            "tenant_ids": tenant_ids,
        }

    async def create_config_revision(
        self,
        revision_id: str,
        tenant_id: str,
        resource_type: str,
        resource_id: str,
        revision_no: int,
        config_json: dict[str, Any],
        status: str = "draft",
    ) -> None:
        if self._pool is None:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                f'''
                insert into "{self._schema}".config_revisions
                (id, tenant_id, resource_type, resource_id, revision_no, status, config_json)
                values ($1,$2,$3,$4,$5,$6,$7::jsonb)
                on conflict (id) do update set
                    status = excluded.status,
                    config_json = excluded.config_json
                ''',
                revision_id,
                tenant_id,
                resource_type,
                resource_id,
                revision_no,
                status,
                json.dumps(config_json, ensure_ascii=False, default=str),
            )

    async def update_config_revision(
        self,
        revision_id: str,
        *,
        config_json: dict[str, Any] | None = None,
        status: str | None = None,
    ) -> None:
        if self._pool is None:
            return
        assignments = []
        args: list[Any] = []
        if status is not None:
            args.append(status)
            assignments.append(f"status = ${len(args)}")
        if config_json is not None:
            args.append(json.dumps(config_json, ensure_ascii=False, default=str))
            assignments.append(f"config_json = ${len(args)}::jsonb")
        if not assignments:
            return
        args.append(revision_id)
        async with self._pool.acquire() as conn:
            await conn.execute(
                f'''
                update "{self._schema}".config_revisions
                set {", ".join(assignments)}
                where id = ${len(args)}
                ''',
                *args,
            )

    async def set_config_revision_status(self, revision_id: str, status: str) -> None:
        if self._pool is None:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                f'''
                update "{self._schema}".config_revisions
                set status = $1
                where id = $2
                ''',
                status,
                revision_id,
            )

    async def list_config_revisions(
        self,
        *,
        tenant_id: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        if self._pool is None:
            return []
        clauses = []
        args: list[Any] = []
        if tenant_id:
            args.append(tenant_id)
            clauses.append(f"tenant_id = ${len(args)}")
        if resource_type:
            args.append(resource_type)
            clauses.append(f"resource_type = ${len(args)}")
        if resource_id:
            args.append(resource_id)
            clauses.append(f"resource_id = ${len(args)}")
        where_sql = f"where {' and '.join(clauses)}" if clauses else ""
        args.extend([limit, offset])
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f'''
                select id, tenant_id, resource_type, resource_id, revision_no, status, config_json, created_at
                from "{self._schema}".config_revisions
                {where_sql}
                order by created_at desc
                limit ${len(args)-1} offset ${len(args)}
                ''',
                *args,
            )
        return [dict(r) for r in rows]
