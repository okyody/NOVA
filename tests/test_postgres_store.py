from __future__ import annotations

from datetime import datetime

import pytest

from packages.core.types import EventType, NovaEvent, Priority
from packages.ops.postgres_store import PostgresRuntimeStore


class _FakeConn:
    def __init__(self, calls):
        self.calls = calls

    async def execute(self, query, *args):
        self.calls.append((query, args))

    async def fetch(self, query, *args):
        self.calls.append((query, args))
        if "conversation_turns" in query:
            return [{
                "id": "evt-1",
                "runtime_instance": "nova",
                "session_id": "primary",
                "event_type": "platform.chat_message",
                "source": "bilibili",
                "trace_id": "trace-1",
                "ts": datetime.utcnow(),
                "role": "viewer",
                "viewer_id": "v1",
                "viewer_name": "alice",
                "text_content": "hello",
                "payload_json": {},
            }]
        if "safety_events" in query:
            return [{
                "id": "evt-2",
                "runtime_instance": "nova",
                "session_id": "primary",
                "trace_id": "trace-2",
                "ts": datetime.utcnow(),
                "category": "self_harm",
                "reason": "pattern",
                "blocked_text": "x",
                "payload_json": {},
            }]
        if "runtime_sessions" in query:
            return [{
                "id": "primary",
                "runtime_instance": "nova",
                "status": "running",
                "role": "cognitive",
                "character": "Nova",
                "llm_model": "qwen",
                "started_at": datetime.utcnow(),
                "stopped_at": None,
                "last_activity_at": datetime.utcnow(),
                "summary_json": {},
            }]
        if "runtime_viewers" in query:
            return [{
                "id": "v1",
                "runtime_instance": "nova",
                "session_id": "primary",
                "platform": "bilibili",
                "username": "alice",
                "is_member": False,
                "gift_total": 0.0,
                "interaction_count": 1,
                "last_seen_at": datetime.utcnow(),
                "last_event_type": "platform.chat_message",
                "last_message": "hello",
                "payload_json": {},
            }]
        if "roles" in query:
            return [{
                "id": "role-1",
                "tenant_id": "tenant-1",
                "name": "admin",
                "scope": "tenant",
                "description": "Administrator",
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }]
        if "config_revisions" in query:
            return [{
                "id": "rev-1",
                "tenant_id": "tenant-1",
                "resource_type": "runtime",
                "resource_id": "nova",
                "revision_no": 1,
                "status": "draft",
                "config_json": {},
                "created_at": datetime.utcnow(),
            }]
        if "tenants" in query:
            return [{
                "id": "tenant-1",
                "name": "Demo Tenant",
                "slug": "demo",
                "status": "active",
                "plan": "enterprise",
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }]
        return [{
            "id": "audit-1",
            "runtime_instance": "nova",
            "ts": datetime.utcnow(),
            "action": "runtime_session_started",
            "resource_type": "runtime_session",
            "resource_id": "primary",
            "detail_json": {},
        }]


class _Acquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakePool:
    def __init__(self):
        self.calls = []
        self.conn = _FakeConn(self.calls)

    def acquire(self):
        return _Acquire(self.conn)

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_postgres_store_persists_conversation_turn():
    store = PostgresRuntimeStore("postgresql://test")
    store._pool = _FakePool()

    event = NovaEvent(
        type=EventType.CHAT_MESSAGE,
        payload={"text": "hello", "viewer": {"viewer_id": "v1", "username": "alice"}},
        priority=Priority.NORMAL,
        source="bilibili",
        trace_id="trace-1",
        timestamp=datetime.utcnow(),
    )
    await store.persist_conversation_turn(event)

    assert len(store._pool.calls) == 1
    assert "conversation_turns" in store._pool.calls[0][0]


@pytest.mark.asyncio
async def test_postgres_store_persists_safety_event():
    store = PostgresRuntimeStore("postgresql://test")
    store._pool = _FakePool()

    event = NovaEvent(
        type=EventType.SAFETY_BLOCK,
        payload={"category": "self_harm", "reason": "pattern", "blocked_text": "x"},
        priority=Priority.HIGH,
        source="safety_guard",
        trace_id="trace-2",
        timestamp=datetime.utcnow(),
    )
    await store.persist_safety_event(event)

    assert len(store._pool.calls) == 1
    assert "safety_events" in store._pool.calls[0][0]


