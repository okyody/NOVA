"""
NOVA Health Monitor
===================
System health monitoring with memory leak detection.

Features:
  - Periodic health checks for all components
  - Memory usage tracking and leak detection
  - EventBus queue depth monitoring
  - Component liveness verification
  - Health report published as HEALTH_CHECK events
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

from packages.core.event_bus import EventBus
from packages.core.types import EventType, NovaEvent, Priority

log = logging.getLogger("nova.health_monitor")


@dataclass
class ComponentHealth:
    """Health status for a single component."""
    name: str
    healthy: bool = True
    latency_ms: float = 0.0
    error: str = ""
    last_check: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SystemHealth:
    """Overall system health report."""
    healthy: bool = True
    components: dict[str, ComponentHealth] = field(default_factory=dict)
    memory_mb: float = 0.0
    memory_delta_mb: float = 0.0
    queue_depth: int = 0
    uptime_s: float = 0.0
    timestamp: float = 0.0


class HealthMonitor:
    """
    Monitors system health and publishes periodic reports.

    Checks:
      - Component liveness (via check_fn callbacks)
      - Memory usage trend (leak detection)
      - EventBus queue depth (back-pressure)
      - Response latency (SLA tracking)
    """

    MEMORY_LEAK_THRESHOLD_MB = 50.0   # Alert if memory grows > 50MB between checks
    QUEUE_DEPTH_WARNING = 100
    QUEUE_DEPTH_CRITICAL = 500
    CHECK_INTERVAL_S = 30.0

    def __init__(
        self,
        bus: EventBus,
        check_interval_s: float = 30.0,
    ) -> None:
        self._bus = bus
        self._check_interval = check_interval_s
        self._checks: dict[str, Callable[[], Coroutine[Any, Any, ComponentHealth]]] = {}
        self._last_memory: float | None = None
        self._start_time = time.monotonic()
        self._running = False
        self._task: asyncio.Task | None = None
        self._last_report: SystemHealth | None = None

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(
            self._check_loop(), name="nova.health_monitor"
        )
        log.info("Health monitor started (interval=%ds)", self._check_interval)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()

    def register_check(
        self,
        name: str,
        check_fn: Callable[[], Coroutine[Any, Any, ComponentHealth]],
    ) -> None:
        """Register a component health check."""
        self._checks[name] = check_fn

    @property
    def last_report(self) -> SystemHealth | None:
        return self._last_report

    async def _check_loop(self) -> None:
        while self._running:
            try:
                report = await self.run_checks()
                self._last_report = report

                # Publish health event
                await self._bus.publish(NovaEvent(
                    type=EventType.HEALTH_CHECK,
                    payload={
                        "healthy": report.healthy,
                        "memory_mb": round(report.memory_mb, 1),
                        "memory_delta_mb": round(report.memory_delta_mb, 1),
                        "queue_depth": report.queue_depth,
                        "uptime_s": round(report.uptime_s, 1),
                        "components": {
                            k: {"healthy": v.healthy, "latency_ms": round(v.latency_ms, 1)}
                            for k, v in report.components.items()
                        },
                    },
                    priority=Priority.LOW,
                    source="health_monitor",
                ))

                if not report.healthy:
                    log.warning("Health check failed: %s",
                                [k for k, v in report.components.items() if not v.healthy])

            except Exception as exc:
                log.error("Health check error: %s", exc)

            await asyncio.sleep(self._check_interval)

    async def run_checks(self) -> SystemHealth:
        """Run all health checks and return a report."""
        import psutil
        import os

        process = psutil.Process(os.getpid())
        current_memory = process.memory_info().rss / (1024 * 1024)  # MB

        memory_delta = 0.0
        if self._last_memory is not None:
            memory_delta = current_memory - self._last_memory
        self._last_memory = current_memory

        # Check for memory leak
        if memory_delta > self.MEMORY_LEAK_THRESHOLD_MB:
            log.warning(
                "Potential memory leak detected: +%.1f MB (current: %.1f MB)",
                memory_delta, current_memory,
            )

        # Run component checks
        components: dict[str, ComponentHealth] = {}
        all_healthy = True

        for name, check_fn in self._checks.items():
            try:
                t0 = time.monotonic()
                health = await check_fn()
                health.latency_ms = (time.monotonic() - t0) * 1000
                health.last_check = time.monotonic()
                components[name] = health
                if not health.healthy:
                    all_healthy = False
            except Exception as exc:
                components[name] = ComponentHealth(
                    name=name, healthy=False, error=str(exc), last_check=time.monotonic()
                )
                all_healthy = False

        # Check queue depth
        bus_stats = self._bus.stats()
        queue_depth = bus_stats.get("queue_depth", 0)
        if queue_depth > self.QUEUE_DEPTH_CRITICAL:
            all_healthy = False
            log.error("EventBus queue depth critical: %d", queue_depth)
        elif queue_depth > self.QUEUE_DEPTH_WARNING:
            log.warning("EventBus queue depth high: %d", queue_depth)

        return SystemHealth(
            healthy=all_healthy,
            components=components,
            memory_mb=current_memory,
            memory_delta_mb=memory_delta,
            queue_depth=queue_depth,
            uptime_s=time.monotonic() - self._start_time,
            timestamp=time.monotonic(),
        )


class SimpleHealthCheck:
    """Helper to create simple component health checks."""

    @staticmethod
    def always_healthy(name: str) -> ComponentHealth:
        return ComponentHealth(name=name, healthy=True)

    @staticmethod
    def from_condition(name: str, condition: bool, error: str = "") -> ComponentHealth:
        return ComponentHealth(name=name, healthy=condition, error=error if not condition else "")

    @staticmethod
    async def check_component(component: Any, name: str) -> ComponentHealth:
        """Check a component by verifying it has a running state."""
        try:
            if hasattr(component, '_running') and not component._running:
                return ComponentHealth(name=name, healthy=False, error="not running")
            if hasattr(component, 'stats'):
                stats = component.stats() if not asyncio.iscoroutinefunction(component.stats) else await component.stats()
                return ComponentHealth(name=name, healthy=True, metadata=stats)
            return ComponentHealth(name=name, healthy=True)
        except Exception as e:
            return ComponentHealth(name=name, healthy=False, error=str(e))
