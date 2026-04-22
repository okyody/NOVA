"""
NOVA Event Bus
==============
Async priority pub/sub. The single communication backbone.
All inter-module communication flows through here — zero direct imports
between modules (except from core.types).

Design decisions:
  - asyncio.PriorityQueue for CRITICAL events to preempt NORMAL work
  - Per-event-type subscriber sets (O(1) dispatch)
  - Wildcard subscriptions via prefix matching (e.g. "platform.*")
  - Dead-letter queue for unhandled events (observability)
  - Back-pressure: slow subscribers get a warning, not a crash
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from .types import EventType, NovaEvent, Priority

log = logging.getLogger("nova.event_bus")

Handler = Callable[[NovaEvent], Awaitable[None]]


@dataclass
class _Subscription:
    handler:    Handler
    sub_id:     str
    max_lag_ms: int = 500    # warn if handler takes longer


class EventBus:
    """
    Central async event bus.

    Usage
    -----
    bus = EventBus()
    await bus.start()

    # Subscribe
    async def on_chat(event: NovaEvent):
        print(event.payload["text"])

    bus.subscribe(EventType.CHAT_MESSAGE, on_chat, sub_id="chat_printer")

    # Publish
    await bus.publish(NovaEvent(
        type=EventType.CHAT_MESSAGE,
        payload={"text": "hello"},
    ))

    await bus.stop()
    """

    def __init__(self, queue_size: int = 4096) -> None:
        self._queue: asyncio.PriorityQueue[tuple[int, float, NovaEvent]] = (
            asyncio.PriorityQueue(maxsize=queue_size)
        )
        self._subscribers: dict[str, list[_Subscription]] = defaultdict(list)
        self._wildcard_subs: list[tuple[str, _Subscription]] = []  # (prefix, sub)
        self._dlq: list[NovaEvent] = []           # dead letter queue
        self._dispatch_task: asyncio.Task | None  = None
        self._running = False
        self._stats: dict[str, int] = defaultdict(int)

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        self._running = True
        self._dispatch_task = asyncio.create_task(
            self._dispatch_loop(), name="nova.event_bus.dispatch"
        )
        log.info("Event bus started")

    async def stop(self) -> None:
        self._running = False
        if self._dispatch_task:
            self._dispatch_task.cancel()
            try:
                await self._dispatch_task
            except asyncio.CancelledError:
                pass
        log.info(
            "Event bus stopped. Stats: %s | DLQ size: %d",
            dict(self._stats), len(self._dlq)
        )

    # ── Publish ────────────────────────────────────────────────────────────

    async def publish(self, event: NovaEvent) -> None:
        """
        Enqueue an event. Priority-ordered: lower int = higher priority.
        Tie-break by timestamp so older events dispatch first within a tier.
        """
        if not self._running:
            log.warning("Bus not running, dropping event %s", event.type)
            return

        sort_key = (event.priority.value, time.monotonic())
        try:
            self._queue.put_nowait((sort_key[0], sort_key[1], event))
            self._stats["published"] += 1
        except asyncio.QueueFull:
            log.error(
                "Event queue full! Dropping %s (priority=%s)",
                event.type, event.priority
            )
            self._stats["dropped"] += 1

    def publish_sync(self, event: NovaEvent) -> None:
        """Fire-and-forget from sync code. Creates a task."""
        asyncio.create_task(self.publish(event))

    # ── Subscribe ──────────────────────────────────────────────────────────

    def subscribe(
        self,
        event_type: EventType | str,
        handler: Handler,
        sub_id: str = "",
        max_lag_ms: int = 500,
    ) -> None:
        """
        Subscribe to a specific event type or a wildcard prefix.

        Examples:
            bus.subscribe(EventType.CHAT_MESSAGE, handler)
            bus.subscribe("platform.*", handler)   # all platform events
            bus.subscribe("cognitive.*", handler)  # all cognitive events
        """
        key = event_type.value if isinstance(event_type, EventType) else event_type
        sub = _Subscription(
            handler=handler,
            sub_id=sub_id or f"sub_{id(handler)}",
            max_lag_ms=max_lag_ms,
        )

        if "*" in key:
            prefix = key.rstrip("*")
            self._wildcard_subs.append((prefix, sub))
            log.debug("Wildcard subscription: %s → %s", key, sub.sub_id)
        else:
            self._subscribers[key].append(sub)
            log.debug("Subscription: %s → %s", key, sub.sub_id)

    def unsubscribe(self, event_type: EventType | str, sub_id: str) -> None:
        key = event_type.value if isinstance(event_type, EventType) else event_type
        self._subscribers[key] = [
            s for s in self._subscribers[key] if s.sub_id != sub_id
        ]

    # ── Internal dispatch ──────────────────────────────────────────────────

    async def _dispatch_loop(self) -> None:
        while self._running:
            try:
                _, _, event = await asyncio.wait_for(
                    self._queue.get(), timeout=1.0
                )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            await self._dispatch(event)
            self._queue.task_done()

    async def _dispatch(self, event: NovaEvent) -> None:
        key = event.type.value
        handlers = list(self._subscribers.get(key, []))

        # Add wildcard matches
        for prefix, sub in self._wildcard_subs:
            if key.startswith(prefix):
                handlers.append(sub)

        if not handlers:
            self._dlq.append(event)
            self._stats["dlq"] += 1
            log.debug("No handler for event %s → DLQ", event.type)
            return

        # Fan out to all handlers concurrently
        tasks = [self._invoke(sub, event) for sub in handlers]
        await asyncio.gather(*tasks, return_exceptions=True)
        self._stats["dispatched"] += 1

    async def _invoke(self, sub: _Subscription, event: NovaEvent) -> None:
        t0 = time.monotonic()
        try:
            await sub.handler(event)
            lag_ms = (time.monotonic() - t0) * 1000
            if lag_ms > sub.max_lag_ms:
                log.warning(
                    "Slow handler %s for %s: %.0f ms", sub.sub_id, event.type, lag_ms
                )
        except Exception as exc:
            log.exception(
                "Handler %s raised for event %s: %s", sub.sub_id, event.type, exc
            )
            self._stats["errors"] += 1

    # ── Observability ──────────────────────────────────────────────────────

    def stats(self) -> dict[str, int]:
        return dict(self._stats) | {"queue_depth": self._queue.qsize()}

    def dlq_drain(self) -> list[NovaEvent]:
        events, self._dlq = self._dlq[:], []
        return events
