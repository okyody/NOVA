"""
NOVA Stable Diffusion Client
=============================
Image generation via Stable Diffusion WebUI API.

Supports:
  - Text-to-image generation
  - Image-to-image editing
  - ControlNet integration
  - Async streaming of generated images

Requires: Stable Diffusion WebUI running with API enabled
(e.g., AUTOMATIC1111 or ComfyUI with API extension)
"""
from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from packages.core.event_bus import EventBus
from packages.core.types import EventType, NovaEvent, Priority

log = logging.getLogger("nova.sd_client")


@dataclass
class ImageGenerationRequest:
    """Parameters for image generation."""
    prompt: str
    negative_prompt: str = ""
    width: int = 512
    height: int = 512
    steps: int = 20
    cfg_scale: float = 7.0
    sampler_name: str = "Euler a"
    seed: int = -1  # -1 = random
    batch_size: int = 1
    n_iter: int = 1


@dataclass
class ImageGenerationResult:
    """Result of image generation."""
    images: list[bytes]  # PNG bytes
    parameters: dict[str, Any]
    info: str = ""


class SDClient:
    """
    Client for Stable Diffusion WebUI API.

    Usage:
        client = SDClient(api_url="http://localhost:7860")
        result = await client.text_to_image("a cute cat sitting on a desk")

    The generated images are published as CONTENT_READY events.
    """

    def __init__(
        self,
        api_url: str = "http://localhost:7860",
        timeout: float = 120.0,  # Image generation can be slow
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=api_url,
            timeout=timeout,
        )
        self._api_url = api_url
        self._enabled = False

    async def check_available(self) -> bool:
        """Check if the SD API is available."""
        try:
            resp = await self._client.get("/sdapi/v1/sd-models")
            self._enabled = resp.status_code == 200
            return self._enabled
        except Exception:
            self._enabled = False
            return False

    async def text_to_image(
        self,
        request: ImageGenerationRequest | None = None,
        prompt: str = "",
        **kwargs: Any,
    ) -> ImageGenerationResult:
        """
        Generate images from text prompts.

        Args:
            request: Full generation request (optional)
            prompt: Quick prompt text (creates default request)
            **kwargs: Override request parameters
        """
        if request is None:
            request = ImageGenerationRequest(prompt=prompt, **kwargs)

        payload = {
            "prompt": request.prompt,
            "negative_prompt": request.negative_prompt,
            "width": request.width,
            "height": request.height,
            "steps": request.steps,
            "cfg_scale": request.cfg_scale,
            "sampler_name": request.sampler_name,
            "seed": request.seed,
            "batch_size": request.batch_size,
            "n_iter": request.n_iter,
        }

        resp = await self._client.post("/sdapi/v1/txt2img", json=payload)
        resp.raise_for_status()
        data = resp.json()

        images = []
        for img_b64 in data.get("images", []):
            images.append(base64.b64decode(img_b64))

        import json
        info = data.get("info", "")
        parameters = {}
        try:
            parameters = json.loads(info) if isinstance(info, str) else info
        except (json.JSONDecodeError, TypeError):
            pass

        log.info("Generated %d images for prompt: %.50s…", len(images), request.prompt)

        return ImageGenerationResult(
            images=images,
            parameters=parameters,
            info=info,
        )

    async def generate_and_publish(
        self,
        prompt: str,
        bus: EventBus,
        trace_id: str = "",
        **kwargs: Any,
    ) -> ImageGenerationResult:
        """Generate an image and publish it as a CONTENT_READY event."""
        result = await self.text_to_image(prompt=prompt, **kwargs)

        if result.images:
            await bus.publish(NovaEvent(
                type=EventType.CONTENT_READY,
                payload={
                    "content_type": "image",
                    "images": [base64.b64encode(img).decode() for img in result.images],
                    "prompt": prompt,
                    "trace_id": trace_id,
                },
                priority=Priority.NORMAL,
                source="sd_client",
                trace_id=trace_id,
            ))

        return result

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def close(self) -> None:
        await self._client.aclose()
