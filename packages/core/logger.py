"""
NOVA Structured Logger
======================
Unified logging with structlog — single source of truth.

All modules should use:
    from packages.core.logger import get_logger
    log = get_logger("nova.component")
    log.info("event_processed", key=value, ...)
"""
from __future__ import annotations

import logging
import sys
from typing import Any

try:
    import structlog
    HAS_STRUCTLOG = True
except ImportError:
    HAS_STRUCTLOG = False


def setup_logging(
    level: str = "INFO",
    json_output: bool = False,
    log_file: str | None = None,
) -> None:
    """
    Configure NOVA unified logging.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        json_output: JSON format for production / log aggregation
        log_file: Optional file path for log output
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s │ %(levelname)-8s │ %(name)s │ %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
        force=True,
    )

    if not HAS_STRUCTLOG:
        return

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        # Add trace_id / span_id from OpenTelemetry if available
        _inject_trace_span,
    ]

    if json_output:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    for handler in handlers:
        handler.setFormatter(formatter)


def _inject_trace_span(logger: Any, method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Inject OpenTelemetry trace_id / span_id into log entries if available."""
    try:
        from opentelemetry import trace
        span = trace.get_current_span()
        ctx = span.get_span_context()
        if ctx.is_valid:
            event_dict["trace_id"] = format(ctx.trace_id, "032x")
            event_dict["span_id"] = format(ctx.span_id, "016x")
    except ImportError:
        pass
    except Exception:
        pass
    return event_dict


def get_logger(name: str, **kwargs: Any) -> Any:
    """
    Get a structured logger.

    Usage:
        log = get_logger("nova.orchestrator")
        log.info("pipeline_started", action="respond", viewer="user1")
    """
    if HAS_STRUCTLOG:
        return structlog.get_logger(name, **kwargs)
    return logging.getLogger(name)


def bind_trace_id(trace_id: str) -> None:
    """Bind trace_id to the current async context for log correlation."""
    if HAS_STRUCTLOG:
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(trace_id=trace_id)
