"""
NOVA Kuaishou (快手) Adapter
============================
Kuaishou Live streaming platform adapter.

Protocol: WebSocket-based danmaku (similar to Douyin).
Authentication: Uses Kuaishou Open Platform OAuth2 token.
API Reference: https://open.kuaishou.com/
"""
from __future__ import annotations

import asyncio
import json
import logging
import struct
import time
import zlib
from typing import Any

import httpx

from packages.core.event_bus import EventBus
from packages.core.types import EventType, NovaEvent, Platform, Priority, ViewerProfile
from packages.platform.adapters import BaseAdapter

log = logging.getLogger("nova.platform.kuaishou")


# ─── Kuaishou WebSocket Protocol ─────────────────────────────────────────────

class KuaishouProto:
    """Kuaishou live WebSocket frame encoder/decoder."""

    # Frame types
    FRAME_AUTH      = 1
    FRAME_AUTH_ACK  = 2
    FRAME_HEARTBEAT = 3
    FRAME_DATA      = 4

    # Operation types
    OP_AUTH       = 1
    OP_HEARTBEAT  = 2
    OP_MESSAGE    = 3

    @staticmethod
    def pack_auth(token: str) -> bytes:
        """Pack authentication frame."""
        body = json.dumps({"token": token}).encode("utf-8")
        return KuaishouProto._pack_frame(KuaishouProto.FRAME_AUTH, body)

    @staticmethod
    def pack_heartbeat() -> bytes:
        """Pack heartbeat frame."""
        return KuaishouProto._pack_frame(KuaishouProto.FRAME_HEARTBEAT, b"")

    @staticmethod
    def _pack_frame(frame_type: int, body: bytes) -> bytes:
        """Pack a WebSocket frame: [header_size(1)][frame_type(1)][body_size(4)][body]"""
        header = struct.pack(">BBI", 6, frame_type, len(body))
        return header + body

    @staticmethod
    def unpack_frame(data: bytes) -> list[dict[str, Any]]:
        """Unpack one or more frames from a WebSocket message."""
        frames = []
        offset = 0
        while offset < len(data):
            if offset + 6 > len(data):
                break
            _, frame_type, body_size = struct.unpack_from(">BBI", data, offset)
            header_size = 6
            body = data[offset + header_size : offset + header_size + body_size]
            frames.append({"type": frame_type, "body": body})
            offset += header_size + body_size
        return frames


# ─── Kuaishou API Client ─────────────────────────────────────────────────────

