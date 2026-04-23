"""
NOVA WeChat Channel Adapter
============================
WeChat Channel (视频号) live streaming adapter.

Authentication: WeChat Open Platform OAuth2.
API Reference: https://developers.weixin.qq.com/doc/channels/
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from typing import Any

import httpx

from packages.core.event_bus import EventBus
from packages.core.types import EventType, NovaEvent, Platform, Priority, ViewerProfile
from packages.platform.adapters import BaseAdapter

log = logging.getLogger("nova.platform.wechat")


# ─── WeChat API Client ───────────────────────────────────────────────────────

class WeChatAPIClient:
    """WeChat Open Platform API client."""

    BASE_URL = "https://api.weixin.qq.com"

    def __init__(self, app_id: str, app_secret: str) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._client = httpx.AsyncClient(timeout=10.0)
        self._access_token: str = ""
        self._token_expires: float = 0.0

    async def get_access_token(self) -> str:
        """Obtain access token (cached until expiry)."""
        if self._access_token and time.time() < self._token_expires:
            return self._access_token

        resp = await self._client.get(
            f"{self.BASE_URL}/cgi-bin/token",
            params={
                "grant_type": "client_credential",
                "appid": self._app_id,
                "secret": self._app_secret,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data.get("access_token", "")
        expires_in = data.get("expires_in", 7200)
        self._token_expires = time.time() + expires_in - 300  # 5min buffer
        log.info("WeChat access token obtained (expires in %ds)", expires_in)
        return self._access_token

    async def get_live_room_info(self, room_id: str) -> dict[str, Any]:
        """Get live room information."""
        token = await self.get_access_token()
        resp = await self._client.post(
            f"{self.BASE_URL}/channels/ec/live/room/get",
            params={"access_token": token},
            json={"roomId": room_id},
        )
        resp.raise_for_status()
        return resp.json()

    async def get_live_comments(self, room_id: str, cursor: str = "") -> dict[str, Any]:
        """Fetch live room comments (polling mode)."""
        token = await self.get_access_token()
        resp = await self._client.post(
            f"{self.BASE_URL}/channels/ec/live/comment/get",
            params={"access_token": token},
            json={"roomId": room_id, "cursor": cursor, "limit": 50},
        )
        resp.raise_for_status()
        return resp.json()

    async def verify_callback_signature(self, body: str, signature: str, timestamp: str, nonce: str) -> bool:
        """Verify WeChat callback signature for webhook mode."""
        token = self._app_id  # In webhook mode, app_id serves as verification token
        parts = sorted([token, timestamp, nonce, body])
        sha1 = hashlib.sha1("".join(parts).encode("utf-8")).hexdigest()
        return hmac_compare(sha1, signature)

    async def close(self) -> None:
        await self._client.aclose()


def hmac_compare(a: str, b: str) -> bool:
    """Constant-time string comparison."""
    import hmac as _hmac
    return _hmac.compare_digest(a, b)


# ─── WeChat Adapter ──────────────────────────────────────────────────────────

class WeChatAdapter(BaseAdapter):
    """
    WeChat Channel Live adapter.

    Two modes:
      1. Polling mode (default): Periodically fetch comments via REST API
      2. Webhook mode: Receive callbacks from WeChat server (requires public URL)

    Supported message types:
      - 评论 → CHAT_MESSAGE
      - 打赏 → GIFT_RECEIVED
      - 进入直播间 → VIEWER_JOIN
      - 关注 → FOLLOW
      - 点赞 → LIKE
    """

    POLL_INTERVAL_S = 2.0  # Poll every 2 seconds

    def __init__(
        self,
        bus: EventBus,
        room_id: str = "",
        app_id: str = "",
        app_secret: str = "",
        mode: str = "polling",  # "polling" or "webhook"
    ) -> None:
        super().__init__(bus, Platform.WECHAT)
        self._room_id = room_id
        self._app_id = app_id
        self._app_secret = app_secret
        self._mode = mode
        self._api = WeChatAPIClient(app_id, app_secret) if app_id else None
        self._poll_task: asyncio.Task | None = None
        self._cursor: str = ""
        self._last_comment_ids: set[str] = set()

    async def _connect(self) -> None:
        """Start message ingestion."""
        if self._mode == "polling" and self._api:
            self._poll_task = asyncio.create_task(self._poll_loop())
            log.info("WeChat adapter started in polling mode (room=%s)", self._room_id)
        elif self._mode == "webhook":
            log.info("WeChat adapter started in webhook mode (room=%s)", self._room_id)
            # Webhook mode: external HTTP callback handler publishes events
        else:
            log.warning("WeChat adapter: no API credentials, running in stub mode")

    async def _disconnect(self) -> None:
        """Clean up connections."""
        if self._poll_task:
            self._poll_task.cancel()
            self._poll_task = None
        if self._api:
            await self._api.close()

    async def _poll_loop(self) -> None:
        """Poll WeChat API for new comments."""
        while True:
            try:
                await asyncio.sleep(self.POLL_INTERVAL_S)
                if not self._api or not self._room_id:
                    continue

                result = await self._api.get_live_comments(self._room_id, self._cursor)
                comments = result.get("comments", [])
                self._cursor = result.get("next_cursor", self._cursor)

                for comment in comments:
                    comment_id = comment.get("commentId", "")
                    if comment_id in self._last_comment_ids:
                        continue
                    self._last_comment_ids.add(comment_id)

                    event = self._parse_comment(comment)
                    if event:
                        await self._bus.publish(event)

                # Keep only recent IDs to prevent memory growth
                if len(self._last_comment_ids) > 1000:
                    self._last_comment_ids = set(list(self._last_comment_ids)[-500:])

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("WeChat poll error: %s", e)
                await asyncio.sleep(5)

    def _parse_comment(self, comment: dict[str, Any]) -> NovaEvent | None:
        """Parse a WeChat comment into a NovaEvent."""
        msg_type = comment.get("type", "comment")

        viewer_info = {
            "viewer_id": str(comment.get("userId", "")),
            "username": comment.get("nickname", "anonymous"),
            "platform": "wechat",
        }

        if msg_type == "comment":
            return NovaEvent(
                type=EventType.CHAT_MESSAGE,
                payload={
                    "text": comment.get("content", ""),
                    "viewer": viewer_info,
                },
                priority=Priority.NORMAL,
                source="wechat",
            )

        elif msg_type == "gift":
            return NovaEvent(
                type=EventType.GIFT_RECEIVED,
                payload={
                    "gift_name": comment.get("giftName", "打赏"),
                    "amount": float(comment.get("amount", 0)),
                    "viewer": viewer_info,
                },
                priority=Priority.HIGH,
                source="wechat",
            )

        elif msg_type == "enter":
            return NovaEvent(
                type=EventType.VIEWER_JOIN,
                payload={"viewer": viewer_info},
                priority=Priority.LOW,
                source="wechat",
            )

        elif msg_type == "follow":
            return NovaEvent(
                type=EventType.FOLLOW,
                payload={"viewer": viewer_info},
                priority=Priority.NORMAL,
                source="wechat",
            )

        elif msg_type == "like":
            return NovaEvent(
                type=EventType.CHAT_MESSAGE,
                payload={
                    "text": "[点赞]",
                    "viewer": viewer_info,
                    "is_like": True,
                },
                priority=Priority.LOW,
                source="wechat",
            )

        return None

    def handle_webhook(self, data: dict[str, Any]) -> NovaEvent | None:
        """
        Handle a WeChat webhook callback.
        Called by the HTTP handler when in webhook mode.

        Args:
            data: Parsed JSON body from WeChat callback
        """
        msg_type = data.get("MsgType", data.get("type", ""))
        event_map = {
            "comment": EventType.CHAT_MESSAGE,
            "gift": EventType.GIFT_RECEIVED,
            "enter": EventType.VIEWER_JOIN,
            "follow": EventType.FOLLOW,
            "like": EventType.CHAT_MESSAGE,
        }
        event_type = event_map.get(msg_type)
        if not event_type:
            return None

        return NovaEvent(
            type=event_type,
            payload={
                "text": data.get("Content", data.get("content", "")),
                "gift_name": data.get("GiftName", data.get("giftName", "")),
                "amount": float(data.get("Amount", data.get("amount", 0))),
                "viewer": {
                    "viewer_id": str(data.get("FromUserName", data.get("userId", ""))),
                    "username": data.get("Nickname", data.get("nickname", "anonymous")),
                    "platform": "wechat",
                },
            },
            priority=Priority.NORMAL if msg_type != "gift" else Priority.HIGH,
            source="wechat",
        )

    def _parse_raw(self, raw: Any) -> NovaEvent | None:
        """Parse raw message (for BaseAdapter compatibility)."""
        if isinstance(raw, dict):
            return self._parse_comment(raw)
        if isinstance(raw, str):
            try:
                return self._parse_comment(json.loads(raw))
            except json.JSONDecodeError:
                return None
        return None
