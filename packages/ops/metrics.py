"""
NOVA Prometheus Metrics
=======================
Collects and exposes Prometheus-compatible metrics.

Metrics exposed:
  - nova_events_published_total     — total events published to bus
  - nova_events_dropped_total       — events dropped due to queue full
  - nova_safety_checks_total        — safety guard checks
  - nova_safety_blocks_total        — safety guard blocks
  - nova_llm_requests_total         — LLM API calls
  - nova_llm_latency_seconds        — LLM response latency histogram
  - nova_tts_requests_total         — TTS synthesis calls
  - nova_tts_latency_seconds        — TTS synthesis latency
  - nova_pipeline_latency_seconds   — end-to-end pipeline latency
  - nova_active_websockets          — active WebSocket connections
  - nova_memory_working_size        — working memory entries
  - nova_knowledge_documents        — knowledge base document count
  - nova_circuit_breaker_state      — circuit breaker state (0=closed, 1=open, 2=half_open)
"""
from __future__ import annotations

import logging
import time
from typing import Any

try:
    from prometheus_client import (
        Counter,
        Histogram,
        Gauge,
        CollectorRegistry,
        generate_latest,
        CONTENT_TYPE_LATEST,
    )
    HAS_PROMETHEUS = True
except ImportError:
    HAS_PROMETHEUS = False

log = logging.getLogger("nova.metrics")


# ─── Metrics Registry ─────────────────────────────────────────────────────────

if HAS_PROMETHEUS:
    _registry = CollectorRegistry()

    # Event bus metrics
    events_published = Counter(
        "nova_events_published_total",
        "Total events published to EventBus",
        ["event_type"],
        registry=_registry,
    )
    events_dropped = Counter(
        "nova_events_dropped_total",
        "Events dropped due to queue full",
        registry=_registry,
    )

    # Safety metrics
    safety_checks = Counter(
        "nova_safety_checks_total",
        "Total safety checks performed",
        registry=_registry,
    )
    safety_blocks = Counter(
        "nova_safety_blocks_total",
        "Total safety blocks",
        ["category"],
        registry=_registry,
    )

    # LLM metrics
    llm_requests = Counter(
        "nova_llm_requests_total",
        "Total LLM API requests",
        ["model"],
        registry=_registry,
    )
    llm_latency = Histogram(
        "nova_llm_latency_seconds",
        "LLM response latency",
        ["model"],
        buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
        registry=_registry,
    )

    # TTS metrics
    tts_requests = Counter(
        "nova_tts_requests_total",
        "Total TTS synthesis requests",
        ["backend"],
        registry=_registry,
    )
    tts_latency = Histogram(
        "nova_tts_latency_seconds",
        "TTS synthesis latency",
        ["backend"],
        buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0],
        registry=_registry,
    )

    # Pipeline metrics
    pipeline_latency = Histogram(
        "nova_pipeline_latency_seconds",
        "End-to-end pipeline latency",
        buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0],
        registry=_registry,
    )

    # Gauge metrics
    active_websockets = Gauge(
        "nova_active_websockets",
        "Active WebSocket connections",
        registry=_registry,
    )
    memory_working_size = Gauge(
        "nova_memory_working_size",
        "Working memory entry count",
        registry=_registry,
    )
    knowledge_documents = Gauge(
        "nova_knowledge_documents",
        "Knowledge base document count",
        registry=_registry,
    )
    queue_depth = Gauge(
        "nova_eventbus_queue_depth",
        "EventBus queue depth",
        registry=_registry,
    )
    eventbus_pending = Gauge(
        "nova_eventbus_pending_messages",
        "EventBus pending messages in external transport",
        registry=_registry,
    )
    eventbus_stream_length = Gauge(
        "nova_eventbus_stream_length",
        "EventBus external stream length",
        registry=_registry,
    )
    eventbus_consumer_lag = Gauge(
        "nova_eventbus_consumer_lag",
        "EventBus consumer lag for external transport",
        registry=_registry,
    )
    eventbus_dlq_length = Gauge(
        "nova_eventbus_dlq_length",
        "EventBus dead-letter stream length",
        registry=_registry,
    )
    eventbus_retries_total = Gauge(
        "nova_eventbus_retries_total",
        "EventBus retried messages total",
        registry=_registry,
    )
    eventbus_reclaimed_total = Gauge(
        "nova_eventbus_reclaimed_total",
        "EventBus reclaimed stale messages total",
        registry=_registry,
    )
    eventbus_dead_lettered_total = Gauge(
        "nova_eventbus_dead_lettered_total",
        "EventBus dead-lettered messages total",
        registry=_registry,
    )
    circuit_breaker_state = Gauge(
        "nova_circuit_breaker_state",
        "Circuit breaker state (0=closed, 1=open, 2=half_open)",
        ["name"],
        registry=_registry,
    )


