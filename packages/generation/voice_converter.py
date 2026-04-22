"""
NOVA Voice Converter (so-vits-svc / DDSP-SVC)
===============================================
Optional post-processing step: TTS output → Voice Converter → Final audio.

Pipeline position: TTSBackend → VoiceConverter → AudioPlayer

Voice conversion adds 150-300ms latency but enables
character-specific voice styling beyond what TTS alone provides.
"""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator

import httpx

log = logging.getLogger("nova.generation.voice_converter")


class VoiceConverter:
    """
    Voice conversion using so-vits-svc or DDSP-SVC local API.

    This is an optional post-processing step in the audio pipeline.
    When enabled, TTS output is sent through a voice conversion
    model before being played.

    Config:
      api_url:  Local inference API URL
      model:    Voice model name to use
      enabled:  Whether voice conversion is active
    """

    def __init__(
        self,
        api_url: str = "http://localhost:7861",
        model: str = "default",
        enabled: bool = False,
    ) -> None:
        self._url = api_url
        self._model = model
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value
        log.info("Voice conversion %s", "enabled" if value else "disabled")

    async def convert(self, audio_bytes: bytes) -> bytes:
        """Convert audio bytes through the voice model."""
        if not self._enabled:
            return audio_bytes

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{self._url}/convert",
                    content=audio_bytes,
                    params={"model": self._model},
                )
                resp.raise_for_status()
                return resp.content
        except httpx.ConnectError:
            log.error("Voice converter not available at %s", self._url)
            return audio_bytes  # Pass through unchanged
        except Exception as exc:
            log.error("Voice conversion failed: %s, passing through", exc)
            return audio_bytes
