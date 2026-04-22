"""
NOVA Platform Adapters
======================
Unified interface for all streaming platforms.

Architecture:
  BaseAdapter defines the contract.
  Each platform subclass handles its own WebSocket protocol and normalizes
  events into NovaEvent format.

  The platform adapter is the ONLY place that knows about a specific platform.
  Everything downstream speaks NovaEvent.

Adding a new platform: subclass BaseAdapter, implement _connect() and _parse_raw().
"""
from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx

from packages.core.event_bus import EventBus
from packages.core.types import (
    EventType,
    NovaEvent,
    Platform,
    Priority,
    ViewerProfile,
)

log = logging.getLogger("nova.platform")


# ─── Base Adapter ─────────────────────────────────────────────────────────────

class BaseAdapter(ABC):
    """
    Abstract platform adapter.

    Subclasses implement:
      _connect()    → establish platform WebSocket / polling connection
      _disconnect() → clean up
      _parse_raw()  → raw platform message → NovaEvent | None

    The base class handles:
      - Automatic reconnection with exponential backoff
      - Event publishing to the bus
      - Connection health monitoring
    """

    def __init__(self, bus: EventBus, platform: Platform) -> None:
        self._bus      = bus
        self._platform = platform
        self._running  = False
        self._task: asyncio.Task | None = None
        self._reconnect_attempts = 0
        self._MAX_BACKOFF = 60

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(
            self._run_loop(), name=f"nova.platform.{self._platform.value}"
        )
        log.info("Platform adapter started: %s", self._platform.value)

    async def stop(self) -> None:
        self._running = False
        await self._disconnect()
        if self._task:
            self._task.cancel()

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await self._connect()
                self._reconnect_attempts = 0
            except Exception as exc:
                self._reconnect_attempts += 1
                backoff = min(2 ** self._reconnect_attempts, self._MAX_BACKOFF)
                log.warning(
                    "%s adapter error (attempt %d), retrying in %ds: %s",
                    self._platform.value, self._reconnect_attempts, backoff, exc
                )
                await asyncio.sleep(backoff)

    # ── Abstract interface ─────────────────────────────────────────────────

    @abstractmethod
    async def _connect(self) -> None:
        """Open connection and loop until disconnected."""

    @abstractmethod
    async def _disconnect(self) -> None:
        """Clean up connections."""

    @abstractmethod
    def _parse_raw(self, raw: Any) -> NovaEvent | None:
        """Parse a platform-specific message into a NovaEvent. Return None to skip."""

    # ── Helpers ────────────────────────────────────────────────────────────

    async def _emit(self, event: NovaEvent) -> None:
        await self._bus.publish(event)

    def _make_viewer(self, data: dict[str, Any]) -> ViewerProfile:
        return ViewerProfile(
            viewer_id=str(data.get("uid") or data.get("user_id") or "unknown"),
            platform=self._platform,
            username=data.get("uname") or data.get("username") or "anonymous",
            is_member=bool(data.get("is_member") or data.get("is_fans")),
            gift_total=float(data.get("gift_total") or 0),
        )


# ─── Bilibili Adapter ─────────────────────────────────────────────────────────

