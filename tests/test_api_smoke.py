"""FastAPI startup smoke tests."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from apps.nova_server.main import attach_runtime_routes, create_app
from packages.core.config import NovaSettings, PlatformConfig


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


def _auth_smoke_settings() -> NovaSettings:
    return NovaSettings(
        port=8765,
        debug=False,
        character={"path": str(ROOT / "characters" / "nova_default.toml")},
        knowledge={"enabled": False},
        platforms=[],
        persistence={"enabled": False},
        auth={"enabled": True, "jwt_secret": "test-secret-with-safe-length-32chars"},
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


def test_runtime_diagnostics_and_inject_event() -> None:
    app = attach_runtime_routes(create_app(settings_override=_smoke_settings()))

    with TestClient(app) as client:
        diagnostics = client.get("/api/runtime/diagnostics")
        overview = client.get("/api/runtime/overview")
        metrics = client.get("/api/runtime/metrics-snapshot")
        injected = client.post(
            "/api/runtime/inject-event",
            json={
                "event_type": "CHAT_MESSAGE",
                "text": "hello from smoke",
                "viewer_id": "smoke-user",
                "username": "SmokeUser",
            },
        )
        workers = client.get("/api/runtime/workers")
        studio = client.get("/studio/api/status")

    assert diagnostics.status_code == 200
    assert diagnostics.json()["status"] == "ok"
    assert "workers" in diagnostics.json()
    assert "issues" in diagnostics.json()
    assert overview.status_code == 200
    assert overview.json()["status"] == "ok"
    assert "history" in overview.json()
    assert "hot_state_summary" in overview.json()
    assert "issues" in overview.json()
    assert metrics.status_code == 200
    assert metrics.json()["status"] == "ok"
    assert "metrics" in metrics.json()
    assert "bus" in metrics.json()["metrics"]
    assert injected.status_code == 200
    assert injected.json()["event_type"] == "platform.chat_message"
    assert workers.status_code == 200
    assert workers.json()["workers"]["api"] is True
    assert studio.status_code == 200
    assert "workers" in studio.json()
    assert studio.json()["workers"]["api"] is True


def test_ai_eval_and_routing_preview() -> None:
    app = attach_runtime_routes(create_app(settings_override=_smoke_settings()))

    with TestClient(app) as client:
        eval_report = client.get("/api/ai/eval/latest")
        routing = client.post(
            "/api/ai/routing-preview",
            json={"text": "我今天有点难过", "emotion": "sad"},
        )

    assert eval_report.status_code == 200
    assert eval_report.json()["status"] == "ok"
    assert eval_report.json()["report"]["total"] >= 1
    assert routing.status_code == 200
    assert routing.json()["status"] == "ok"
    assert routing.json()["intent"]["intent"] == "emotion"


def test_platform_catalog_config_status_and_test_event() -> None:
    settings = _smoke_settings()
    settings.platforms = [
        PlatformConfig(
            platform="douyin",
            room_id="acceptance-room",
            app_id="demo-app",
            app_secret="demo-secret",
            webhook_port=8766,
            mode="webhook",
        )
    ]
    app = attach_runtime_routes(create_app(settings_override=settings))

    with TestClient(app) as client:
        catalog = client.get("/api/platforms/catalog")
        catalog_detail = client.get("/api/platforms/catalog/douyin")
        templates = client.get("/api/platforms/templates")
        extension_spec = client.get("/api/platforms/extensions/spec")
        library_catalog = client.get("/api/library/catalog")
        library_character = client.get("/api/library/templates/characters")
        library_character_detail = client.get("/api/library/templates/characters/energetic_host")
        extension_docs = client.get("/api/library/extensions/docs")
        extension_doc_detail = client.get("/api/library/extensions/docs/ADAPTER_SDK")
        config = client.get("/api/platforms/config")
        filtered_config = client.get("/api/platforms/config", params={"platform": "douyin"})
        validate = client.post("/api/platforms/validate-config", json={"items": config.json()["items"]})
        status = client.get("/api/platforms/status")
        status_detail = client.get("/api/platforms/status/douyin")
        test_event = client.post(
            "/api/platforms/test-event",
            json={
                "platform": "douyin",
                "event_type": "CHAT_MESSAGE",
                "priority": "HIGH",
                "trace_id": "platform-smoke-trace",
                "viewer_id": "platform-smoke",
                "username": "PlatformSmoke",
                "text": "platform debug",
            },
        )

    assert catalog.status_code == 200
    assert catalog_detail.status_code == 200
    assert templates.status_code == 200
    assert extension_spec.status_code == 200
    assert library_catalog.status_code == 200
    assert library_character.status_code == 200
    assert library_character_detail.status_code == 200
    assert extension_docs.status_code == 200
    assert extension_doc_detail.status_code == 200
    assert config.status_code == 200
    assert filtered_config.status_code == 200
    assert validate.status_code == 200
    assert status.status_code == 200
    assert status_detail.status_code == 200
    assert test_event.status_code == 200
    assert test_event.json()["source"] == "douyin"
    assert test_event.json()["priority"] == "HIGH"
    assert test_event.json()["trace_id"] == "platform-smoke-trace"
    assert catalog_detail.json()["item"]["platform"] == "douyin"
    assert templates.json()["items"][0]["acceptance_checklist"]
    assert templates.json()["items"][0]["notes"]["supports_runtime_reload"] is True
    assert templates.json()["items"][0]["template"]["enabled"] is True
    assert templates.json()["items"][0]["template"]["priority"] == 100
    assert extension_spec.json()["adapter_contract"]["base_class"].endswith("BaseAdapter")
    assert extension_spec.json()["runtime_contract"]["status_detail_entrypoint"].endswith("{platform_name}")
    assert "characters" in library_catalog.json()["templates"]
    assert library_character_detail.json()["item"]["format"] == "toml"
    assert extension_doc_detail.json()["item"]["format"] == "md"
    assert filtered_config.json()["count"] == 1
    assert status.json()["summary"]["configured_count"] == 1
    assert "disabled_count" in status.json()["summary"]
    assert status_detail.json()["item"]["platform"] == "douyin"


def test_studio_dashboard_contains_control_plane() -> None:
    app = attach_runtime_routes(create_app(settings_override=_smoke_settings()))

    with TestClient(app) as client:
        response = client.get("/studio/")

    assert response.status_code == 200
    assert "Control" in response.text
    assert "Platforms" in response.text
    assert "Platform Detail" in response.text
    assert "Extension Entry Spec" in response.text
    assert "Template Library" in response.text
    assert "Extension Docs" in response.text
    assert "Create Tenant" in response.text
    assert "Save Config" in response.text
    assert "Load Capability Catalog" in response.text
    assert "RAG Enabled" in response.text
    assert "LLM provider" in response.text
    assert "output strategy" in response.text
    assert "Memory Enabled" in response.text
    assert "Center Map" in response.text
    assert "Runtime Center" in response.text
    assert "Control Center" in response.text
    assert "Config Center" in response.text
    assert "Platform Center" in response.text
    assert "Acceptance Center" in response.text
    assert "Quick Start" in response.text
    assert "Quick Actions" in response.text


def test_config_current_and_save_roundtrip(tmp_path) -> None:
    config_path = tmp_path / "nova.config.json"
    config_path.write_text(
        """
        {
          "port": 8765,
          "llm": {"base_url": "http://localhost:11434/v1", "model": "qwen2.5:14b"},
          "voice": {"backend": "edge_tts", "voice_id": "zh-CN-XiaoyiNeural"},
          "character": {"path": "characters/nova_default.toml"},
          "knowledge": {"enabled": false},
          "persistence": {"backend": "json", "redis_url": "redis://localhost:6379", "postgres_url": "postgresql://nova:nova@localhost:5432/nova"},
          "auth": {"enabled": false},
          "runtime": {"role": "all"}
        }
        """,
        encoding="utf-8",
    )
    settings = _smoke_settings()
    settings.config_path = config_path
    app = attach_runtime_routes(create_app(settings_override=settings))

    with TestClient(app) as client:
        capabilities = client.get("/api/capabilities/catalog")
        current = client.get("/api/config/current")
        acceptance_export = client.get("/api/acceptance/export")
        saved = client.post(
            "/api/config/current",
            json={
                "config_json": {
                    "port": 8877,
                    "llm": {"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "qwen2.5:32b"},
                    "voice": {"backend": "edge_tts", "voice_id": "zh-CN-XiaoxiaoNeural", "fallback_chain": ["edge_tts", "azure"]},
                    "character": {"path": str(ROOT / "characters" / "nova_default.toml")},
                    "knowledge": {
                        "enabled": True,
                        "embedding_backend": "ollama",
                        "embedding_model": "nomic-embed-text",
                        "vector_backend": "memory",
                    },
                    "memory": {"enabled": False, "working_memory_maxlen": 64},
                    "persistence": {
                        "backend": "redis",
                        "redis_url": "redis://localhost:6379",
                        "postgres_url": "postgresql://nova:nova@localhost:5432/nova",
                    },
                    "auth": {"enabled": True},
                    "avatar": {"enabled": True, "driver": "web", "output_strategy": "voice_and_avatar"},
                    "runtime": {"role": "api"},
                }
            },
        )

    assert capabilities.status_code == 200
    assert capabilities.json()["llm_providers"][0]["id"] == "ollama"
    assert acceptance_export.status_code == 200
    assert acceptance_export.json()["status"] == "ok"
    assert current.status_code == 200
    assert current.json()["config_path"] == str(config_path)
    assert current.json()["config_json"]["llm"]["model"] == "qwen2.5:14b"
    assert saved.status_code == 200
    assert saved.json()["status"] == "saved"
    assert saved.json()["restart_required"] is True
    persisted = config_path.read_text(encoding="utf-8")
    assert '"model": "qwen2.5:32b"' in persisted
    assert '"output_strategy": "voice_and_avatar"' in persisted


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

        async def list_audit_logs(self, *, limit: int = 100, offset: int = 0, action=None, resource_type=None, resource_id=None):
            return [{"id": "audit-1", "action": "runtime_session_started"}]

        async def get_tenant(self, tenant_id: str, *, tenant_ids=None):
            return {"id": tenant_id, "slug": "demo", "status": "active", "plan": "enterprise"}

        async def list_tenants(self, *, tenant_ids=None, limit: int = 100, offset: int = 0):
            return [{"id": "tenant-1", "slug": "demo"}]

        async def list_roles(self, *, tenant_id=None, tenant_ids=None, limit: int = 100, offset: int = 0):
            return [{"id": "role-1", "name": "admin"}]

        async def list_config_revisions(self, *, tenant_id=None, tenant_ids=None, resource_type=None, resource_id=None, status=None, limit: int = 100, offset: int = 0):
            return [{"id": "rev-1", "resource_type": "runtime"}]

        async def list_permissions(self, *, resource=None, action=None, limit: int = 100, offset: int = 0):
            return [{"id": "perm-1", "code": "tenant.read", "resource": "tenant", "action": "read"}]

        async def get_permission(self, permission_id: str):
            return {"id": permission_id, "code": "tenant.read", "resource": "tenant", "action": "read"}

        async def list_role_permissions(self, *, role_id: str, limit: int = 100, offset: int = 0):
            return [{"role_id": role_id, "permission_id": "perm-1", "code": "tenant.read", "resource": "tenant", "action": "read"}]

        async def list_users(self, *, tenant_id=None, tenant_ids=None, status=None, limit: int = 100, offset: int = 0):
            return [{"id": "user-1", "tenant_id": "tenant-1", "email": "demo@example.com", "status": "active"}]

        async def list_user_roles(self, *, user_id: str, limit: int = 100, offset: int = 0):
            return [{"user_id": user_id, "role_id": "role-1", "name": "admin", "scope": "tenant"}]

        async def get_user(self, *, user_id: str | None = None, email: str | None = None, tenant_ids=None):
            return {
                "id": user_id or "user-1",
                "tenant_id": "tenant-1",
                "email": email or "demo@example.com",
                "display_name": "Demo User",
            }

        async def get_user_auth_context(self, *, user_id: str | None = None, email: str | None = None):
            return {
                "user": {
                    "id": user_id or "user-1",
                    "tenant_id": "tenant-1",
                    "email": email or "demo@example.com",
                    "display_name": "Demo User",
                },
                "roles": ["admin"],
                "permissions": ["*"],
                "tenant_ids": ["tenant-1"],
            }

        async def get_user(self, *, user_id: str | None = None, email: str | None = None, tenant_ids=None):
            return {"id": user_id or "user-1", "tenant_id": "tenant-1", "email": email or "demo@example.com", "display_name": "Demo User"}

        async def get_user_auth_context(self, *, user_id: str | None = None, email: str | None = None):
            return {
                "user": {"id": user_id or "user-1", "tenant_id": "tenant-1", "email": email or "demo@example.com", "display_name": "Demo User"},
                "roles": ["admin"],
                "permissions": ["*"],
                "tenant_ids": ["tenant-1"],
            }

        async def create_tenant(self, tenant_id: str, name: str, slug: str, plan: str = "enterprise"):
            self.tenant_updates.append(("create", tenant_id, name, slug, plan))

        async def update_tenant(self, tenant_id: str, *, name=None, slug=None, status=None, plan=None):
            self.tenant_updates.append(("update", tenant_id, name, slug, status, plan))

        async def create_role(self, role_id: str, tenant_id: str, name: str, scope: str, description: str = ""):
            self.role_updates.append(("create", role_id, tenant_id, name, scope, description))

        async def update_role(self, role_id: str, *, name=None, scope=None, description=None):
            self.role_updates.append(("update", role_id, name, scope, description))

        async def create_permission(self, permission_id: str, code: str, resource: str, action: str, description: str = ""):
            self.role_updates.append(("permission", permission_id, code, resource, action, description))

        async def set_role_permissions(self, role_id: str, permission_ids: list[str]):
            self.role_updates.append(("role_permissions", role_id, permission_ids))

        async def create_user(self, user_id: str, tenant_id: str, email: str, display_name: str = "", status: str = "active"):
            self.tenant_updates.append(("user_create", user_id, tenant_id, email, display_name, status))

        async def update_user(self, user_id: str, *, email=None, display_name=None, status=None):
            self.tenant_updates.append(("user_update", user_id, email, display_name, status))

        async def set_user_roles(self, user_id: str, role_ids: list[str]):
            self.role_updates.append(("user_roles", user_id, role_ids))

        async def user_has_permission(self, user_id: str, permission_code: str):
            return permission_code in {
                "tenant.read", "tenant.write", "role.read", "role.write",
                "permission.read", "permission.write",
                "config_revision.read", "config_revision.write",
                "config_revision.publish", "config_revision.rollback",
                "user.read", "user.write",
            }

        async def create_config_revision(self, revision_id: str, tenant_id: str, resource_type: str, resource_id: str, revision_no: int, config_json: dict, status: str = "draft", changed_by=None, change_note=None):
            self.revision_statuses.append(("create", revision_id, status, revision_no, config_json, changed_by, change_note))

        async def set_config_revision_status(self, revision_id: str, status: str):
            self.revision_statuses.append(("status", revision_id, status))

        async def get_role(self, role_id: str, *, tenant_ids=None):
            return {"id": role_id, "tenant_id": "tenant-1", "name": "admin", "scope": "tenant"}

        async def get_config_revision(self, revision_id: str, *, tenant_ids=None):
            return {"id": revision_id, "tenant_id": "tenant-1", "status": "draft", "resource_type": "runtime", "resource_id": "nova", "change_note": "", "changed_by": None}

        async def get_effective_config_revision(self, *, tenant_id=None, tenant_ids=None, resource_type: str, resource_id: str):
            return {"id": "rev-published", "tenant_id": tenant_id or "tenant-1", "resource_type": resource_type, "resource_id": resource_id, "revision_no": 3, "status": "published"}

        async def publish_config_revision(self, revision_id: str, *, tenant_ids=None, changed_by=None, change_note=None):
            return {"id": revision_id, "status": "published", "changed_by": changed_by, "change_note": change_note}

        async def rollback_config_revision(self, revision_id: str, *, tenant_ids=None, changed_by=None, change_note=None):
            return {"id": revision_id, "status": "rolled_back", "changed_by": changed_by, "change_note": change_note}

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
        tenant_detail = client.get("/api/control/tenants/tenant-1")
        roles = client.get("/api/control/roles?tenant_id=tenant-1&limit=10&offset=0")
        role_detail = client.get("/api/control/roles/role-1")
        users = client.get("/api/control/users?tenant_id=tenant-1&limit=10&offset=0")
        user_detail = client.get("/api/control/users/user-1")
        revisions = client.get("/api/control/config-revisions?tenant_id=tenant-1&resource_type=runtime&resource_id=nova&limit=10&offset=0")
        effective_revision = client.get("/api/control/config-revisions/effective?tenant_id=tenant-1&resource_type=runtime&resource_id=nova")
        revision_detail = client.get("/api/control/config-revisions/rev-1")
        permissions = client.get("/api/control/permissions?limit=10&offset=0&resource=tenant&action=read")
        permission_detail = client.get("/api/control/permissions/perm-1")
        control_audit = client.get("/api/control/audit?limit=10&offset=0&action=runtime_session_started&resource_type=runtime_session&resource_id=primary")
        role_permissions = client.get("/api/control/roles/role-1/permissions?limit=10&offset=0")
        user_roles = client.get("/api/control/users/user-1/roles?limit=10&offset=0")
        create_tenant = client.post("/api/control/tenants", json={"id": "tenant-2", "name": "New Tenant", "slug": "new-tenant", "plan": "pro"})
        patch_tenant = client.patch("/api/control/tenants/tenant-2", json={"status": "suspended", "plan": "enterprise"})
        create_role = client.post("/api/control/roles", json={"id": "role-2", "tenant_id": "tenant-1", "name": "operator", "scope": "tenant"})
        patch_role = client.patch("/api/control/roles/role-2", json={"description": "Ops role"})
        create_user = client.post("/api/control/users", json={"id": "user-2", "tenant_id": "tenant-1", "email": "u2@example.com", "display_name": "User Two"})
        patch_user = client.patch("/api/control/users/user-2", json={"status": "suspended"})
        create_permission = client.post("/api/control/permissions", json={"id": "perm-2", "code": "tenant.write", "resource": "tenant", "action": "write"})
        bind_permissions = client.put("/api/control/roles/role-2/permissions", json={"permission_ids": ["perm-1", "perm-2"]})
        bind_user_roles = client.put("/api/control/users/user-2/roles", json={"role_ids": ["role-1", "role-2"]})
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
    assert tenant_detail.status_code == 200
    assert roles.status_code == 200
    assert roles.json()["count"] == 1
    assert role_detail.status_code == 200
    assert users.status_code == 200
    assert users.json()["count"] == 1
    assert user_detail.status_code == 200
    assert revisions.status_code == 200
    assert revisions.json()["count"] == 1
    assert effective_revision.status_code == 200
    assert effective_revision.json()["item"]["status"] == "published"
    assert revision_detail.status_code == 200
    assert permissions.status_code == 200
    assert permissions.json()["count"] == 1
    assert permission_detail.status_code == 200
    assert control_audit.status_code == 200
    assert control_audit.json()["count"] == 1
    assert role_permissions.status_code == 200
    assert role_permissions.json()["count"] == 1
    assert user_roles.status_code == 200
    assert user_roles.json()["count"] == 1
    assert create_tenant.status_code == 200
    assert patch_tenant.status_code == 200
    assert create_role.status_code == 200
    assert patch_role.status_code == 200
    assert create_user.status_code == 200
    assert patch_user.status_code == 200
    assert create_permission.status_code == 200
    assert bind_permissions.status_code == 200
    assert bind_permissions.json()["permission_count"] == 2
    assert bind_user_roles.status_code == 200
    assert bind_user_roles.json()["role_count"] == 2
    assert create_revision.status_code == 200
    assert publish_revision.status_code == 200
    assert publish_revision.json()["revision_status"] == "published"
    assert rollback_revision.status_code == 200
    assert rollback_revision.json()["revision_status"] == "rolled_back"
    assert studio.status_code == 200
    assert "history_preview" in studio.json()


def test_control_plane_permission_enforced_when_auth_enabled() -> None:
    app = create_app(settings_override=_auth_smoke_settings())
    app = attach_runtime_routes(app)

    class _AuthStore:
        async def get_user_auth_context(self, *, user_id: str | None = None, email: str | None = None):
            if user_id != "user-1":
                return None
            return {
                "user": {
                    "id": "user-1",
                    "tenant_id": "tenant-1",
                    "email": "demo@example.com",
                    "display_name": "Demo User",
                },
                "roles": ["viewer"],
                "permissions": ["tenant.read", "user.read"],
                "tenant_ids": ["tenant-1"],
            }

        async def get_user(self, *, user_id: str | None = None, email: str | None = None, tenant_ids=None):
            if user_id == "user-1":
                return {
                    "id": "user-1",
                    "tenant_id": "tenant-1",
                    "email": "demo@example.com",
                    "display_name": "Demo User",
                }
            return None

        async def user_has_permission(self, user_id: str, permission_code: str):
            return permission_code == "tenant.read"

        async def list_tenants(self, *, tenant_ids=None, limit: int = 100, offset: int = 0):
            return [{"id": "tenant-1", "slug": "demo"}]

        async def list_users(self, *, tenant_id=None, tenant_ids=None, status=None, limit: int = 100, offset: int = 0):
            return [{"id": "user-1", "tenant_id": "tenant-1", "email": "demo@example.com"}]

        async def stop(self):
            return None

    app.state.nova.postgres_store = _AuthStore()

    with TestClient(app) as client:
        token_response = client.post("/api/auth/token", json={"user_id": "user-1"})
        token = token_response.json()["access_token"]
        ok = client.get("/api/control/tenants", headers={"Authorization": f"Bearer {token}"})
        forbidden = client.get("/api/control/roles", headers={"Authorization": f"Bearer {token}"})
        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        wrong_tenant = client.get("/api/control/users?tenant_id=tenant-2", headers={"Authorization": f"Bearer {token}"})

    assert token_response.status_code == 200
    assert ok.status_code == 200
    assert forbidden.status_code == 403
    assert me.status_code == 200
    assert me.json()["user"]["id"] == "user-1"
    assert me.json()["user"]["tenant_id"] == "tenant-1"
    assert wrong_tenant.status_code == 403
