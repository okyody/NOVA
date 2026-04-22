"""
NOVA Douyin (TikTok China) Adapter
====================================
Uses Douyin Live WebHook API to receive live stream events.

Douyin's live streaming API uses a webhook push model (vs Bilibili's
WebSocket). We run a lightweight HTTP server to receive push notifications
from the Douyin Live Open Platform.

Message types handled:
  ChatMessage    → CHAT_MESSAGE
  GiftMessage    → GIFT_RECEIVED (with combo merging)
  MemberMessage  → VIEWER_JOIN
  FollowMessage  → FOLLOW
  LiveStats      → LIVE_STATS

Note: Gift combo merging — same gift from same viewer within 2s is
merged into a single GIFT_RECEIVED with combined count.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from typing import Any

from packages.core.event_bus import EventBus
from packages.core.types import EventType, NovaEvent, Platform, Priority, ViewerProfile

from .adapters import BaseAdapter

log = logging.getLogger("nova.platform.douyin")


class DouyinAdapter(BaseAdapter):
    """
    Douyin Live webhook adapter.

    Runs a local HTTP server (on webhook_port) that receives POST
    callbacks from Douyin Live Open Platform.

    Requires:
      - Douyin developer credentials (app_id, app_secret)
      - Webhook URL configured in Douyin developer console
      - Signature verification for security
    """

    def __init__(
        self,
        bus: EventBus,
        room_id: str,
        app_id: str = "",
        app_secret: str = "",
        webhook_port: int = 8766,
    ) -> None:
        super().__init__(bus, Platform.DOUYIN)
        self._room_id = room_id
        self._app_id = app_id
        self._app_secret = app_secret
        self._webhook_port = webhook_port
        self._server: asyncio.Server | None = None
        self._gift_combos: dict[str, tuple[float, dict]] = {}  # key → (timestamp, data)
        self._combo_merge_window = 2.0  # seconds

    async def _connect(self) -> None:
        """Start webhook HTTP server."""
        self._server = await asyncio.start_server(
            self._handle_connection,
            host="0.0.0.0",
            port=self._webhook_port,
        )
        log.info("Douyin webhook server listening on port %d", self._webhook_port)

        # Start combo merger
        combo_task = asyncio.create_task(self._combo_merger_loop())

        try:
            async with self._server:
                await self._server.serve_forever()
        except asyncio.CancelledError:
            pass
        finally:
            combo_task.cancel()

    async def _disconnect(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle a single HTTP connection (minimal HTTP parser)."""
        try:
            # Read request line
            request_line = await reader.readline()
            if not request_line:
                writer.close()
                return

            parts = request_line.decode().strip().split()
            if len(parts) < 2:
                writer.close()
                return

            method, path = parts[0], parts[1]

            # Read headers
            headers = {}
            content_length = 0
            while True:
                line = await reader.readline()
                if line == b"\r\n" or line == b"\n":
                    break
                decoded = line.decode().strip()
                if ":" in decoded:
                    key, val = decoded.split(":", 1)
                    headers[key.strip().lower()] = val.strip()
                    if key.strip().lower() == "content-length":
                        content_length = int(val.strip())

            # Read body
            body = b""
            if content_length > 0:
                body = await reader.readexactly(content_length)

            # Handle the request
            import json

            if method == "POST" and path == "/webhook/douyin":
                try:
                    payload = json.loads(body.decode("utf-8"))
                    await self._process_webhook(payload)
                    response = "HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n"
                except Exception as exc:
                    log.error("Webhook processing error: %s", exc)
                    response = "HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n"
            elif method == "GET" and path == "/webhook/douyin/verify":
                # Douyin webhook verification challenge
                challenge = headers.get("x-verify-challenge", "")
                resp_body = json.dumps({"challenge": challenge})
                response = (
                    f"HTTP/1.1 200 OK\r\n"
                    f"Content-Type: application/json\r\n"
                    f"Content-Length: {len(resp_body)}\r\n\r\n"
                    f"{resp_body}"
                )
            else:
                response = "HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n"

            writer.write(response.encode())
            await writer.drain()
        except Exception as exc:
            log.debug("Connection handling error: %s", exc)
        finally:
            writer.close()

    async def _process_webhook(self, payload: dict) -> None:
        """Process a webhook push from Douyin."""
        event_type = payload.get("type", "")
        data = payload.get("data", {})

        event = self._parse_douyin_event(event_type, data)
        if event:
            # Gift combo merging
            if event.type == EventType.GIFT_RECEIVED:
                await self._handle_gift_combo(event)
            else:
                await self._emit(event)

    def _parse_douyin_event(self, event_type: str, data: dict) -> NovaEvent | None:
        """Convert Douyin webhook data to NovaEvent."""
        if event_type == "ChatMessage":
            viewer = self._make_viewer({
                "uid":      data.get("user_id", ""),
                "username": data.get("nickname", "匿名"),
                "is_member": data.get("fanclub", {}).get("is_member", False),
            })
            return NovaEvent(
                type=EventType.CHAT_MESSAGE,
                payload={
                    "text": data.get("content", ""),
                    "viewer": viewer.__dict__,
                },
                priority=Priority.NORMAL,
                source="douyin",
            )

        elif event_type == "GiftMessage":
            viewer = self._make_viewer(data.get("user", {}))
            amount = data.get("diamond_count", 0) / 10  # diamonds → CNY (approx 10:1)
            return NovaEvent(
                type=EventType.GIFT_RECEIVED,
                payload={
                    "gift_name": data.get("gift_name", ""),
                    "amount":    amount,
                    "count":     data.get("gift_count", 1),
                    "combo":     data.get("combo_count", 1),
                    "viewer":    viewer.__dict__,
                },
                priority=Priority.HIGH,
                source="douyin",
            )

        elif event_type == "MemberMessage":
            viewer = self._make_viewer({
                "uid":      data.get("user_id", ""),
                "username": data.get("nickname", "匿名"),
            })
            action = data.get("action", "")
            event_type_out = EventType.VIEWER_JOIN if action == "1" else EventType.FOLLOW
            return NovaEvent(
                type=event_type_out,
                payload={"viewer": viewer.__dict__},
                priority=Priority.LOW,
                source="douyin",
            )

        elif event_type == "FollowMessage":
            viewer = self._make_viewer({
                "uid":      data.get("user_id", ""),
                "username": data.get("nickname", "匿名"),
            })
            return NovaEvent(
                type=EventType.FOLLOW,
                payload={"viewer": viewer.__dict__},
                priority=Priority.NORMAL,
                source="douyin",
            )

        elif event_type == "LiveStats":
            return NovaEvent(
                type=EventType.LIVE_STATS,
                payload={
                    "online_count":  data.get("online_count", 0),
                    "watched_count": data.get("total_count", 0),
                },
                priority=Priority.LOW,
                source="douyin",
            )

        return None

    def _parse_raw(self, raw: Any) -> NovaEvent | None:
        # Not used — webhook model instead of polling
        return None

    # ── Gift combo merging ──────────────────────────────────────────────────

    async def _handle_gift_combo(self, event: NovaEvent) -> None:
        """Buffer gifts for combo merging."""
        viewer_id = event.payload.get("viewer", {}).get("viewer_id", "unknown")
        gift_name = event.payload.get("gift_name", "")
        combo_key = f"{viewer_id}:{gift_name}"

        now = time.monotonic()
        if combo_key in self._gift_combos:
            prev_time, prev_data = self._gift_combos[combo_key]
            if now - prev_time < self._combo_merge_window:
                # Merge: add count and amount
                prev_data["count"] += event.payload.get("count", 1)
                prev_data["amount"] += event.payload.get("amount", 0)
                prev_data["combo"] = event.payload.get("combo", 1)
                self._gift_combos[combo_key] = (now, prev_data)
                return  # don't emit yet

        # New combo or expired — store
        self._gift_combos[combo_key] = (now, dict(event.payload))

    async def _combo_merger_loop(self) -> None:
        """Flush expired gift combos periodically."""
        while True:
            await asyncio.sleep(1.0)
            now = time.monotonic()
            expired_keys = []
            for key, (ts, data) in self._gift_combos.items():
                if now - ts >= self._combo_merge_window:
                    expired_keys.append(key)

            for key in expired_keys:
                _, data = self._gift_combos.pop(key)
                await self._emit(NovaEvent(
                    type=EventType.GIFT_RECEIVED,
                    payload=data,
                    priority=Priority.HIGH,
                    source="douyin",
                ))
