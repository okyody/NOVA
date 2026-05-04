from __future__ import annotations

import os

import windows_launcher


def test_studio_url_uses_default_port(monkeypatch) -> None:
    monkeypatch.delenv("NOVA_PORT", raising=False)
    assert windows_launcher._studio_url() == "http://127.0.0.1:8765/studio/"


def test_studio_url_uses_env_port(monkeypatch) -> None:
    monkeypatch.setenv("NOVA_PORT", "9123")
    assert windows_launcher._studio_url() == "http://127.0.0.1:9123/studio/"


def test_should_auto_open_studio_respects_env_true(monkeypatch) -> None:
    monkeypatch.setenv("NOVA_AUTO_OPEN_STUDIO", "true")
    assert windows_launcher._should_auto_open_studio() is True


def test_should_auto_open_studio_respects_env_false(monkeypatch) -> None:
    monkeypatch.setenv("NOVA_AUTO_OPEN_STUDIO", "false")
    assert windows_launcher._should_auto_open_studio() is False


def test_should_embed_studio_respects_env_true(monkeypatch) -> None:
    monkeypatch.setenv("NOVA_EMBED_STUDIO", "true")
    assert windows_launcher._should_embed_studio() is True


def test_should_embed_studio_respects_env_false(monkeypatch) -> None:
    monkeypatch.setenv("NOVA_EMBED_STUDIO", "false")
    assert windows_launcher._should_embed_studio() is False
