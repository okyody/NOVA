"""
NOVA TTS Factory & Fallback Chain
===================================
Factory for creating TTS backends and a fallback chain
that automatically tries the next backend on failure.

Fallback order (configurable):
  1. Local inference (CosyVoice2 / GPT-SoVITS)
  2. Cloud (Azure / ElevenLabs)
  3. Free (edge-tts) — always available as last resort

The FallbackChain monitors health and automatically
switches to the next available backend.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import AsyncIterator

from packages.generation.voice_pipeline import (
    CosyVoice2Backend,
    EdgeTTSBackend,
    ProsodyParams,
    TTSBackend,
)

log = logging.getLogger("nova.generation.tts_factory")


# ─── Backend health tracking ────────────────────────────────────────────────────

@dataclass
class BackendHealth:
    name: str
    backend: TTSBackend
    healthy: bool = True
    consecutive_failures: int = 0
    last_success: float = 0.0
    last_failure: float = 0.0
    total_requests: int = 0
    total_failures: int = 0

    MAX_CONSECUTIVE_FAILURES = 3
    RECOVERY_TIME_S = 60  # wait before retrying a failed backend

    def record_success(self) -> None:
        self.healthy = True
        self.consecutive_failures = 0
        self.last_success = time.monotonic()
        self.total_requests += 1

    def record_failure(self) -> None:
        self.consecutive_failures += 1
        self.last_failure = time.monotonic()
        self.total_requests += 1
        self.total_failures += 1
        if self.consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
            self.healthy = False
            log.warning(
                "TTS backend '%s' marked unhealthy after %d consecutive failures",
                self.name, self.consecutive_failures,
            )

    def should_try(self) -> bool:
        """Check if this backend should be attempted."""
        if self.healthy:
            return True
        # Allow retry after recovery period
        if time.monotonic() - self.last_failure > self.RECOVERY_TIME_S:
            self.healthy = True
            self.consecutive_failures = 0
            log.info("TTS backend '%s' recovery attempt", self.name)
            return True
        return False


# ─── Fallback Chain ─────────────────────────────────────────────────────────────

class TTSFallbackChain(TTSBackend):
    """
    TTS backend that tries multiple backends in order,
    falling back to the next on failure.

    Usage:
        chain = TTSFallbackChain([
            ("cosyvoice2", CosyVoice2Backend()),
            ("edge_tts", EdgeTTSBackend()),
        ])
        async for chunk in chain.synthesize(text, voice, prosody):
            ...
    """

    def __init__(self, backends: list[tuple[str, TTSBackend]]) -> None:
        self._backends: list[BackendHealth] = [
            BackendHealth(name=name, backend=backend)
            for name, backend in backends
        ]

    async def synthesize(
        self,
        text: str,
        voice: str = "zh-CN-XiaoyiNeural",
        prosody: ProsodyParams = ProsodyParams(),
    ) -> AsyncIterator[bytes]:
        """Try backends in order, falling back on failure."""
        last_error: Exception | None = None

        for bh in self._backends:
            if not bh.should_try():
                continue

            try:
                # We need to consume the iterator to detect errors
                # but yield chunks as they come
                got_data = False
                async for chunk in bh.backend.synthesize(text, voice, prosody):
                    if not got_data:
                        got_data = True
                        bh.record_success()
                    yield chunk

                if got_data:
                    return  # Success — done

                # Empty response — treat as failure
                bh.record_failure()
                log.warning("TTS backend '%s' returned empty, trying next", bh.name)

            except Exception as exc:
                bh.record_failure()
                last_error = exc
                log.warning(
                    "TTS backend '%s' failed: %s, trying next",
                    bh.name, exc,
                )

        # All backends failed
        log.error("All TTS backends failed! Last error: %s", last_error)
        # Last resort: try edge-tts directly (always available)
        try:
            async for chunk in EdgeTTSBackend().synthesize(text, voice, prosody):
                yield chunk
        except Exception:
            log.critical("Even edge-tts failed — no TTS available!")

    def get_health(self) -> dict[str, dict]:
        """Get health status of all backends."""
        return {
            bh.name: {
                "healthy": bh.healthy,
                "consecutive_failures": bh.consecutive_failures,
                "total_requests": bh.total_requests,
                "total_failures": bh.total_failures,
            }
            for bh in self._backends
        }


# ─── TTS Factory ────────────────────────────────────────────────────────────────

def create_tts_backend(config: dict) -> TTSBackend:
    """
    Create a TTS backend or fallback chain from configuration.

    Config format:
        {
            "backend": "edge_tts" | "cosyvoice2" | "gptsovits" | "azure" | "elevenlabs" | "chain",
            "voice_id": "zh-CN-XiaoyiNeural",
            # Backend-specific options...
            "chain_order": ["cosyvoice2", "edge_tts"],  # for "chain" mode
        }
    """
    backend_type = config.get("backend", "edge_tts")

    if backend_type == "chain":
        return _create_chain(config)
    elif backend_type == "edge_tts":
        return EdgeTTSBackend()
    elif backend_type == "cosyvoice2":
        return CosyVoice2Backend(
            api_url=config.get("cosyvoice2_url", "http://localhost:7860"),
        )
    elif backend_type == "gptsovits":
        from .gptsovits_backend import GPTSoVITSBackend
        return GPTSoVITSBackend(
            api_url=config.get("gptsovits_url", "http://localhost:9880"),
            voices_dir=config.get("voices_dir", "voices"),
            default_speaker=config.get("speaker", "nova"),
        )
    elif backend_type == "azure":
        from .cloud_tts_backends import AzureTTSBackend
        return AzureTTSBackend(
            subscription_key=config.get("azure_key", ""),
            region=config.get("azure_region", "eastasia"),
            voice_name=config.get("azure_voice", "zh-CN-XiaoxiaoNeural"),
        )
    elif backend_type == "elevenlabs":
        from .cloud_tts_backends import ElevenLabsBackend
        return ElevenLabsBackend(
            api_key=config.get("elevenlabs_key", ""),
            voice_id=config.get("elevenlabs_voice", "21m00Tcm4TlvDq8ikWAM"),
        )
    else:
        log.warning("Unknown TTS backend '%s', falling back to edge-tts", backend_type)
        return EdgeTTSBackend()


def _create_chain(config: dict) -> TTSFallbackChain:
    """Create a fallback chain from config."""
    chain_order = config.get("chain_order", ["cosyvoice2", "edge_tts"])
    backends: list[tuple[str, TTSBackend]] = []

    for name in chain_order:
        sub_config = {**config, "backend": name}
        backend = create_tts_backend(sub_config)
        backends.append((name, backend))

    if not backends:
        backends.append(("edge_tts", EdgeTTSBackend()))

    return TTSFallbackChain(backends)
