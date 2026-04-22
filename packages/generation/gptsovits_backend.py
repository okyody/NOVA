"""
NOVA GPT-SoVITS Backend
========================
GPT-SoVITS voice cloning backend for custom character voices.

Supports 5-10 second reference audio cloning — ideal for
creating unique character-specific voices.

Usage:
  1. Place reference audio files in the voices/ directory
  2. Each character gets a subfolder with their reference audio
  3. The backend auto-selects the best reference based on emotion
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import AsyncIterator

import httpx

from packages.generation.voice_pipeline import ProsodyParams, TTSBackend

log = logging.getLogger("nova.generation.gptsovits")


class GPTSoVITSBackend(TTSBackend):
    """
    GPT-SoVITS voice cloning backend.

    Calls the local GPT-SoVITS WebAPI (default port 9880).
    Each character can have multiple reference audio files for
    different emotional tones.
    """

    def __init__(
        self,
        api_url: str = "http://localhost:9880",
        voices_dir: str = "voices",
        default_speaker: str = "nova",
    ) -> None:
        self._url = api_url
        self._voices_dir = Path(voices_dir)
        self._default_speaker = default_speaker

    async def synthesize(
        self,
        text: str,
        voice: str = "default",
        prosody: ProsodyParams = ProsodyParams(),
    ) -> AsyncIterator[bytes]:
        """Synthesize speech using GPT-SoVITS."""
        speaker = voice if voice != "zh-CN-XiaoyiNeural" else self._default_speaker
        ref_audio = self._find_reference(speaker)

        payload: dict = {
            "text": text,
            "refer_wav_path": str(ref_audio) if ref_audio else "",
            "prompt_language": "zh",
            "text_language": "zh",
        }

        # Adjust speed from prosody
        speed = 1.0
        if prosody.rate and prosody.rate.endswith("%"):
            try:
                speed = 1.0 + float(prosody.rate.rstrip("%")) / 100
            except ValueError:
                pass
        payload["speed"] = speed

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                async with client.stream(
                    "POST", f"{self._url}/tts", json=payload
                ) as resp:
                    resp.raise_for_status()
                    async for chunk in resp.aiter_bytes(4096):
                        yield chunk
        except httpx.ConnectError:
            log.error("GPT-SoVITS not available at %s", self._url)
        except Exception as exc:
            log.error("GPT-SoVITS synthesis failed: %s", exc)

    def _find_reference(self, speaker: str) -> Path | None:
        """Find the best reference audio for a speaker."""
        speaker_dir = self._voices_dir / speaker
        if speaker_dir.exists():
            # Prefer emotion-specific references
            for ext in (".wav", ".mp3", ".flac"):
                refs = list(speaker_dir.glob(f"*{ext}"))
                if refs:
                    return refs[0]  # Return first available
        # Fallback to default
        default_dir = self._voices_dir / self._default_speaker
        if default_dir.exists():
            for ext in (".wav", ".mp3", ".flac"):
                refs = list(default_dir.glob(f"*{ext}"))
                if refs:
                    return refs[0]
        return None
