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
        if "role_permissions" in query:
            return [{
                "role_id": "role-1",
                "permission_id": "perm-1",
                "code": "tenant.read",
                "resource": "tenant",
                "action": "read",
                "description": "Read tenants",
            }]
        if "permissions" in query:
            return [{
                "id": "perm-1",
                "code": "tenant.read",
                "resource": "tenant",
                "action": "read",
                "description": "Read tenants",
                "created_at": datetime.utcnow(),
            }]
        if "user_roles" in query:
            return [{
                "user_id": "user-1",
                "role_id": "role-1",
                "tenant_id": "tenant-1",
                "name": "admin",
                "scope": "tenant",
                "description": "Administrator",
            }]
        if "users" in query:
            return [{
                "id": "user-1",
                "tenant_id": "tenant-1",
                "email": "demo@example.com",
                "display_name": "Demo User",
                "status": "active",
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
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

    queries = "\n".join(call[0] for call in store._pool.calls)
    assert 'tenant_id = $1' in queries or 'tenant_id = any($1::text[])' in queries


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


@pytest.mark.asyncio
async def test_postgres_store_permissions_and_role_bindings():
    store = PostgresRuntimeStore("postgresql://test")
    store._pool = _FakePool()

    await store.create_permission("perm-1", "tenant.read", "tenant", "read", "Read tenants")
    await store.set_role_permissions("role-1", ["perm-1"])
    permissions = await store.list_permissions(limit=10, offset=0, resource="tenant", action="read")
    role_permissions = await store.list_role_permissions(role_id="role-1", limit=10, offset=0)

    assert permissions[0]["id"] == "perm-1"
    assert role_permissions[0]["permission_id"] == "perm-1"


@pytest.mark.asyncio
async def test_postgres_store_users_roles_and_permission_lookup():
    store = PostgresRuntimeStore("postgresql://test")
    store._pool = _FakePool()

    await store.create_user("user-1", "tenant-1", "demo@example.com", "Demo User", "active")
    await store.update_user("user-1", status="suspended")
    await store.set_user_roles("user-1", ["role-1"])
    users = await store.list_users(limit=10, offset=0, tenant_id="tenant-1", status="active")
    user_roles = await store.list_user_roles(user_id="user-1", limit=10, offset=0)
    has_permission = await store.user_has_permission("user-1", "tenant.read")

    assert users[0]["id"] == "user-1"
    assert user_roles[0]["role_id"] == "role-1"
    assert has_permission is True


@pytest.mark.asyncio
async def test_postgres_store_builds_user_auth_context():
    store = PostgresRuntimeStore("postgresql://test")
    store._pool = _FakePool()

    context = await store.get_user_auth_context(user_id="user-1")

    assert context is not None
    assert context["user"]["id"] == "user-1"
    assert "tenant-1" in context["tenant_ids"]


@pytest.mark.asyncio
async def test_postgres_store_getters_support_tenant_scope():
    store = PostgresRuntimeStore("postgresql://test")
    store._pool = _FakePool()

    await store.list_tenants(tenant_ids=["tenant-1"], limit=10, offset=0)
    await store.list_roles(tenant_ids=["tenant-1"], limit=10, offset=0)
    await store.list_users(tenant_ids=["tenant-1"], limit=10, offset=0)
    await store.list_config_revisions(tenant_ids=["tenant-1"], limit=10, offset=0)
    await store.get_role("role-1", tenant_ids=["tenant-1"])
    await store.get_config_revision("rev-1", tenant_ids=["tenant-1"])

    queries = "\n".join(call[0] for call in store._pool.calls)
    assert "any(" in queries


@pytest.mark.asyncio
async def test_postgres_store_revision_state_machine():
    store = PostgresRuntimeStore("postgresql://test")
    store._pool = _FakePool()
    state = {"status": "draft"}

    async def _fake_get_config_revision(revision_id: str, *, tenant_ids=None):
        return {
            "id": revision_id,
            "tenant_id": "tenant-1",
            "resource_type": "runtime",
            "resource_id": "nova",
            "status": state["status"],
        }

    async def _fake_set_config_revision_status(revision_id: str, status: str):
        state["status"] = status

    store.get_config_revision = _fake_get_config_revision  # type: ignore[method-assign]
    store.set_config_revision_status = _fake_set_config_revision_status  # type: ignore[method-assign]
    original_execute = store._pool.conn.execute

    async def _execute_with_state(query, *args):
        if "set status = 'published'" in query:
            state["status"] = "published"
        if "set status = 'rolled_back'" in query:
            state["status"] = "rolled_back"
        await original_execute(query, *args)

    store._pool.conn.execute = _execute_with_state  # type: ignore[method-assign]

    published = await store.publish_config_revision("rev-1", tenant_ids=["tenant-1"])
    assert published["status"] == "published"
    assert state["status"] == "published"

    rolled_back = await store.rollback_config_revision("rev-1", tenant_ids=["tenant-1"])
    assert rolled_back["status"] == "rolled_back"
    assert state["status"] == "rolled_back"
