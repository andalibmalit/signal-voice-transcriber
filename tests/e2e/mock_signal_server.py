"""Mock signal-cli-rest-api server for e2e tests.

Provides WebSocket and REST endpoints matching the real signal-cli-rest-api,
with helpers for injecting envelopes, recording sent messages, and serving
audio fixture files.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from aiohttp import web, WSMsgType

logger = logging.getLogger(__name__)


class MockSignalServer:
    """In-process mock of signal-cli-rest-api."""

    def __init__(self) -> None:
        self.sent_messages: list[dict[str, Any]] = []
        self.attachment_map: dict[str, Path] = {}  # attachment_id -> fixture path
        self.attachment_requests: list[str] = []  # IDs that were requested
        self.next_send_status: int = 200

        self._ws_connections: list[web.WebSocketResponse] = []
        self._connection_event = asyncio.Event()
        self._message_condition = asyncio.Condition()
        self._attachment_event = asyncio.Event()

        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._url: str = ""

    @property
    def url(self) -> str:
        return self._url

    async def start(self, host: str = "127.0.0.1", port: int = 0) -> str:
        """Start the mock server. Returns base URL like 'http://127.0.0.1:54321'."""
        self._app = web.Application()
        self._app.router.add_get("/v1/receive/{number}", self._ws_handler)
        self._app.router.add_post("/v2/send", self._send_handler)
        self._app.router.add_get("/v1/attachments/{attachment_id}", self._attachment_handler)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, host, port)
        await self._site.start()

        # Extract the actual bound port
        sockets = self._site._server.sockets  # type: ignore[union-attr]
        actual_port = sockets[0].getsockname()[1]
        self._url = f"http://{host}:{actual_port}"
        logger.info("Mock signal server started at %s", self._url)
        return self._url

    async def stop(self) -> None:
        """Gracefully shut down the server."""
        for ws in list(self._ws_connections):
            await ws.close()
        self._ws_connections.clear()
        if self._runner:
            await self._runner.cleanup()
        logger.info("Mock signal server stopped")

    async def inject_envelope(self, envelope: dict[str, Any]) -> None:
        """Send a JSON envelope to all connected WebSocket clients."""
        data = json.dumps({"envelope": envelope})
        for ws in list(self._ws_connections):
            if not ws.closed:
                await ws.send_str(data)

    async def drop_websocket(self) -> None:
        """Forcibly close all WebSocket connections (for reconnection tests)."""
        for ws in list(self._ws_connections):
            await ws.close()
        self._ws_connections.clear()
        # Reset connection event so wait_for_connection() waits for a NEW connection
        self._connection_event = asyncio.Event()

    async def wait_for_connection(self, timeout: float = 5.0) -> None:
        """Block until at least one WebSocket client is connected."""
        await asyncio.wait_for(self._connection_event.wait(), timeout=timeout)

    async def wait_for_messages(self, count: int, timeout: float = 10.0) -> list[dict[str, Any]]:
        """Block until at least `count` messages have been sent, or timeout."""
        async with self._message_condition:
            await asyncio.wait_for(
                self._message_condition.wait_for(lambda: len(self.sent_messages) >= count),
                timeout=timeout,
            )
        return self.sent_messages[:count]

    async def wait_for_attachment_request(self, timeout: float = 10.0) -> None:
        """Block until at least one attachment has been requested."""
        await asyncio.wait_for(self._attachment_event.wait(), timeout=timeout)

    def clear(self) -> None:
        """Reset all recorded state between tests."""
        self.sent_messages.clear()
        self.attachment_requests.clear()
        self.attachment_map.clear()
        self.next_send_status = 200
        self._attachment_event = asyncio.Event()

    # --- aiohttp request handlers ---

    async def _ws_handler(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self._ws_connections.append(ws)
        self._connection_event.set()
        logger.debug("WebSocket client connected (total: %d)", len(self._ws_connections))

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    logger.debug("WS received: %s", msg.data[:200])
                elif msg.type == WSMsgType.ERROR:
                    break
        finally:
            self._ws_connections.remove(ws)
            logger.debug("WebSocket client disconnected (total: %d)", len(self._ws_connections))

        return ws

    async def _send_handler(self, request: web.Request) -> web.Response:
        payload = await request.json()
        self.sent_messages.append(payload)
        logger.debug("Recorded sent message #%d: %s", len(self.sent_messages), json.dumps(payload)[:200])

        async with self._message_condition:
            self._message_condition.notify_all()

        return web.json_response({}, status=self.next_send_status)

    async def _attachment_handler(self, request: web.Request) -> web.Response:
        attachment_id = request.match_info["attachment_id"]
        self.attachment_requests.append(attachment_id)
        self._attachment_event.set()

        fixture_path = self.attachment_map.get(attachment_id)
        if fixture_path is None or not fixture_path.exists():
            return web.Response(status=404, text="Attachment not found")

        return web.Response(
            body=fixture_path.read_bytes(),
            content_type="application/octet-stream",
        )
