"""
NOVA Avatar Driver
===================
Drives a Live2D avatar via WebSocket connection.

The avatar runs in a browser (OBS Browser Source), and this driver
pushes expression/lip-sync commands to it over WebSocket.

Architecture:
  VoicePipeline → AVATAR_COMMAND event → AvatarDriver → WS → Browser

The browser-side Live2D renderer receives JSON commands and applies
them to the model in real-time.

Command format:
  {
    "type": "avatar_command",
    "expression": "smile",
    "mouth_open": 0.6,
    "eye_blink": 0.2,
    "head_tilt": -3.0,
    "blend_time_ms": 80
  }
"""
from __future__ import annotations

import asyncio
import hashlib
import base64
import json
import logging
import time
from typing import Any

from packages.core.event_bus import EventBus
from packages.core.types import EventType, NovaEvent, Priority

log = logging.getLogger("nova.generation.avatar_driver")


class AvatarDriver:
    """
    WebSocket server that drives a Live2D avatar renderer.

    Listens for AVATAR_COMMAND events and forwards them
    to all connected browser clients over WebSocket.

    Also handles:
      - Client connection/disconnection
      - Idle animation (breathing, blinking)
    """

    def __init__(
        self,
        bus: EventBus,
        ws_port: int = 8767,
        idle_blink_interval: float = 4.0,
    ) -> None:
        self._bus = bus
        self._ws_port = ws_port
        self._idle_blink_interval = idle_blink_interval

        self._clients: set = set()
        self._server: asyncio.Server | None = None
        self._running = False
        self._last_command_time = 0.0

    async def start(self) -> None:
        self._running = True
        self._bus.subscribe(
            EventType.AVATAR_COMMAND, self._on_command, sub_id="avatar_driver"
        )
        self._server = await asyncio.start_server(
            self._handle_client,
            host="0.0.0.0",
            port=self._ws_port,
        )
        asyncio.create_task(self._idle_loop(), name="nova.avatar.idle")
        log.info("Avatar driver started on WS port %d", self._ws_port)

    async def stop(self) -> None:
        self._running = False
        if self._server:
            self._server.close()
        for client in list(self._clients):
            try:
                client.close()
            except Exception:
                pass
        self._clients.clear()

    @property
    def client_count(self) -> int:
        return len(self._clients)

    # ── WebSocket client handler ────────────────────────────────────────────

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle a single WebSocket client connection."""
        try:
            # Read HTTP upgrade request
            request = await reader.read(4096)
            if b"Upgrade: websocket" not in request:
                writer.close()
                return

            # Extract Sec-WebSocket-Key
            key = b""
            for line in request.split(b"\r\n"):
                if line.lower().startswith(b"sec-websocket-key:"):
                    key = line.split(b":", 1)[1].strip()
                    break

            if not key:
                writer.close()
                return

            # Compute accept key
            accept = base64.b64encode(
                hashlib.sha1(key + b"258EAFA5-E914-47DA-95CA-5ABFAB0B5B5F").digest()
            ).decode()

            # Send upgrade response
            response = (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
            ).encode()
            writer.write(response)
            await writer.drain()

            self._clients.add(writer)
            log.info("Avatar client connected (total: %d)", len(self._clients))

            # Keep connection alive
            try:
                while self._running:
                    data = await reader.read(4096)
                    if not data:
                        break
            except (ConnectionError, asyncio.CancelledError):
                pass
            finally:
                self._clients.discard(writer)
                try:
                    writer.close()
                except Exception:
                    pass
                log.info("Avatar client disconnected (total: %d)", len(self._clients))

        except Exception as exc:
            log.debug("Avatar client error: %s", exc)

    async def _broadcast(self, message: dict) -> None:
        """Send a message to all connected clients."""
        if not self._clients:
            return

        payload = json.dumps(message)
        frame = self._encode_ws_frame(payload)

        dead_clients = set()
        for client in self._clients:
            try:
                client.write(frame)
                await client.drain()
            except ConnectionError:
                dead_clients.add(client)

        for client in dead_clients:
            self._clients.discard(client)
            try:
                client.close()
            except Exception:
                pass

    @staticmethod
    def _encode_ws_frame(data: str, opcode: int = 1) -> bytes:
        """Encode a WebSocket text frame."""
        payload = data.encode("utf-8")
        frame = bytearray()
        frame.append(0x80 | opcode)  # FIN + opcode

        length = len(payload)
        if length < 126:
            frame.append(length)
        elif length < 65536:
            frame.append(126)
            frame.extend(length.to_bytes(2, "big"))
        else:
            frame.append(127)
            frame.extend(length.to_bytes(8, "big"))

        frame.extend(payload)
        return bytes(frame)

    # ── Event handlers ──────────────────────────────────────────────────────

    async def _on_command(self, event: NovaEvent) -> None:
        """Forward AVATAR_COMMAND events to all clients."""
        self._last_command_time = time.monotonic()
        await self._broadcast({
            "type": "avatar_command",
            **event.payload,
        })

    # ── Idle animation ──────────────────────────────────────────────────────

    async def _idle_loop(self) -> None:
        """Generate idle animations (blinking) when not actively speaking."""
        blink_timer = 0.0

        while self._running:
            await asyncio.sleep(0.1)

            now = time.monotonic()
            silence = now - self._last_command_time

            # Only idle when not actively speaking
            if silence < 0.5:
                continue

            blink_timer += 0.1

            # Random blink
            if blink_timer >= self._idle_blink_interval:
                blink_timer = 0.0
                await self._broadcast({
                    "type": "avatar_command",
                    "expression": "blink",
                    "eye_blink": 1.0,
                    "blend_time_ms": 100,
                })
                await asyncio.sleep(0.15)
                await self._broadcast({
                    "type": "avatar_command",
                    "expression": "neutral",
                    "eye_blink": 0.15,
                    "blend_time_ms": 150,
                })
