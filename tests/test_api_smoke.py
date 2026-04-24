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


def test_runtime_history_endpoints_with_fake_postgres_store() -> None:
    app = create_app(settings_override=_smoke_settings())
    app = attach_runtime_routes(app)

    class _FakeStore:
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

        async def stop(self):
            return None

    app.state.nova.postgres_store = _FakeStore()

    with TestClient(app) as client:
        turns = client.get("/api/runtime/history/conversation?limit=10&offset=0&trace_id=trace-1&session_id=primary")
        safety = client.get("/api/runtime/history/safety?limit=10&offset=0&trace_id=trace-2&session_id=primary&category=self_harm")
        sessions = client.get("/api/runtime/storage/sessions?limit=10&offset=0&status=running&role=cognitive")
        viewers = client.get("/api/runtime/storage/viewers?limit=10&offset=0&session_id=primary&platform=bilibili")
        audit = client.get("/api/runtime/storage/audit?limit=10&offset=0&action=runtime_session_started&resource_type=runtime_session")

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
