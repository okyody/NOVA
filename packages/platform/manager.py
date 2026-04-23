"""
NOVA Platform Manager
======================
Manages multiple platform adapters concurrently.
Aggregates LIVE_STATS from all platforms into a unified view.

Features:
  - Start/stop individual adapters without restarting the server
  - Aggregate viewer counts and chat rates across platforms
  - Per-platform health monitoring
  - Hot-add new platforms at runtime
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from packages.core.event_bus import EventBus
from packages.core.types import EventType, NovaEvent, Platform, Priority

from .adapters import BaseAdapter, create_adapter

log = logging.getLogger("nova.platform.manager")


@dataclass
class AdapterStatus:
    platform: Platform
    running: bool = False
    last_event_time: float = 0.0
    events_received: int = 0
    errors: int = 0
    latency_ms: float = 0.0


class PlatformManager:
    """
    Unified manager for all platform adapters.

    Lifecycle:
      1. start() — start all configured adapters
      2. add_platform() — hot-add a new platform at runtime
      3. remove_platform() — gracefully stop and remove a platform
      4. stop() — stop all adapters

    Aggregates LIVE_STATS events from all platforms and publishes
    a unified AGGREGATED_STATS event.
    """

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._adapters: dict[Platform, BaseAdapter] = {}
        self._statuses: dict[Platform, AdapterStatus] = {}
        self._running = False

    @staticmethod
    def validate_config(config: dict[str, Any]) -> tuple[bool, str]:
        platform = str(config.get("platform", "")).strip().lower()
        required: dict[str, list[str]] = {
            "bilibili": ["room_id"],
            "douyin": ["room_id", "app_id", "app_secret"],
            "youtube": ["live_chat_id", "api_key"],
            "twitch": ["channel", "oauth_token"],
            "kuaishou": ["room_id"],
            "wechat": ["room_id", "app_id", "app_secret"],
        }
        missing = [key for key in required.get(platform, []) if not config.get(key)]
        if missing:
            return False, f"missing required fields: {', '.join(missing)}"
        return True, ""

    async def start(self, platform_configs: list[dict]) -> None:
        """Start all configured platform adapters."""
        self._running = True

        # Subscribe to stats for aggregation
        self._bus.subscribe(
            EventType.LIVE_STATS, self._on_stats, sub_id="platform_manager_stats"
        )

        for cfg in platform_configs:
            try:
                await self.add_platform(cfg)
            except Exception as exc:
                log.error("Failed to start adapter for %s: %s",
                         cfg.get("platform", "?"), exc)

        log.info("Platform manager started with %d adapter(s)", len(self._adapters))

    async def stop(self) -> None:
        """Stop all adapters."""
        self._running = False
        for platform, adapter in list(self._adapters.items()):
            try:
                await adapter.stop()
                self._statuses[platform].running = False
                log.info("Stopped adapter: %s", platform.value)
            except Exception as exc:
                log.error("Error stopping %s: %s", platform.value, exc)
        self._adapters.clear()

    async def add_platform(self, config: dict) -> None:
        """Hot-add a new platform adapter at runtime."""
        valid, reason = self.validate_config(config)
        if not valid:
            log.warning("Skipping platform config for %s: %s", config.get("platform", "?"), reason)
            return

        platform = Platform(config["platform"])

        if platform in self._adapters:
            log.warning("Adapter already running for %s, removing first", platform.value)
            await self.remove_platform(platform)

        adapter = create_adapter(platform, self._bus, config)
        await adapter.start()

        self._adapters[platform] = adapter
        self._statuses[platform] = AdapterStatus(platform=platform, running=True)

        log.info("Added platform adapter: %s", platform.value)

    async def remove_platform(self, platform: Platform) -> None:
        """Gracefully stop and remove a platform adapter."""
        adapter = self._adapters.pop(platform, None)
        if adapter:
            await adapter.stop()
            self._statuses.pop(platform, None)
            log.info("Removed platform adapter: %s", platform.value)

    def get_status(self) -> dict[str, dict]:
        """Get status of all adapters."""
        result = {}
        for platform, status in self._statuses.items():
            result[platform.value] = {
                "running": status.running,
                "events_received": status.events_received,
                "errors": status.errors,
                "last_event_ago_s": round(time.monotonic() - status.last_event_time, 1)
                    if status.last_event_time > 0 else None,
            }
        return result

    async def _on_stats(self, event: NovaEvent) -> None:
        """Track per-platform stats from LIVE_STATS events."""
        source = event.source
        platform = None
        for p in Platform:
            if p.value == source:
                platform = p
                break

        if platform and platform in self._statuses:
            status = self._statuses[platform]
            status.last_event_time = time.monotonic()
            status.events_received += 1