class KuaishouAPIClient:
    """Kuaishou Open Platform REST API client."""

    BASE_URL = "https://open.kuaishou.com/openapi"

    def __init__(self, app_id: str, app_secret: str) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._client = httpx.AsyncClient(timeout=10.0)
        self._access_token: str = ""

    async def get_access_token(self) -> str:
        """Obtain access token via client credentials."""
        resp = await self._client.post(
            f"{self.BASE_URL}/oauth2/access_token",
            json={
                "app_id": self._app_id,
                "app_secret": self._app_secret,
                "grant_type": "client_credentials",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data.get("access_token", "")
        return self._access_token

    async def get_live_stream_url(self, live_room_id: str) -> str:
        """Get WebSocket URL for a live room."""
        if not self._access_token:
            await self.get_access_token()
        # Kuaishou uses a standard WS endpoint pattern
        return f"wss://live.kuaishou.com/ws/{live_room_id}"

    async def close(self) -> None:
        await self._client.aclose()


# ─── Kuaishou Adapter ────────────────────────────────────────────────────────

class KuaishouAdapter(BaseAdapter):
    """
    Kuaishou Live danmaku adapter.

    Supported message types:
      - 弹幕消息 → CHAT_MESSAGE
      - 礼物消息 → GIFT_RECEIVED
      - 进入直播间 → VIEWER_JOIN
      - 关注 → FOLLOW
      - 点赞 → LIKE
    """

    WS_URL = "wss://live.kuaishou.com/ws"

    def __init__(
        self,
        bus: EventBus,
        room_id: str = "",
        token: str = "",
        app_id: str = "",
        app_secret: str = "",
    ) -> None:
        super().__init__(bus, Platform.KUAISHOU)
        self._room_id = room_id
        self._token = token
        self._app_id = app_id
        self._app_secret = app_secret
        self._api = KuaishouAPIClient(app_id, app_secret) if app_id else None
        self._ws: Any = None
        self._heartbeat_task: asyncio.Task | None = None

    async def _connect(self) -> None:
        """Connect to Kuaishou Live WebSocket."""
        try:
            import websockets
        except ImportError:
            log.error("websockets not installed. Run: pip install websockets")
            return

        ws_url = self.WS_URL
        if self._api and self._room_id:
            try:
                ws_url = await self._api.get_live_stream_url(self._room_id)
            except Exception as e:
                log.warning("Failed to get WS URL from API, using default: %s", e)

        log.info("Kuaishou adapter connecting to room %s", self._room_id)
        try:
            self._ws = await websockets.connect(
                ws_url,
                additional_headers={"Authorization": f"Bearer {self._token}"} if self._token else {},
                ping_interval=20,
                ping_timeout=10,
            )

            # Send authentication frame
            if self._token:
                auth_frame = KuaishouProto.pack_auth(self._token)
                await self._ws.send(auth_frame)

            # Start heartbeat
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

            log.info("Kuaishou WS connected, room=%s", self._room_id)
            await self._recv_loop()
        except Exception as e:
            log.error("Kuaishou WS connection failed: %s", e)
            raise

    async def _disconnect(self) -> None:
        """Clean up connections."""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None
        if self._ws:
            await self._ws.close()
            self._ws = None
        if self._api:
            await self._api.close()

    async def _heartbeat_loop(self) -> None:
        """Send periodic heartbeat frames."""
        while True:
            await asyncio.sleep(25)
            if self._ws:
                try:
                    await self._ws.send(KuaishouProto.pack_heartbeat())
                except Exception:
                    break

    async def _recv_loop(self) -> None:
        """Receive and parse messages from WebSocket."""
        if not self._ws:
            return

        try:
            async for raw in self._ws:
                if isinstance(raw, bytes):
                    frames = KuaishouProto.unpack_frame(raw)
                    for frame in frames:
                        event = self._parse_frame(frame)
                        if event:
                            await self._bus.publish(event)
                elif isinstance(raw, str):
                    event = self._parse_json_message(raw)
                    if event:
                        await self._bus.publish(event)
        except websockets.ConnectionClosed:
            log.info("Kuaishou WS connection closed")
        except Exception as e:
            log.error("Kuaishou WS recv error: %s", e)

    def _parse_frame(self, frame: dict[str, Any]) -> NovaEvent | None:
        """Parse a binary frame into a NovaEvent."""
        frame_type = frame.get("type")
        body = frame.get("body", b"")

        if frame_type == KuaishouProto.FRAME_DATA and body:
            try:
                # Try decompress (zlib)
                try:
                    body = zlib.decompress(body)
                except zlib.error:
                    pass
                data = json.loads(body.decode("utf-8"))
                return self._parse_data_message(data)
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                log.debug("Failed to parse Kuaishou frame: %s", e)
        return None

    def _parse_json_message(self, raw: str) -> NovaEvent | None:
        """Parse a JSON text message."""
        try:
            data = json.loads(raw)
            return self._parse_data_message(data)
        except (json.JSONDecodeError, KeyError) as e:
            log.debug("Failed to parse Kuaishou JSON: %s", e)
            return None

    def _parse_data_message(self, data: dict[str, Any]) -> NovaEvent | None:
        """Parse a Kuaishou data message into the appropriate NovaEvent."""
        msg_type = data.get("type", data.get("cmd", ""))
        payload_data = data.get("data", data.get("payload", {}))

        if msg_type in ("DANMU", "danmu", "COMMENT"):
            return NovaEvent(
                type=EventType.CHAT_MESSAGE,
                payload={
                    "text": payload_data.get("content", ""),
                    "viewer": {
                        "viewer_id": str(payload_data.get("userId", "")),
                        "username": payload_data.get("userName", "anonymous"),
                        "platform": "kuaishou",
                    },
                },
                priority=Priority.NORMAL,
                source="kuaishou",
            )

        elif msg_type in ("GIFT", "gift"):
            return NovaEvent(
                type=EventType.GIFT_RECEIVED,
                payload={
                    "gift_name": payload_data.get("giftName", "礼物"),
                    "amount": float(payload_data.get("coinCount", 0)),
                    "viewer": {
                        "viewer_id": str(payload_data.get("userId", "")),
                        "username": payload_data.get("userName", "anonymous"),
                        "platform": "kuaishou",
                    },
                },
                priority=Priority.HIGH,
                source="kuaishou",
            )

        elif msg_type in ("ENTER", "enter", "JOIN"):
            return NovaEvent(
                type=EventType.VIEWER_JOIN,
                payload={
                    "viewer": {
                        "viewer_id": str(payload_data.get("userId", "")),
                        "username": payload_data.get("userName", "anonymous"),
                        "platform": "kuaishou",
                    },
                },
                priority=Priority.LOW,
                source="kuaishou",
            )

        elif msg_type in ("FOLLOW", "follow", "SUBSCRIBE"):
            return NovaEvent(
                type=EventType.FOLLOW,
                payload={
                    "viewer": {
                        "viewer_id": str(payload_data.get("userId", "")),
                        "username": payload_data.get("userName", "anonymous"),
                        "platform": "kuaishou",
                    },
                },
                priority=Priority.NORMAL,
                source="kuaishou",
            )

        return None

    def _parse_raw(self, raw: Any) -> NovaEvent | None:
        """Parse raw message (used by BaseAdapter._recv_loop)."""
        if isinstance(raw, str):
            return self._parse_json_message(raw)
        if isinstance(raw, bytes):
            frames = KuaishouProto.unpack_frame(raw)
            for frame in frames:
                return self._parse_frame(frame)
        return None
