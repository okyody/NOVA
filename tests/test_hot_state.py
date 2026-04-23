from __future__ import annotations

import pytest

from packages.ops.hot_state import (
    HotStateSync,
    InMemoryHotStateBackend,
    RuntimeSessionState,
    RuntimeStateProjector,
)


@pytest.mark.asyncio
async def test_hot_state_sync_publishes_runtime_context_and_emotion() -> None:
    backend = InMemoryHotStateBackend()
    sync = HotStateSync(backend, interval_s=60, ttl_s=30, runtime_name="test")
    sync.bind(
        runtime=lambda: {"queue_depth": 3},
        context=lambda: {"heat_level": "normal", "chat_rate": 1.0},
        emotion=lambda: {"label": "happy", "valence": 0.4},
        platforms=lambda: {"bilibili": {"running": True}},
    )

    await sync.publish_once()

    assert (await backend.get_json("test:runtime")) == {"queue_depth": 3}
    assert (await backend.get_json("test:context"))["heat_level"] == "normal"
    assert (await backend.get_json("test:emotion"))["label"] == "happy"
    assert (await backend.get_json("test:platforms"))["bilibili"]["running"] is True


def test_platform_configs_missing_required_fields_are_rejected() -> None:
    from packages.platform.manager import PlatformManager

    ok, reason = PlatformManager.validate_config({"platform": "youtube", "live_chat_id": ""})
    assert ok is False
    assert "api_key" in reason


@pytest.mark.asyncio
async def test_runtime_state_projector_tracks_viewer_and_summary() -> None:
    backend = InMemoryHotStateBackend()
    projector = RuntimeStateProjector(backend, runtime_name="nova", ttl_s=300)

    await projector.project_event(
        "platform.chat_message",
        {
            "text": "hello",
            "viewer": {
                "viewer_id": "v1",
                "username": "alice",
                "platform": "bilibili",
                "is_member": True,
            },
        },
    )
    await projector.project_event(
        "platform.gift_received",
        {
            "amount": 12.5,
            "viewer": {
                "viewer_id": "v1",
                "username": "alice",
                "platform": "bilibili",
                "is_member": True,
            },
        },
    )
    await projector.project_event("cognitive.safe_output", {"text": "thanks!"})

    summary = await projector.get_summary()
    viewer = await projector.get_viewer("v1")

    assert summary is not None
    assert summary["message_count"] == 1
    assert summary["gift_count"] == 1
    assert summary["output_count"] == 1
    assert viewer is not None
    assert viewer["interaction_count"] == 2
    assert viewer["gift_total"] == 12.5
    assert viewer["last_event_type"] == "platform.gift_received"


@pytest.mark.asyncio
async def test_runtime_session_state_tracks_session_viewers_and_idempotency() -> None:
    backend = InMemoryHotStateBackend()
    session = RuntimeSessionState(
        backend,
        runtime_name="nova",
        session_id="primary",
        ttl_s=300,
        idempotency_ttl_s=300,
    )

    await session.mark_session_started({"character": "Nova", "llm_model": "qwen2.5:14b"})
    accepted = await session.project_event(
        "evt-1",
        "platform.chat_message",
        {
            "text": "hello",
            "viewer": {
                "viewer_id": "v1",
                "username": "alice",
                "platform": "bilibili",
            },
        },
    )
    duplicate = await session.project_event(
        "evt-1",
        "platform.chat_message",
        {
            "text": "hello again",
            "viewer": {
                "viewer_id": "v1",
                "username": "alice",
                "platform": "bilibili",
            },
        },
    )

    state = await session.get_session()
    viewer = await session.get_viewer("v1")
    viewers = await session.list_viewers()

    assert accepted is True
    assert duplicate is False
    assert state is not None
    assert state["message_count"] == 1
    assert viewer is not None
    assert viewer["interaction_count"] == 1
    assert "nova:sessions:primary:viewers:v1" in viewers


@pytest.mark.asyncio
async def test_runtime_session_state_lists_sessions() -> None:
    backend = InMemoryHotStateBackend()
    session_a = RuntimeSessionState(backend, runtime_name="nova", session_id="a")
    session_b = RuntimeSessionState(backend, runtime_name="nova", session_id="b")

    await session_a.mark_session_started({"character": "Nova"})
    await session_b.mark_session_started({"character": "Nova-2"})

    sessions = await session_a.list_sessions()
    assert "nova:sessions:a" in sessions
    assert "nova:sessions:b" in sessions