class MetricsCollector:
    """
    Centralized metrics collector for NOVA.

    Provides convenience methods for recording metrics.
    Falls back to no-op if prometheus_client is not installed.
    """

    def __init__(self) -> None:
        self._enabled = HAS_PROMETHEUS

    def record_event_published(self, event_type: str) -> None:
        if self._enabled:
            events_published.labels(event_type=event_type).inc()

    def record_event_dropped(self) -> None:
        if self._enabled:
            events_dropped.inc()

    def record_safety_check(self) -> None:
        if self._enabled:
            safety_checks.inc()

    def record_safety_block(self, category: str) -> None:
        if self._enabled:
            safety_blocks.labels(category=category).inc()

    def record_llm_request(self, model: str, latency_s: float) -> None:
        if self._enabled:
            llm_requests.labels(model=model).inc()
            llm_latency.labels(model=model).observe(latency_s)

    def record_tts_request(self, backend: str, latency_s: float) -> None:
        if self._enabled:
            tts_requests.labels(backend=backend).inc()
            tts_latency.labels(backend=backend).observe(latency_s)

    def record_pipeline_latency(self, latency_s: float) -> None:
        if self._enabled:
            pipeline_latency.observe(latency_s)

    def set_active_websockets(self, count: int) -> None:
        if self._enabled:
            active_websockets.set(count)

    def set_memory_working_size(self, size: int) -> None:
        if self._enabled:
            memory_working_size.set(size)

    def set_knowledge_documents(self, count: int) -> None:
        if self._enabled:
            knowledge_documents.set(count)

    def set_queue_depth(self, depth: int) -> None:
        if self._enabled:
            queue_depth.set(depth)

    def set_eventbus_pending(self, count: int) -> None:
        if self._enabled:
            eventbus_pending.set(count)

    def set_eventbus_stream_length(self, count: int) -> None:
        if self._enabled:
            eventbus_stream_length.set(count)

    def set_eventbus_consumer_lag(self, count: int) -> None:
        if self._enabled:
            eventbus_consumer_lag.set(count)

    def set_eventbus_dlq_length(self, count: int) -> None:
        if self._enabled:
            eventbus_dlq_length.set(count)

    def set_eventbus_retries_total(self, count: int) -> None:
        if self._enabled:
            eventbus_retries_total.set(count)

    def set_eventbus_reclaimed_total(self, count: int) -> None:
        if self._enabled:
            eventbus_reclaimed_total.set(count)

    def set_eventbus_dead_lettered_total(self, count: int) -> None:
        if self._enabled:
            eventbus_dead_lettered_total.set(count)

    def set_circuit_breaker(self, name: str, state: str) -> None:
        if self._enabled:
            state_map = {"closed": 0, "open": 1, "half_open": 2}
            circuit_breaker_state.labels(name=name).set(state_map.get(state, 0))

    def generate_metrics(self) -> tuple[str, str]:
        """Generate Prometheus-compatible metrics output. Returns (content, content_type)."""
        if not self._enabled:
            return "", "text/plain"
        return generate_latest(_registry).decode("utf-8"), CONTENT_TYPE_LATEST


# Global instance
metrics = MetricsCollector()


class Timer:
    """Context manager / decorator for timing operations."""

    def __init__(self, metric_fn: Any = None) -> None:
        self._metric_fn = metric_fn
        self._start = 0.0
        self.elapsed = 0.0

    def __enter__(self) -> "Timer":
        self._start = time.monotonic()
        return self

    def __exit__(self, *args: Any) -> None:
        self.elapsed = time.monotonic() - self._start
        if self._metric_fn:
            self._metric_fn(self.elapsed)

    async def __aenter__(self) -> "Timer":
        self._start = time.monotonic()
        return self

    async def __aexit__(self, *args: Any) -> None:
        self.elapsed = time.monotonic() - self._start
        if self._metric_fn:
            self._metric_fn(self.elapsed)
