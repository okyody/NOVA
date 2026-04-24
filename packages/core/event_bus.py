"""
NOVA Event Bus
==============
Async pub/sub with optional external transport mirroring.

Default mode remains in-process queue dispatch.
Enterprise foundation:
  - optional ingress idempotency before queueing
  - optional Redis Streams mirroring for external consumers
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable

from .types import EventType, NovaEvent

log = logging.getLogger("nova.event_bus")

Handler = Callable[[NovaEvent], Awaitable[None]]


@dataclass
class _Subscription:
    handler: Handler
    sub_id: str
    max_lag_ms: int = 500


class EventTransportBackend(ABC):
    @abstractmethod
    async def start(self) -> None:
        ...

    @abstractmethod
    async def stop(self) -> None:
        ...

    @abstractmethod
    async def publish(self, event: NovaEvent) -> None:
        ...

    @abstractmethod
    async def consume(self, *, block_ms: int = 1000, count: int = 10) -> list[NovaEvent]:
        ...

    @abstractmethod
    async def stats(self) -> dict[str, int]:
        ...


class InMemoryEventTransportBackend(EventTransportBackend):
    def __init__(self) -> None:
        self._queue: asyncio.Queue[NovaEvent] = asyncio.Queue()

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def publish(self, event: NovaEvent) -> None:
        await self._queue.put(event)

    async def consume(self, *, block_ms: int = 1000, count: int = 10) -> list[NovaEvent]:
        timeout_s = max(block_ms / 1000.0, 0.001)
        events: list[NovaEvent] = []
        try:
            first = await asyncio.wait_for(self._queue.get(), timeout=timeout_s)
            events.append(first)
        except asyncio.TimeoutError:
            return []

        while len(events) < count:
            try:
                events.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return events

    async def stats(self) -> dict[str, int]:
        return {"stream_length": self._queue.qsize(), "pending": 0, "dlq_length": 0, "retries_total": 0, "reclaimed_total": 0, "dead_lettered_total": 0}


class RedisStreamsEventTransportBackend(EventTransportBackend):
    def __init__(
        self,
        url: str = "redis://localhost:6379",
        db: int = 0,
        stream: str = "nova:events",
    ) -> None:
        self._url = url
        self._db = db
        self._stream = stream
        self._consumer_group = "nova-workers"
        self._consumer_name = "nova-consumer-1"
        self._pending_min_idle_ms = 30000
        self._reclaim_batch_size = 20
        self._max_retries = 5
        self._dlq_stream = f"{stream}:dlq"
        self._last_pending_count = 0
        self._retries_total = 0
        self._reclaimed_total = 0
        self._dead_lettered_total = 0
        self._client: Any = None

    def configure_consumer(
        self,
        *,
        group: str,
        consumer: str,
        pending_min_idle_ms: int = 30000,
        reclaim_batch_size: int = 20,
        max_retries: int = 5,
        dlq_stream: str | None = None,
    ) -> None:
        self._consumer_group = group
        self._consumer_name = consumer
        self._pending_min_idle_ms = pending_min_idle_ms
        self._reclaim_batch_size = reclaim_batch_size
        self._max_retries = max_retries
        if dlq_stream:
            self._dlq_stream = dlq_stream

    def _client_or_raise(self) -> Any:
        if self._client is None:
            try:
                import redis.asyncio as aioredis
            except ImportError as exc:
                raise ImportError("redis.asyncio not installed. Run: pip install redis") from exc
            self._client = aioredis.from_url(self._url, db=self._db, decode_responses=True)
        return self._client

    async def start(self) -> None:
        client = self._client_or_raise()
        try:
            await client.xgroup_create(self._stream, self._consumer_group, id="$", mkstream=True)
        except Exception:
            pass
        try:
            await client.xgroup_create(self._dlq_stream, self._consumer_group, id="$", mkstream=True)
        except Exception:
            pass

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.close()

    async def publish(self, event: NovaEvent) -> None:
        client = self._client_or_raise()
        await client.xadd(
            self._stream,
            {
                "event_id": event.event_id,
                "type": event.type.value,
                "priority": str(event.priority.value),
                "timestamp": event.timestamp.isoformat(),
                "source": event.source,
                "trace_id": event.trace_id or "",
                "payload": json.dumps(event.payload, ensure_ascii=False, default=str),
            },
        )

    async def consume(self, *, block_ms: int = 1000, count: int = 10) -> list[NovaEvent]:
        client = self._client_or_raise()
        reclaimed = await self._reclaim_stale_messages(count=min(count, self._reclaim_batch_size))
        if reclaimed:
            return reclaimed

        results = await client.xreadgroup(
            self._consumer_group,
            self._consumer_name,
            {self._stream: ">"},
            count=count,
            block=block_ms,
        )
        events: list[NovaEvent] = []
        for _stream_name, items in results:
            for redis_id, fields in items:
                event = self._deserialize_event(redis_id, fields)
                if event is not None:
                    events.append(event)
                    await client.xack(self._stream, self._consumer_group, redis_id)
        return events

    async def _reclaim_stale_messages(self, *, count: int) -> list[NovaEvent]:
        client = self._client_or_raise()
        try:
            pending = await client.xpending_range(
                self._stream,
                self._consumer_group,
                min="-",
                max="+",
                count=count,
                idle=self._pending_min_idle_ms,
            )
        except Exception:
            return []

        if not pending:
            return []
        self._last_pending_count = len(pending)

        reclaim_ids: list[str] = []
        events: list[NovaEvent] = []
        for item in pending:
            msg_id = item.get("message_id") or item.get("message_id".encode())
            deliveries = item.get("times_delivered") or item.get("times_delivered".encode()) or 0
            if not msg_id:
                continue
            if int(deliveries) > self._max_retries:
                await self._move_to_dlq(msg_id)
                continue
            reclaim_ids.append(msg_id)
            self._retries_total += 1

        if not reclaim_ids:
            return []

        try:
            claimed = await client.xclaim(
                self._stream,
                self._consumer_group,
                self._consumer_name,
                min_idle_time=self._pending_min_idle_ms,
                message_ids=reclaim_ids,
            )
        except Exception:
            return []

        for redis_id, fields in claimed:
            event = self._deserialize_event(redis_id, fields)
            if event is not None:
                events.append(event)
                self._reclaimed_total += 1
                await client.xack(self._stream, self._consumer_group, redis_id)
        return events

    async def _move_to_dlq(self, redis_id: str) -> None:
        client = self._client_or_raise()
        records = await client.xrange(self._stream, min=redis_id, max=redis_id, count=1)
        if not records:
            return
        _, fields = records[0]
        payload = dict(fields)
        payload["original_stream"] = self._stream
        payload["dead_lettered_at"] = datetime.utcnow().isoformat()
        await client.xadd(self._dlq_stream, payload)
        await client.xack(self._stream, self._consumer_group, redis_id)
        self._dead_lettered_total += 1

    def _deserialize_event(self, redis_id: str, fields: dict[str, Any]) -> NovaEvent | None:
        try:
            return NovaEvent(
                type=EventType(fields["type"]),
                payload=json.loads(fields.get("payload", "{}")),
                priority=int(fields.get("priority", "2")),
                event_id=fields.get("event_id", redis_id),
                timestamp=datetime.fromisoformat(fields["timestamp"]) if fields.get("timestamp") else datetime.utcnow(),
                source=fields.get("source", "unknown"),
                trace_id=fields.get("trace_id") or None,
            )
        except Exception:
            log.warning("Failed to deserialize event from stream id=%s", redis_id)
            return None

    async def stats(self) -> dict[str, int]:
        client = self._client_or_raise()
        stream_length = 0
        dlq_length = 0
        consumer_lag = 0
        pending_count = self._last_pending_count
        try:
            stream_length = await client.xlen(self._stream)
        except Exception:
            pass
        try:
            dlq_length = await client.xlen(self._dlq_stream)
        except Exception:
            pass
        try:
            groups = await client.xinfo_groups(self._stream)
            for group in groups:
                name = group.get("name") or group.get(b"name")
                if name == self._consumer_group:
                    consumer_lag = int(group.get("lag") or group.get(b"lag") or 0)
                    pending_count = int(group.get("pending") or group.get(b"pending") or pending_count)
                    break
        except Exception:
            pass
        return {
            "stream_length": int(stream_length),
            "pending": int(pending_count),
            "consumer_lag": int(consumer_lag),
            "dlq_length": int(dlq_length),
            "retries_total": int(self._retries_total),
            "reclaimed_total": int(self._reclaimed_total),
            "dead_lettered_total": int(self._dead_lettered_total),
        }


def create_event_transport_backend(config: dict[str, Any] | None = None) -> EventTransportBackend:
    config = config or {}
    backend = config.get("backend", "memory")
    if backend == "redis_streams":
        transport = RedisStreamsEventTransportBackend(
            url=config.get("url", "redis://localhost:6379"),
            db=config.get("db", 0),
            stream=config.get("stream", "nova:events"),
        )
        transport.configure_consumer(
            group=config.get("consumer_group", "nova-workers"),
            consumer=config.get("consumer_name", "nova-consumer-1"),
            pending_min_idle_ms=config.get("pending_min_idle_ms", 30000),
            reclaim_batch_size=config.get("reclaim_batch_size", 20),
            max_retries=config.get("max_retries", 5),
            dlq_stream=config.get("dlq_stream"),
        )
        return transport
    return InMemoryEventTransportBackend()


class EventBus:
    def __init__(
        self,
        queue_size: int = 4096,
        transport_backend: EventTransportBackend | None = None,
        ingress_idempotency_backend: Any | None = None,
        ingress_idempotency_namespace: str = "nova",
        ingress_idempotency_ttl_s: int = 600,
        mode: str = "local",
    ) -> None:
        self._queue: asyncio.PriorityQueue[tuple[int, float, NovaEvent]] = (
            asyncio.PriorityQueue(maxsize=queue_size)
        )
        self._subscribers: dict[str, list[_Subscription]] = defaultdict(list)
        self._wildcard_subs: list[tuple[str, _Subscription]] = []
        self._dlq: list[NovaEvent] = []
        self._dispatch_task: asyncio.Task | None = None
        self._running = False
        self._stats: dict[str, int] = defaultdict(int)
        self._transport_stats: dict[str, int] = {}
        self._transport_backend = transport_backend or InMemoryEventTransportBackend()
        self._ingress_idempotency_backend = ingress_idempotency_backend
        self._ingress_idempotency_namespace = ingress_idempotency_namespace
        self._ingress_idempotency_ttl_s = ingress_idempotency_ttl_s
        self._mode = mode

    async def start(self) -> None:
        self._running = True
        await self._transport_backend.start()
        self._transport_stats = await self._transport_backend.stats()
        loop_fn = self._consume_loop if self._mode == "external_consumer" else self._dispatch_loop
        self._dispatch_task = asyncio.create_task(loop_fn(), name="nova.event_bus.dispatch")
        log.info("Event bus started")

    async def stop(self) -> None:
        self._running = False
        if self._dispatch_task:
            self._dispatch_task.cancel()
            try:
                await self._dispatch_task
            except asyncio.CancelledError:
                pass
        await self._transport_backend.stop()
        log.info("Event bus stopped. Stats: %s | DLQ size: %d", dict(self._stats), len(self._dlq))

    async def publish(self, event: NovaEvent) -> None:
        if not self._running:
            log.warning("Bus not running, dropping event %s", event.type)
            return

        await self._transport_backend.publish(event)

        if self._mode == "local":
            sort_key = (event.priority.value, time.monotonic())
            try:
                self._queue.put_nowait((sort_key[0], sort_key[1], event))
                self._stats["published"] += 1
            except asyncio.QueueFull:
                log.error("Event queue full! Dropping %s (priority=%s)", event.type, event.priority)
                self._stats["dropped"] += 1
        else:
            self._stats["published"] += 1

    async def publish_ingress(self, event: NovaEvent) -> bool:
        if self._ingress_idempotency_backend is not None:
            key = f"{self._ingress_idempotency_namespace}:ingress:{event.event_id}"
            accepted = await self._ingress_idempotency_backend.set_if_absent_json(
                key,
                {
                    "event_id": event.event_id,
                    "type": event.type.value,
                    "source": event.source,
                    "timestamp": event.timestamp.isoformat(),
                },
                ttl=self._ingress_idempotency_ttl_s,
            )
            if not accepted:
                self._stats["duplicates"] += 1
                return False
        await self.publish(event)
        return True

    def publish_sync(self, event: NovaEvent) -> None:
        asyncio.create_task(self.publish(event))

    def subscribe(
        self,
        event_type: EventType | str,
        handler: Handler,
        sub_id: str = "",
        max_lag_ms: int = 500,
    ) -> None:
        key = event_type.value if isinstance(event_type, EventType) else event_type
        sub = _Subscription(
            handler=handler,
            sub_id=sub_id or f"sub_{id(handler)}",
            max_lag_ms=max_lag_ms,
        )

        if "*" in key:
            prefix = key.rstrip("*")
            self._wildcard_subs.append((prefix, sub))
            log.debug("Wildcard subscription: %s -> %s", key, sub.sub_id)
        else:
            self._subscribers[key].append(sub)
            log.debug("Subscription: %s -> %s", key, sub.sub_id)

    def unsubscribe(self, event_type: EventType | str, sub_id: str) -> None:
        key = event_type.value if isinstance(event_type, EventType) else event_type
        self._subscribers[key] = [s for s in self._subscribers[key] if s.sub_id != sub_id]

    async def _dispatch_loop(self) -> None:
        while self._running:
            try:
                _, _, event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            await self._dispatch(event)
            self._queue.task_done()

    async def _consume_loop(self) -> None:
        while self._running:
            try:
                events = await self._transport_backend.consume(block_ms=1000, count=10)
                self._transport_stats = await self._transport_backend.stats()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.warning("External consumer poll failed: %s", exc)
                await asyncio.sleep(1)
                continue

            for event in events:
                await self._dispatch(event)

    async def _dispatch(self, event: NovaEvent) -> None:
        key = event.type.value
        handlers = list(self._subscribers.get(key, []))

        for prefix, sub in self._wildcard_subs:
            if key.startswith(prefix):
                handlers.append(sub)

        if not handlers:
            self._dlq.append(event)
            self._stats["dlq"] += 1
            log.debug("No handler for event %s -> DLQ", event.type)
            return

        tasks = [self._invoke(sub, event) for sub in handlers]
        await asyncio.gather(*tasks, return_exceptions=True)
        self._stats["dispatched"] += 1

    async def _invoke(self, sub: _Subscription, event: NovaEvent) -> None:
        t0 = time.monotonic()
        try:
            await sub.handler(event)
            lag_ms = (time.monotonic() - t0) * 1000
            if lag_ms > sub.max_lag_ms:
                log.warning("Slow handler %s for %s: %.0f ms", sub.sub_id, event.type, lag_ms)
        except Exception as exc:
            log.exception("Handler %s raised for event %s: %s", sub.sub_id, event.type, exc)
            self._stats["errors"] += 1

    def stats(self) -> dict[str, int]:
        queue_depth = self._queue.qsize() if self._mode == "local" else 0
        return dict(self._stats) | {"queue_depth": queue_depth, **self._transport_stats}

    def dlq_drain(self) -> list[NovaEvent]:
        events, self._dlq = self._dlq[:], []
        return events
