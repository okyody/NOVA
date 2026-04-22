"""
NOVA Circuit Breaker
====================
Prevents cascading failures when external services (LLM, TTS, Qdrant) go down.

States:
  CLOSED   — normal operation, requests pass through
  OPEN     — service failing, requests are rejected immediately
  HALF_OPEN — testing if service recovered, allows one request through

Usage:
    breaker = CircuitBreaker(name="llm", failure_threshold=3, recovery_timeout=30)

    async with breaker:
        result = await llm.complete(messages)

    # Or manual:
    if breaker.allow_request():
        try:
            result = await llm.complete(messages)
            breaker.record_success()
        except Exception:
            breaker.record_failure()
"""
from __future__ import annotations

import asyncio
import logging
import time
from enum import Enum
from typing import Any, Callable, Coroutine

log = logging.getLogger("nova.circuit_breaker")


class CircuitState(str, Enum):
    CLOSED   = "closed"
    OPEN     = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerOpen(Exception):
    """Raised when the circuit breaker is open and rejecting requests."""
    def __init__(self, name: str, state: CircuitState) -> None:
        self.name = name
        self.state = state
        super().__init__(f"Circuit breaker '{name}' is {state.value}, rejecting request")


class CircuitBreaker:
    """
    Circuit breaker for external service calls.

    Config:
      name: Identifier for logging
      failure_threshold: Consecutive failures before opening (default 5)
      recovery_timeout: Seconds before attempting half-open (default 30)
      success_threshold: Consecutive successes in half-open to close (default 2)
    """

    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        success_threshold: int = 2,
    ) -> None:
        self.name = name
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._success_threshold = success_threshold

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = 0.0
        self._last_state_change = time.monotonic()
        self._total_calls = 0
        self._total_failures = 0
        self._total_rejections = 0

    @property
    def state(self) -> CircuitState:
        """Current circuit state, with automatic transition from OPEN to HALF_OPEN."""
        if self._state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self._recovery_timeout:
                self._transition(CircuitState.HALF_OPEN)
        return self._state

    def allow_request(self) -> bool:
        """Check if a request should be allowed."""
        state = self.state
        if state == CircuitState.CLOSED:
            return True
        if state == CircuitState.HALF_OPEN:
            return True  # Allow one test request
        # OPEN
        self._total_rejections += 1
        return False

    def record_success(self) -> None:
        """Record a successful call."""
        self._total_calls += 1
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self._success_threshold:
                self._transition(CircuitState.CLOSED)
        elif self._state == CircuitState.CLOSED:
            self._failure_count = 0  # Reset on success

    def record_failure(self) -> None:
        """Record a failed call."""
        self._total_calls += 1
        self._total_failures += 1
        self._failure_count += 1
        self._last_failure_time = time.monotonic()

        if self._state == CircuitState.HALF_OPEN:
            self._transition(CircuitState.OPEN)
        elif self._failure_count >= self._failure_threshold:
            self._transition(CircuitState.OPEN)

    async def __aenter__(self) -> "CircuitBreaker":
        if not self.allow_request():
            raise CircuitBreakerOpen(self.name, self.state)
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if exc_type is not None:
            self.record_failure()
        else:
            self.record_success()

    def _transition(self, new_state: CircuitState) -> None:
        old_state = self._state
        self._state = new_state
        self._last_state_change = time.monotonic()

        if new_state == CircuitState.CLOSED:
            self._failure_count = 0
            self._success_count = 0
        elif new_state == CircuitState.HALF_OPEN:
            self._success_count = 0

        log.warning(
            "Circuit breaker '%s': %s → %s (failures=%d, total=%d)",
            self.name, old_state.value, new_state.value,
            self._failure_count, self._total_calls,
        )

    def stats(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "total_calls": self._total_calls,
            "total_failures": self._total_failures,
            "total_rejections": self._total_rejections,
        }

    async def call(
        self,
        fn: Callable[..., Coroutine[Any, Any, Any]],
        *args: Any,
        fallback: Callable[..., Coroutine[Any, Any, Any]] | None = None,
        **kwargs: Any,
    ) -> Any:
        """
        Execute a coroutine through the circuit breaker with optional fallback.
        """
        if not self.allow_request():
            if fallback:
                return await fallback(*args, **kwargs)
            raise CircuitBreakerOpen(self.name, self.state)

        try:
            result = await fn(*args, **kwargs)
            self.record_success()
            return result
        except Exception as e:
            self.record_failure()
            if fallback:
                log.warning("Circuit breaker '%s' call failed, using fallback: %s", self.name, e)
                return await fallback(*args, **kwargs)
            raise


# ─── Fallback Responder ─────────────────────────────────────────────────────

class FallbackResponder:
    """
    Generates safe fallback responses when the LLM circuit breaker is open.

    Strategies:
      - Static fallback: return a canned response
      - Echo fallback: reflect the user's message
      - Personality fallback: use character catchphrases
    """

    def __init__(self, character: Any = None) -> None:
        self._character = character
        self._static_fallbacks = [
            "嗯，让我想想……",
            "这个嘛……我需要考虑一下～",
            "稍等哦，我正在思考！",
            "哈哈，这个问题有点难倒我了～",
            "让我缓一下，马上回来！",
        ]
        self._fallback_index = 0

    async def get_fallback(self, trigger_text: str = "") -> str:
        """Get a fallback response when LLM is unavailable."""
        if self._character and hasattr(self._character, 'catchphrases') and self._character.catchphrases:
            import random
            if random.random() < 0.3:
                return random.choice(self._character.catchphrases)

        # Rotate through static fallbacks
        response = self._static_fallbacks[self._fallback_index % len(self._static_fallbacks)]
        self._fallback_index += 1
        return response
