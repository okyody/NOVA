"""
NOVA Twitch Adapter
====================
Uses Twitch IRC WebSocket (via twitchio-compatible protocol)
for real-time chat events.

Twitch chat is IRC-based, accessed via WebSocket.
Authentication uses OAuth tokens (refresh every 60 days).

Message types:
  PRIVMSG         → CHAT_MESSAGE
  USERNOTICE(sub) → VIEWER_JOIN
  USERNOTICE(raid)→ VIEWER_JOIN (with raid metadata)
  CHEERMOTE       → GIFT_RECEIVED (bits)
  SUBSCRIPTION    → SUPER_CHAT (paid subscription)
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from packages.core.event_bus import EventBus
from packages.core.types import EventType, NovaEvent, Platform, Priority, ViewerProfile

from .adapters import BaseAdapter

log = logging.getLogger("nova.platform.twitch")


class TwitchAdapter(BaseAdapter):
    """
    Twitch IRC WebSocket adapter.

    Connects to Twitch's chat IRC server over WebSocket.
    No external library dependency — uses raw IRC protocol
    for maximum control and minimal dependencies.
    """

    IRC_URL = "wss://irc-ws.chat.twitch.tv:443"

    def __init__(
        self,
        bus: EventBus,
        channel: str,
        oauth_token: str,
        username: str = "nova_bot",
    ) -> None:
        super().__init__(bus, Platform.TWITCH)
        self._channel = channel.lower()
        self._oauth = oauth_token
        self._username = username.lower()
        self._ws = None

    async def _connect(self) -> None:
        import websockets

        async with websockets.connect(self.IRC_URL) as ws:
            self._ws = ws
            log.info("Twitch IRC WS connected, channel=%s", self._channel)

            # Authenticate
            await ws.send(f"PASS oauth:{self._oauth}")
            await ws.send(f"NICK {self._username}")
            await ws.send(f"JOIN #{self._channel}")

            # Request capabilities for more metadata
            await ws.send("CAP REQ :twitch.tv/tags twitch.tv/commands")

            # Read loop
            async for raw in ws:
                lines = raw.split("\r\n")
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    await self._handle_irc(line, ws)

    async def _disconnect(self) -> None:
        if self._ws:
            await self._ws.close()

    async def _handle_irc(self, line: str, ws) -> None:
        """Parse and handle a single IRC message."""
        # Respond to PING
        if line.startswith("PING"):
            await ws.send(line.replace("PING", "PONG"))
            return

        # Parse IRC message with tags
        tags = {}
        if line.startswith("@"):
            tag_part, _, rest = line.partition(" ")
            tags = self._parse_tags(tag_part[1:])
            line = rest

        # Parse prefix and command
        if line.startswith(":"):
            prefix, _, line = line.partition(" ")

        parts = line.split(" ", 2)
        command = parts[0] if parts else ""

        if command == "PRIVMSG":
            event = self._parse_privmsg(parts, tags)
            if event:
                await self._emit(event)

        elif command == "USERNOTICE":
            event = self._parse_usernotice(parts, tags)
            if event:
                await self._emit(event)

    def _parse_tags(self, tag_str: str) -> dict[str, str]:
        """Parse Twitch IRC tags string into dict."""
        tags = {}
        for pair in tag_str.split(";"):
            if "=" in pair:
                key, _, val = pair.partition("=")
                tags[key] = val.replace("\\s", " ").replace("\\:", ";").replace("\\\\", "\\")
        return tags

    def _parse_privmsg(self, parts: list[str], tags: dict) -> NovaEvent | None:
        """Parse a PRIVMSG (chat message)."""
        if len(parts) < 3:
            return None

        channel = parts[1].lstrip("#")
        message = parts[2].lstrip(":")

        # Extract display name from tags
        display_name = tags.get("display-name", tags.get("login", "Anonymous"))
        user_id = tags.get("user-id", "")
        is_sub = tags.get("subscriber") == "1"
        is_mod = tags.get("mod") == "1"

        # Check for bits (cheer)
        bits_match = re.search(r"cheer(\d+)", message, re.IGNORECASE)
        if bits_match:
            bits_count = int(bits_match.group(1))
            # Clean cheer text from message
            clean_msg = re.sub(r"cheer\d+", "", message, flags=re.IGNORECASE).strip()
            viewer = self._make_viewer({
                "uid": user_id,
                "username": display_name,
                "is_member": is_sub,
            })
            return NovaEvent(
                type=EventType.GIFT_RECEIVED,
                payload={
                    "gift_name": "Bits",
                    "amount": bits_count / 100,  # 100 bits ≈ $1.40, simplified to 1 cent/bit
                    "count": bits_count,
                    "viewer": viewer.__dict__,
                },
                priority=Priority.HIGH,
                source="twitch",
            )

        viewer = self._make_viewer({
            "uid": user_id,
            "username": display_name,
            "is_member": is_sub,
        })
        return NovaEvent(
            type=EventType.CHAT_MESSAGE,
            payload={"text": message, "viewer": viewer.__dict__},
            priority=Priority.NORMAL if not is_mod else Priority.HIGH,
            source="twitch",
        )

    def _parse_usernotice(self, parts: list[str], tags: dict) -> NovaEvent | None:
        """Parse a USERNOTICE (subscription, raid, etc.)."""
        msg_id = tags.get("msg-id", "")
        display_name = tags.get("display-name", tags.get("login", "Anonymous"))
        user_id = tags.get("user-id", "")

        viewer = self._make_viewer({
            "uid": user_id,
            "username": display_name,
        })

        if msg_id in ("sub", "resub", "subgift"):
            # Paid subscription
            plan = tags.get("msg-param-sub-plan", "")
            amount = {"1000": 4.99, "2000": 9.99, "3000": 24.99}.get(plan, 4.99)
            return NovaEvent(
                type=EventType.SUPER_CHAT,
                payload={
                    "text": tags.get("system-msg", ""),
                    "amount": amount,
                    "currency": "USD",
                    "viewer": viewer.__dict__,
                },
                priority=Priority.CRITICAL,
                source="twitch",
            )

        elif msg_id == "raid":
            viewer_count = int(tags.get("msg-param-viewerCount", "0"))
            return NovaEvent(
                type=EventType.VIEWER_JOIN,
                payload={
                    "viewer": viewer.__dict__,
                    "raid": True,
                    "raid_viewers": viewer_count,
                },
                priority=Priority.NORMAL,
                source="twitch",
            )

        elif msg_id in ("anongiftsubupgrade", "giftpaidupgrade"):
            return NovaEvent(
                type=EventType.VIEWER_JOIN,
                payload={"viewer": viewer.__dict__},
                priority=Priority.LOW,
                source="twitch",
            )

        return None

    def _parse_raw(self, raw: Any) -> NovaEvent | None:
        return None
