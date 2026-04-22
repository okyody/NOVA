"""
NOVA OpenTelemetry Tracing
==========================
Distributed tracing for request correlation across LLM → Qdrant → Redis → TTS.

If opentelemetry is not installed, all operations are no-op.
"""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

log = logging.getLogger("nova.tracing")

# ─── Optional OpenTelemetry ──────────────────────────────────────────────────

try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    HAS_OTEL = True
except ImportError:
    HAS_OTEL = False


# ─── Tracer setup ────────────────────────────────────────────────────────────

_tracer: Any = None


def setup_tracing(
    service_name: str = "nova",
    endpoint: str = "http://localhost:4317",
    enabled: bool = False,
) -> Any:
    """
    Configure OpenTelemetry tracing.

    Args:
        service_name: Service name in traces
        endpoint: OTLP gRPC endpoint (e.g. Jaeger, Tempo, Collector)
        enabled: Enable tracing (requires opentelemetry packages)
    """
    global _tracer

    if not enabled or not HAS_OTEL:
        _tracer = None
        if enabled and not HAS_OTEL:
            log.warning(
                "Tracing enabled but opentelemetry not installed. "
                "Run: pip install opentelemetry-api opentelemetry-sdk "
                "opentelemetry-exporter-otlp-proto-grpc"
            )
        return None

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer(service_name)

    log.info("OpenTelemetry tracing enabled (endpoint=%s)", endpoint)
    return _tracer


def get_tracer() -> Any:
    """Get the global tracer instance (None if not configured)."""
    if HAS_OTEL and _tracer is None:
        # Return a no-op tracer
        return trace.get_tracer("nova")
    return _tracer


# ─── Convenience helpers ─────────────────────────────────────────────────────

@asynccontextmanager
async def traced_span(
    name: str,
    attributes: dict[str, Any] | None = None,
) -> AsyncIterator[Any]:
    """
    Context manager for a traced span.

    Usage:
        async with traced_span("llm.generate", model="qwen2.5") as span:
            result = await llm.generate(...)
    """
    tracer = get_tracer()
    if tracer is None:
        yield None
        return

    with tracer.start_as_current_span(name, attributes=attributes or {}) as span:
        try:
            yield span
        except Exception as e:
            if span and span.is_recording():
                span.set_status(trace.StatusCode.ERROR, str(e))
                span.record_exception(e)
            raise


def traced(name: str | None = None, **static_attrs: Any) -> Any:
    """
    Decorator for tracing async functions.

    Usage:
        @traced("orchestrator.pipeline", component="cognitive")
        async def pipeline(self, ...):
            ...
    """
    def decorator(func: Any) -> Any:
        span_name = name or f"{func.__module__}.{func.__qualname__}"

        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            tracer = get_tracer()
            if tracer is None:
                return await func(*args, **kwargs)

            with tracer.start_as_current_span(span_name, attributes=static_attrs) as span:
                try:
                    result = await func(*args, **kwargs)
                    return result
                except Exception as e:
                    if span and span.is_recording():
                        span.set_status(trace.StatusCode.ERROR, str(e))
                        span.record_exception(e)
                    raise

        wrapper.__name__ = func.__name__
        wrapper.__qualname__ = func.__qualname__
        wrapper.__doc__ = func.__doc__
        return wrapper

    return decorator


class TraceContext:
    """Helper to propagate trace context in event payloads."""

    @staticmethod
    def inject(payload: dict[str, Any]) -> dict[str, Any]:
        """Inject current trace_id and span_id into payload."""
        if not HAS_OTEL:
            return payload

        span = trace.get_current_span()
        ctx = span.get_span_context()
        if ctx.is_valid:
            payload["trace_id"] = format(ctx.trace_id, "032x")
            payload["span_id"] = format(ctx.span_id, "016x")
        return payload

    @staticmethod
    def extract(payload: dict[str, Any]) -> dict[str, str]:
        """Extract trace info from payload for logging."""
        return {
            "trace_id": payload.get("trace_id", ""),
            "span_id": payload.get("span_id", ""),
        }
