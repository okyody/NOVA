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
