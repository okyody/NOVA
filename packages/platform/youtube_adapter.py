"""
NOVA YouTube Live Adapter
==========================
Uses YouTube Data API v3 (liveChatMessages.list) to poll
live chat messages from a YouTube live stream.

YouTube uses a polling model (not WebSocket) due to API constraints.
We implement exponential backoff and quota management.

Message types:
  textMessageEvent    → CHAT_MESSAGE
  superChatEvent      → SUPER_CHAT
  newSponsorEvent     → VIEWER_JOIN (member join)
  memberMilestoneChatEvent → CHAT_MESSAGE (with milestone info)
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from packages.core.event_bus import EventBus
from packages.core.types import EventType, NovaEvent, Platform, Priority, ViewerProfile

from .adapters import BaseAdapter

log = logging.getLogger("nova.platform.youtube")


class YouTubeAdapter(BaseAdapter):
    """
    YouTube Live Chat adapter using the Data API v3.

    Uses polling with smart backoff:
      - Active chat: poll every 2-3s
      - Quiet chat:  poll every 5-7s
      - Quota low:   reduce poll frequency

    Quota budget: 10,000 units/day
      - liveChatMessages.list costs 5 units per call
      - Max ~2,000 calls/day → ~1 call per 43s if running 24h
      - In practice: poll every 3s for ~2.8h or manage quota carefully
    """

    API_BASE = "https://www.googleapis.com/youtube/v3"

    def __init__(
        self,
        bus: EventBus,
        live_chat_id: str,
        api_key: str,
        poll_interval: float = 3.0,
    ) -> None:
        super().__init__(bus, Platform.YOUTUBE)
        self._live_chat_id = live_chat_id
        self._api_key = api_key
        self._poll_interval = poll_interval
        self._next_page_token: str | None = None
        self._client: httpx.AsyncClient | None = None
        self._quota_used = 0
        self._DAILY_QUOTA = 10000

    async def _connect(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=self.API_BASE,
            params={"key": self._api_key},
            timeout=15.0,
        )
        log.info("YouTube adapter connected, chat_id=%s", self._live_chat_id)
        await self._poll_loop()

    async def _disconnect(self) -> None:
        if self._client:
            await self._client.aclose()

    async def _poll_loop(self) -> None:
        """Main polling loop with adaptive interval."""
        while self._running:
            try:
                msg_count = await self._poll_messages()

                # Adaptive polling: faster when busy, slower when quiet
                if msg_count > 5:
                    self._poll_interval = max(2.0, self._poll_interval * 0.9)
                elif msg_count == 0:
                    self._poll_interval = min(7.0, self._poll_interval * 1.1)

                # Quota management
                if self._quota_used > self._DAILY_QUOTA * 0.8:
                    log.warning(
                        "YouTube API quota at %d/%d, reducing poll frequency",
                        self._quota_used, self._DAILY_QUOTA,
                    )
                    self._poll_interval = min(15.0, self._poll_interval * 2.0)

                await asyncio.sleep(self._poll_interval)

            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 403:
                    log.error("YouTube API quota exceeded or forbidden")
                    await asyncio.sleep(60)
                elif exc.response.status_code >= 500:
                    log.warning("YouTube server error, backing off")
                    await asyncio.sleep(30)
                else:
                    raise
            except Exception as exc:
                log.error("YouTube poll error: %s", exc)
                await asyncio.sleep(10)

    async def _poll_messages(self) -> int:
        """Fetch and emit new chat messages. Returns count of new messages."""
        if not self._client:
            return 0

        params: dict[str, Any] = {
            "liveChatId": self._live_chat_id,
            "part": "snippet,authorDetails",
            "maxResults": 200,
        }
        if self._next_page_token:
            params["pageToken"] = self._next_page_token

        resp = await self._client.get("/liveChat/messages", params=params)
        resp.raise_for_status()
        self._quota_used += 5  # cost per call

        data = resp.json()
        self._next_page_token = data.get("nextPageToken")

        items = data.get("items", [])
        poll_interval_ms = data.get("pollingIntervalMillis", 3000)
        self._poll_interval = poll_interval_ms / 1000.0

        for item in items:
            event = self._parse_youtube_item(item)
            if event:
                await self._emit(event)

        return len(items)

    def _parse_youtube_item(self, item: dict) -> NovaEvent | None:
        """Parse a YouTube liveChatMessage resource into a NovaEvent."""
        snippet = item.get("snippet", {})
        author = item.get("authorDetails", {})
        msg_type = snippet.get("type", "")

        viewer = self._make_viewer({
            "uid":       author.get("channelId", ""),
            "username":  author.get("displayName", "Anonymous"),
            "is_member": author.get("isChatSponsor", False),
        })

        if msg_type == "textMessageEvent":
            text = snippet.get("displayMessage", "")
            return NovaEvent(
                type=EventType.CHAT_MESSAGE,
                payload={"text": text, "viewer": viewer.__dict__},
                priority=Priority.NORMAL,
                source="youtube",
            )

        elif msg_type == "superChatEvent":
            amount_micros = snippet.get("superChatDetails", {}).get("amountMicros", 0)
            amount_usd = amount_micros / 1_000_000
            currency = snippet.get("superChatDetails", {}).get("currency", "USD")
            text = snippet.get("superChatDetails", {}).get("userComment", "")
            return NovaEvent(
                type=EventType.SUPER_CHAT,
                payload={
                    "text": text,
                    "amount": amount_usd,
                    "currency": currency,
                    "viewer": viewer.__dict__,
                },
                priority=Priority.CRITICAL,
                source="youtube",
            )

        elif msg_type == "newSponsorEvent":
            return NovaEvent(
                type=EventType.VIEWER_JOIN,
                payload={"viewer": viewer.__dict__},
                priority=Priority.NORMAL,
                source="youtube",
            )

        elif msg_type == "memberMilestoneChatEvent":
            text = snippet.get("displayMessage", "")
            return NovaEvent(
                type=EventType.CHAT_MESSAGE,
                payload={
                    "text": text,
                    "viewer": viewer.__dict__,
                    "is_milestone": True,
                },
                priority=Priority.NORMAL,
                source="youtube",
            )

        return None

    def _parse_raw(self, raw: Any) -> NovaEvent | None:
        return None
