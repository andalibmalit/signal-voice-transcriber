"""Self-tests for the mock signal-cli-rest-api server."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import aiohttp
import pytest

from .mock_signal_server import MockSignalServer


pytestmark = pytest.mark.e2e


@pytest.fixture
async def server():
    srv = MockSignalServer()
    await srv.start()
    yield srv
    await srv.stop()


async def test_server_starts_and_returns_url(server: MockSignalServer) -> None:
    assert server.url.startswith("http://127.0.0.1:")
    port = int(server.url.split(":")[-1])
    assert port > 0


async def test_websocket_connects(server: MockSignalServer) -> None:
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(f"{server.ws_url}/v1/receive/+10000000000") as ws:
            await server.wait_for_connection(timeout=2)
            assert server.connection_count == 1
            assert not ws.closed


async def test_inject_envelope(server: MockSignalServer) -> None:
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(f"{server.ws_url}/v1/receive/+10000000000") as ws:
            await server.wait_for_connection(timeout=2)

            envelope = {"source": "+11111111111", "timestamp": 1000}
            await server.inject_envelope(envelope)

            msg = await asyncio.wait_for(ws.receive_str(), timeout=2)
            data = json.loads(msg)
            assert data["envelope"]["source"] == "+11111111111"
            assert data["envelope"]["timestamp"] == 1000


async def test_send_records_payload(server: MockSignalServer) -> None:
    payload = {"message": "Hello", "number": "+10000000000", "recipients": ["+11111111111"]}
    async with aiohttp.ClientSession() as session:
        resp = await session.post(f"{server.url}/v2/send", json=payload)
        assert resp.status == 200

    msgs = await server.wait_for_messages(1, timeout=2)
    assert len(msgs) == 1
    assert msgs[0]["message"] == "Hello"
    assert msgs[0]["recipients"] == ["+11111111111"]


async def test_send_custom_status(server: MockSignalServer) -> None:
    server.next_send_status = 500
    async with aiohttp.ClientSession() as session:
        resp = await session.post(f"{server.url}/v2/send", json={"message": "fail"})
        assert resp.status == 500


async def test_attachment_serves_fixture(server: MockSignalServer, tmp_path: Path) -> None:
    fixture = tmp_path / "test.ogg"
    fixture.write_bytes(b"OggS fake audio data")
    server.attachment_map["att_001"] = fixture

    async with aiohttp.ClientSession() as session:
        resp = await session.get(f"{server.url}/v1/attachments/att_001")
        assert resp.status == 200
        body = await resp.read()
        assert body == b"OggS fake audio data"

    assert "att_001" in server.attachment_requests


async def test_attachment_404_for_unknown(server: MockSignalServer) -> None:
    async with aiohttp.ClientSession() as session:
        resp = await session.get(f"{server.url}/v1/attachments/nonexistent")
        assert resp.status == 404


async def test_drop_websocket_and_reconnect(server: MockSignalServer) -> None:
    async with aiohttp.ClientSession() as session:
        ws_endpoint = f"{server.ws_url}/v1/receive/+10000000000"

        # First connection
        ws1 = await session.ws_connect(ws_endpoint)
        await server.wait_for_connection(timeout=2)
        assert server.connection_count == 1

        # Drop it
        await server.drop_websocket()
        msg = await asyncio.wait_for(ws1.receive(), timeout=2)
        assert msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING)

        # Second connection
        ws2 = await session.ws_connect(ws_endpoint)
        await server.wait_for_connection(timeout=2)
        assert server.connection_count == 1
        await ws2.close()


async def test_wait_for_messages_timeout(server: MockSignalServer) -> None:
    with pytest.raises(asyncio.TimeoutError):
        await server.wait_for_messages(1, timeout=0.5)


async def test_clear_resets_state(server: MockSignalServer, tmp_path: Path) -> None:
    fixture = tmp_path / "test.ogg"
    fixture.write_bytes(b"data")
    server.attachment_map["att_001"] = fixture
    server.sent_messages.append({"message": "test"})
    server.attachment_requests.append("att_001")
    server.next_send_status = 500

    server.clear()

    assert server.sent_messages == []
    assert server.attachment_requests == []
    assert server.attachment_map == {}
    assert server.next_send_status == 200
