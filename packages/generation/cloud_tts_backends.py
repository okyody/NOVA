"""
NOVA Azure TTS & ElevenLabs Backends
======================================
Cloud TTS fallback backends for when local inference is unavailable.

Fallback chain: Local → Azure TTS → ElevenLabs → edge-tts
"""
from __future__ import annotations

import logging
from typing import AsyncIterator

import httpx

from packages.generation.voice_pipeline import ProsodyParams, TTSBackend

log = logging.getLogger("nova.generation.cloud_tts")


class AzureTTSBackend(TTSBackend):
    """
    Azure Cognitive Services Speech TTS backend.

    Pros:
      - ~200ms latency
      - Good Chinese voice quality
      - SSML support for fine-grained prosody control

    Cons:
      - Requires Azure subscription
      - Pay per character
    """

    def __init__(
        self,
        subscription_key: str,
        region: str = "eastasia",
        voice_name: str = "zh-CN-XiaoxiaoNeural",
    ) -> None:
        self._key = subscription_key
        self._region = region
        self._voice = voice_name

    async def synthesize(
        self,
        text: str,
        voice: str = "",
        prosody: ProsodyParams = ProsodyParams(),
    ) -> AsyncIterator[bytes]:
        voice_name = voice if voice else self._voice
        url = f"https://{self._region}.tts.speech.microsoft.com/cognitiveservices/v1"

        # Build SSML with prosody
        ssml = (
            f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="zh-CN">'
            f'<voice name="{voice_name}">'
            f'<prosody rate="{prosody.rate}" pitch="{prosody.pitch}" volume="{prosody.volume}">'
            f'{text}'
            f'</prosody>'
            f'</voice>'
            f'</speak>'
        )

        headers = {
            "Ocp-Apim-Subscription-Key": self._key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": "raw-16khz-16bit-mono-pcm",
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                async with client.stream("POST", url, content=ssml, headers=headers) as resp:
                    resp.raise_for_status()
                    async for chunk in resp.aiter_bytes(4096):
                        yield chunk
        except Exception as exc:
            log.error("Azure TTS failed: %s", exc)


class ElevenLabsBackend(TTSBackend):
    """
    ElevenLabs TTS backend — highest quality, highest cost.

    Pros:
      - Best voice quality and naturalness
      - Voice cloning from short samples
      - Emotion/style control

    Cons:
      - Expensive ($0.30/1K chars for standard)
      - Higher latency (~300-500ms)
    """

    def __init__(
        self,
        api_key: str,
        voice_id: str = "21m00Tcm4TlvDq8ikWAM",  # Rachel default
        model: str = "eleven_multilingual_v2",
    ) -> None:
        self._key = api_key
        self._voice_id = voice_id
        self._model = model

    async def synthesize(
        self,
        text: str,
        voice: str = "",
        prosody: ProsodyParams = ProsodyParams(),
    ) -> AsyncIterator[bytes]:
        voice_id = voice if voice else self._voice_id
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"

        headers = {
            "xi-api-key": self._key,
            "Content-Type": "application/json",
            "Accept": "audio/raw",
        }

        # Map prosody to ElevenLabs voice settings
        stability = 0.5
        similarity_boost = 0.75
        if prosody.rate.endswith("%"):
            try:
                rate_val = float(prosody.rate.rstrip("%"))
                stability = max(0.0, min(1.0, 0.5 - rate_val / 200))
            except ValueError:
                pass

        payload = {
            "text": text,
            "model_id": self._model,
            "voice_settings": {
                "stability": stability,
                "similarity_boost": similarity_boost,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as resp:
                    resp.raise_for_status()
                    async for chunk in resp.aiter_bytes(4096):
                        yield chunk
        except Exception as exc:
            log.error("ElevenLabs TTS failed: %s", exc)
