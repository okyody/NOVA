"""Productization smoke tests for startup/config/deployment consistency."""

from __future__ import annotations

import importlib
from pathlib import Path

from packages.core.event_bus import EventBus
from packages.core.config import load_settings
from packages.platform.adapters import create_adapter


ROOT = Path(__file__).resolve().parent.parent


def test_server_entrypoint_importable() -> None:
    module = importlib.import_module("apps.nova_server.main")
    assert module is not None


def test_example_json_config_matches_settings_schema() -> None:
    settings = load_settings(ROOT / "nova.config.example.json")

    assert settings.llm.base_url == "http://localhost:11434/v1"
    assert settings.voice.backend == "edge_tts"
    assert settings.knowledge.embedding_backend == "ollama"
    assert settings.knowledge.vector_backend in {"memory", "qdrant"}
    assert settings.runtime.instance_name == "nova"
    assert settings.runtime.session_id == "primary"
    assert settings.runtime.event_bus_mode == "local"
    assert settings.runtime.event_bus_backend == "memory"
    assert settings.runtime.event_bus_max_retries == 5
    assert any(p.platform == "kuaishou" for p in settings.platforms)
    assert any(p.platform == "wechat" for p in settings.platforms)


def test_env_example_uses_nested_setting_names() -> None:
    env_text = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "NOVA_LLM__BASE_URL" in env_text
    assert "NOVA_KNOWLEDGE__ENABLED" in env_text
    assert "NOVA_PERSIST__BACKEND" in env_text
    assert "NOVA_AUTH__JWT_SECRET" in env_text


def test_docker_compose_uses_existing_monitoring_paths_and_nested_env_names() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "NOVA_LLM__BASE_URL" in compose
    assert "NOVA_KNOWLEDGE__ENABLED" in compose
    assert "./deploy/monitoring/grafana/dashboards" in compose
    assert "./deploy/monitoring/prometheus/prometheus.yml" in compose


def test_example_platform_configs_can_instantiate_adapters() -> None:
    settings = load_settings(ROOT / "nova.config.example.json")
    bus = EventBus(queue_size=32)

    for platform_cfg in settings.platforms:
        config = {
            "platform": platform_cfg.platform,
            "room_id": platform_cfg.room_id,
            "token": platform_cfg.token.get_secret_value() if platform_cfg.token.get_secret_value() else "",
            "uid": platform_cfg.uid,
            "app_id": platform_cfg.app_id,
            "app_secret": platform_cfg.app_secret.get_secret_value() if platform_cfg.app_secret.get_secret_value() else "",
            "live_chat_id": platform_cfg.live_chat_id,
            "api_key": platform_cfg.api_key.get_secret_value() if platform_cfg.api_key.get_secret_value() else "",
            "poll_interval": platform_cfg.poll_interval,
            "channel": platform_cfg.channel,
            "oauth_token": platform_cfg.oauth_token.get_secret_value() if platform_cfg.oauth_token.get_secret_value() else "",
            "username": platform_cfg.username,
            "webhook_port": platform_cfg.webhook_port,
            "mode": platform_cfg.mode,
        }
        adapter = create_adapter(platform_cfg.platform, bus, config)
        assert adapter is not None