class BilibiliAdapter(BaseAdapter):
    """
    Bilibili Live danmaku adapter.

    Uses the public WebSocket API (wss://broadcastlv.chat.bilibili.com/sub).
    Authenticates with a user token for member detection.

    Supported message types:
      DANMU_MSG     → CHAT_MESSAGE
      SEND_GIFT     → GIFT_RECEIVED
      SUPER_CHAT_MESSAGE → SUPER_CHAT
      INTERACT_WORD (type=1) → VIEWER_JOIN
      WATCHED_CHANGE, ONLINE_RANK_COUNT → LIVE_STATS
    """

    WS_URL = "wss://broadcastlv.chat.bilibili.com/sub"

    def __init__(
        self,
        bus: EventBus,
        room_id: int,
        token: str = "",
        uid: int = 0,
    ) -> None:
        super().__init__(bus, Platform.BILIBILI)
        self._room_id = room_id
        self._token   = token
        self._uid     = uid
        self._ws      = None

    async def _connect(self) -> None:
        import websockets
        import json
        import struct
        import zlib

        async with websockets.connect(self.WS_URL) as ws:
            self._ws = ws
            log.info("Bilibili WS connected, room=%d", self._room_id)

            # Send auth packet
            auth = json.dumps({
                "uid":        self._uid,
                "roomid":     self._room_id,
                "protover":   3,
                "platform":   "web",
                "type":       2,
                "key":        self._token,
            }).encode()
            await ws.send(self._pack(auth, op=7))

            # Start heartbeat task
            hb_task = asyncio.create_task(self._heartbeat(ws))

            try:
                async for raw in ws:
                    await self._handle_packet(raw)
            finally:
                hb_task.cancel()

    async def _disconnect(self) -> None:
        if self._ws:
            await self._ws.close()

    async def _heartbeat(self, ws) -> None:
        """Send heartbeat every 30s to keep connection alive."""
        while True:
            await asyncio.sleep(30)
            await ws.send(self._pack(b"[object Object]", op=2))

    async def _handle_packet(self, data: bytes) -> None:
        """Parse binary packet, possibly containing multiple sub-packets."""
        import zlib
        import json

        offset = 0
        while offset < len(data):
            if offset + 16 > len(data):
                break
            pack_len = int.from_bytes(data[offset:offset+4], "big")
            header_len = int.from_bytes(data[offset+4:offset+6], "big")
            proto_ver = int.from_bytes(data[offset+6:offset+8], "big")
            op = int.from_bytes(data[offset+8:offset+12], "big")
            body = data[offset + header_len: offset + pack_len]

            if proto_ver == 2:
                # zlib compressed — recursively parse
                body = zlib.decompress(body)
                await self._handle_packet(body)
            elif op == 5:
                # Danmaku command
                try:
                    msg = json.loads(body.decode("utf-8"))
                    event = self._parse_raw(msg)
                    if event:
                        await self._emit(event)
                except Exception as exc:
                    log.debug("Parse error: %s", exc)

            offset += pack_len

    def _parse_raw(self, msg: dict) -> NovaEvent | None:
        cmd = msg.get("cmd", "")
        data = msg.get("data", {})
        info = msg.get("info", [])

        if cmd == "DANMU_MSG":
            # info[1] = message text, info[2] = [uid, uname, ...]
            text = info[1] if len(info) > 1 else ""
            user_info = info[2] if len(info) > 2 else {}
            viewer = self._make_viewer({
                "uid":   user_info[0] if user_info else 0,
                "uname": user_info[1] if len(user_info) > 1 else "匿名",
                "is_member": bool(user_info[3] if len(user_info) > 3 else 0),
            })
            return NovaEvent(
                type=EventType.CHAT_MESSAGE,
                payload={"text": text, "viewer": viewer.__dict__},
                priority=Priority.NORMAL,
                source="bilibili",
            )

        elif cmd == "SEND_GIFT":
            viewer = self._make_viewer(data)
            return NovaEvent(
                type=EventType.GIFT_RECEIVED,
                payload={
                    "gift_name": data.get("giftName", ""),
                    "amount":    data.get("total_coin", 0) / 1000,   # milli-bean to yuan
                    "count":     data.get("num", 1),
                    "viewer":    viewer.__dict__,
                },
                priority=Priority.HIGH,
                source="bilibili",
            )

        elif cmd == "SUPER_CHAT_MESSAGE":
            viewer = self._make_viewer(data.get("user_info", {}))
            return NovaEvent(
                type=EventType.SUPER_CHAT,
                payload={
                    "text":   data.get("message", ""),
                    "amount": float(data.get("price", 0)),
                    "viewer": viewer.__dict__,
                },
                priority=Priority.CRITICAL,
                source="bilibili",
            )

        elif cmd == "INTERACT_WORD" and data.get("msg_type") == 1:
            viewer = self._make_viewer(data)
            return NovaEvent(
                type=EventType.VIEWER_JOIN,
                payload={"viewer": viewer.__dict__},
                priority=Priority.LOW,
                source="bilibili",
            )

        elif cmd in ("WATCHED_CHANGE", "ONLINE_RANK_COUNT"):
            return NovaEvent(
                type=EventType.LIVE_STATS,
                payload={
                    "watched_count": data.get("num", 0),
                    "online_count":  data.get("count", 0),
                },
                priority=Priority.LOW,
                source="bilibili",
            )

        return None

    @staticmethod
    def _pack(body: bytes, op: int) -> bytes:
        """Pack a bilibili WebSocket frame."""
        import struct
        header_len = 16
        total_len = header_len + len(body)
        return struct.pack(">IHHII", total_len, header_len, 1, op, 1) + body


# ─── Adapter registry ─────────────────────────────────────────────────────────

def create_adapter(platform: Platform, bus: EventBus, config: dict) -> BaseAdapter:
    """Factory — returns the correct adapter for a given platform."""
    if platform == Platform.BILIBILI:
        return BilibiliAdapter(
            bus=bus,
            room_id=int(config["room_id"]),
            token=config.get("token", ""),
            uid=int(config.get("uid", 0)),
        )
    elif platform == Platform.DOUYIN:
        from .douyin_adapter import DouyinAdapter
        return DouyinAdapter(
            bus=bus,
            room_id=str(config["room_id"]),
            app_id=config.get("app_id", ""),
            app_secret=config.get("app_secret", ""),
            webhook_port=int(config.get("webhook_port", 8766)),
        )
    elif platform == Platform.YOUTUBE:
        from .youtube_adapter import YouTubeAdapter
        return YouTubeAdapter(
            bus=bus,
            live_chat_id=config["live_chat_id"],
            api_key=config.get("api_key", ""),
            poll_interval=float(config.get("poll_interval", 3.0)),
        )
    elif platform == Platform.TWITCH:
        from .twitch_adapter import TwitchAdapter
        return TwitchAdapter(
            bus=bus,
            channel=config["channel"],
            oauth_token=config.get("oauth_token", ""),
            username=config.get("username", "nova_bot"),
        )
    elif platform == Platform.TIKTOK:
        # Kuaishou uses TIKTOK platform enum for now
        from .kuaishou_adapter import KuaishouAdapter
        return KuaishouAdapter(
            bus=bus,
            room_id=str(config.get("room_id", "")),
            token=config.get("token", ""),
        )
    elif platform == Platform.LOCAL:
        # WeChat uses LOCAL platform enum for now
        from .wechat_adapter import WeChatAdapter
        return WeChatAdapter(
            bus=bus,
            room_id=str(config.get("room_id", "")),
            app_id=config.get("app_id", ""),
            app_secret=config.get("app_secret", ""),
        )
    raise NotImplementedError(f"No adapter for platform: {platform.value}")
