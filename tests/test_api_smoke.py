"""FastAPI startup smoke tests."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from apps.nova_server.main import attach_runtime_routes, create_app
from packages.core.config import NovaSettings


ROOT = Path(__file__).resolve().parent.parent


def _smoke_settings() -> NovaSettings:
    return NovaSettings(
        port=8765,
        debug=False,
        character={"path": str(ROOT / "characters" / "nova_default.toml")},
        knowledge={"enabled": False},
        platforms=[],
        persistence={"enabled": False},
        auth={"enabled": False},
        observability={"tracing_enabled": False, "log_json": False, "log_level": "INFO"},
    )


def test_health_startup_smoke() -> None:
    app = attach_runtime_routes(create_app(settings_override=_smoke_settings()))

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert "bus" in payload
    assert "platforms" in payload
    assert payload["knowledge_base"]["enabled"] is False


def test_studio_dashboard_contains_control_plane() -> None:
    app = attach_runtime_routes(create_app(settings_override=_smoke_settings()))

    with TestClient(app) as client:
        response = client.get("/studio/")

    assert response.status_code == 200
    assert "Control" in response.text
    assert "Create Tenant" in response.text


def test_runtime_history_endpoints_with_fake_postgres_store() -> None:
    app = create_app(settings_override=_smoke_settings())
    app = attach_runtime_routes(app)

    class _FakeStore:
        def __init__(self):
            self.audit_calls = []
            self.tenant_updates = []
            self.role_updates = []
            self.revision_statuses = []

        async def list_conversation_turns(self, *, limit: int = 100, offset: int = 0, trace_id=None, session_id=None):
            return [{"id": "evt-1", "text_content": "hello"}]

        async def list_safety_events(self, *, limit: int = 100, offset: int = 0, trace_id=None, session_id=None, category=None):
            return [{"id": "evt-2", "category": "self_harm"}]

        async def list_runtime_sessions(self, *, limit: int = 100, offset: int = 0, status=None, role=None):
            return [{"id": "primary", "role": "cognitive"}]

        async def list_runtime_viewers(self, *, limit: int = 100, offset: int = 0, session_id=None, platform=None):
            return [{"id": "v1", "platform": "bilibili"}]

        async def list_audit_logs(self, *, limit: int = 100, offset: int = 0, action=None, resource_type=None):
            return [{"id": "audit-1", "action": "runtime_session_started"}]

        async def list_tenants(self, *, limit: int = 100, offset: int = 0):
            return [{"id": "tenant-1", "slug": "demo"}]

        async def list_roles(self, *, tenant_id=None, limit: int = 100, offset: int = 0):
            return [{"id": "role-1", "name": "admin"}]

        async def list_config_revisions(self, *, tenant_id=None, resource_type=None, resource_id=None, limit: int = 100, offset: int = 0):
            return [{"id": "rev-1", "resource_type": "runtime"}]

        async def create_tenant(self, tenant_id: str, name: str, slug: str, plan: str = "enterprise"):
            self.tenant_updates.append(("create", tenant_id, name, slug, plan))

        async def update_tenant(self, tenant_id: str, *, name=None, slug=None, status=None, plan=None):
            self.tenant_updates.append(("update", tenant_id, name, slug, status, plan))

        async def create_role(self, role_id: str, tenant_id: str, name: str, scope: str, description: str = ""):
            self.role_updates.append(("create", role_id, tenant_id, name, scope, description))

        async def update_role(self, role_id: str, *, name=None, scope=None, description=None):
            self.role_updates.append(("update", role_id, name, scope, description))

        async def create_config_revision(self, revision_id: str, tenant_id: str, resource_type: str, resource_id: str, revision_no: int, config_json: dict, status: str = "draft"):
            self.revision_statuses.append(("create", revision_id, status, revision_no, config_json))

        async def set_config_revision_status(self, revision_id: str, status: str):
            self.revision_statuses.append(("status", revision_id, status))

        async def write_audit_log(self, action: str, resource_type: str, detail: dict, resource_id: str = ""):
            self.audit_calls.append((action, resource_type, resource_id, detail))

        async def stop(self):
            return None

    app.state.nova.postgres_store = _FakeStore()

    with TestClient(app) as client:
        turns = client.get("/api/runtime/history/conversation?limit=10&offset=0&trace_id=trace-1&session_id=primary")
        safety = client.get("/api/runtime/history/safety?limit=10&offset=0&trace_id=trace-2&session_id=primary&category=self_harm")
        sessions = client.get("/api/runtime/storage/sessions?limit=10&offset=0&status=running&role=cognitive")
        viewers = client.get("/api/runtime/storage/viewers?limit=10&offset=0&session_id=primary&platform=bilibili")
        audit = client.get("/api/runtime/storage/audit?limit=10&offset=0&action=runtime_session_started&resource_type=runtime_session")
        tenants = client.get("/api/control/tenants?limit=10&offset=0")
        roles = client.get("/api/control/roles?tenant_id=tenant-1&limit=10&offset=0")
        revisions = client.get("/api/control/config-revisions?tenant_id=tenant-1&resource_type=runtime&resource_id=nova&limit=10&offset=0")
        create_tenant = client.post("/api/control/tenants", json={"id": "tenant-2", "name": "New Tenant", "slug": "new-tenant", "plan": "pro"})
        patch_tenant = client.patch("/api/control/tenants/tenant-2", json={"status": "suspended", "plan": "enterprise"})
        create_role = client.post("/api/control/roles", json={"id": "role-2", "tenant_id": "tenant-1", "name": "operator", "scope": "tenant"})
        patch_role = client.patch("/api/control/roles/role-2", json={"description": "Ops role"})
        create_revision = client.post("/api/control/config-revisions", json={"id": "rev-2", "tenant_id": "tenant-1", "resource_type": "runtime", "resource_id": "nova", "revision_no": 2, "config_json": {"foo": "bar"}})
        publish_revision = client.post("/api/control/config-revisions/rev-2/publish", json={"operator": "tester"})
        rollback_revision = client.post("/api/control/config-revisions/rev-2/rollback", json={"operator": "tester"})
        studio = client.get("/studio/api/status")

    assert turns.status_code == 200
    assert turns.json()["count"] == 1
    assert safety.status_code == 200
    assert safety.json()["count"] == 1
    assert sessions.status_code == 200
    assert sessions.json()["count"] == 1
    assert viewers.status_code == 200
    assert viewers.json()["count"] == 1
    assert audit.status_code == 200
    assert audit.json()["count"] == 1
    assert tenants.status_code == 200
    assert tenants.json()["count"] == 1
    assert roles.status_code == 200
    assert roles.json()["count"] == 1
    assert revisions.status_code == 200
    assert revisions.json()["count"] == 1
    assert create_tenant.status_code == 200
    assert patch_tenant.status_code == 200
    assert create_role.status_code == 200
    assert patch_role.status_code == 200
    assert create_revision.status_code == 200
    assert publish_revision.status_code == 200
    assert publish_revision.json()["revision_status"] == "published"
    assert rollback_revision.status_code == 200
    assert rollback_revision.json()["revision_status"] == "rolled_back"
    assert studio.status_code == 200
    assert "history_preview" in studio.json()