@pytest.mark.asyncio
async def test_postgres_store_lists_conversation_turns():
    store = PostgresRuntimeStore("postgresql://test")
    store._pool = _FakePool()

    rows = await store.list_conversation_turns(limit=10)
    assert rows[0]["id"] == "evt-1"


@pytest.mark.asyncio
async def test_postgres_store_lists_conversation_turns_with_filters():
    store = PostgresRuntimeStore("postgresql://test")
    store._pool = _FakePool()

    rows = await store.list_conversation_turns(limit=10, offset=5, trace_id="trace-1", session_id="primary")
    assert rows[0]["session_id"] == "primary"


@pytest.mark.asyncio
async def test_postgres_store_lists_safety_events():
    store = PostgresRuntimeStore("postgresql://test")
    store._pool = _FakePool()

    rows = await store.list_safety_events(limit=10)
    assert rows[0]["id"] == "evt-2"


@pytest.mark.asyncio
async def test_postgres_store_upserts_session_and_viewer_and_audit():
    store = PostgresRuntimeStore("postgresql://test", runtime_instance="nova", session_id="primary")
    store._pool = _FakePool()

    await store.upsert_runtime_session({"role": "cognitive", "character": "Nova", "llm_model": "qwen"})
    await store.upsert_runtime_viewer("v1", {"platform": "bilibili", "username": "alice", "interaction_count": 1})
    await store.write_audit_log("runtime_session_started", "runtime_session", {"session_id": "primary"}, resource_id="primary")

    assert len(store._pool.calls) == 3


@pytest.mark.asyncio
async def test_postgres_store_lists_runtime_sessions():
    store = PostgresRuntimeStore("postgresql://test")
    store._pool = _FakePool()
    rows = await store.list_runtime_sessions(limit=10, offset=0, status="running", role="cognitive")
    assert rows[0]["id"] == "primary"


@pytest.mark.asyncio
async def test_postgres_store_lists_runtime_viewers():
    store = PostgresRuntimeStore("postgresql://test")
    store._pool = _FakePool()
    rows = await store.list_runtime_viewers(limit=10, offset=0, session_id="primary", platform="bilibili")
    assert rows[0]["id"] == "v1"


@pytest.mark.asyncio
async def test_postgres_store_lists_audit_logs():
    store = PostgresRuntimeStore("postgresql://test")
    store._pool = _FakePool()
    rows = await store.list_audit_logs(limit=10, offset=0, action="runtime_session_started", resource_type="runtime_session")
    assert rows[0]["id"] == "audit-1"


@pytest.mark.asyncio
async def test_postgres_store_creates_and_lists_tenants_roles_and_revisions():
    store = PostgresRuntimeStore("postgresql://test")
    store._pool = _FakePool()

    await store.create_tenant("tenant-1", "Demo Tenant", "demo")
    await store.create_role("role-1", "tenant-1", "admin", "tenant", "Administrator")
    await store.create_config_revision("rev-1", "tenant-1", "runtime", "nova", 1, {"foo": "bar"})

    tenants = await store.list_tenants(limit=10, offset=0)
    roles = await store.list_roles(tenant_id="tenant-1", limit=10, offset=0)
    revisions = await store.list_config_revisions(tenant_id="tenant-1", resource_type="runtime", resource_id="nova", limit=10, offset=0)

    assert tenants[0]["id"] == "tenant-1"
    assert roles[0]["id"] == "role-1"
    assert revisions[0]["id"] == "rev-1"


@pytest.mark.asyncio
async def test_postgres_store_updates_control_plane_records():
    store = PostgresRuntimeStore("postgresql://test")
    store._pool = _FakePool()

    await store.update_tenant("tenant-1", status="suspended", plan="pro")
    await store.update_role("role-1", description="Updated role")
    await store.update_config_revision("rev-1", status="draft", config_json={"foo": "bar"})
    await store.set_config_revision_status("rev-1", "published")

    queries = "\n".join(call[0] for call in store._pool.calls)
    assert 'update "public".tenants' in queries
    assert 'update "public".roles' in queries
    assert 'update "public".config_revisions' in queries
