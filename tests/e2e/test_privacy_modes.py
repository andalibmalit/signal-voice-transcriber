"""Privacy / transcribe_mode filtering."""

from __future__ import annotations

import asyncio
import contextlib
import os

import pytest

import signal_transcriber.transcriber as transcriber_mod
import signal_transcriber.listener as listener_mod
from signal_transcriber.config import Config
from signal_transcriber.listener import listen
from .conftest import make_voice_envelope, requires_openai
from .mock_signal_server import MockSignalServer

pytestmark = [pytest.mark.e2e, requires_openai]

BOT_NUMBER = "+10000000000"
ALICE = "+11111111111"
BOB = "+12222222222"


async def _start_bot(server: MockSignalServer, **config_overrides):
    """Start a bot with custom config, return (shutdown, task)."""
    transcriber_mod._openai_client = None

    defaults = dict(
        signal_api_url=server.url,
        signal_number=BOT_NUMBER,
        openai_api_key=os.environ["OPENAI_API_KEY"],
        log_level="DEBUG",
        openai_timeout=30,
    )
    defaults.update(config_overrides)
    config = Config(**defaults)

    shutdown = asyncio.Event()
    task = asyncio.create_task(listen(config, _shutdown=shutdown))
    await server.wait_for_connection(timeout=5)
    return shutdown, task


async def _stop_bot(shutdown, task):
    shutdown.set()
    if not task.done():
        try:
            await asyncio.wait_for(task, timeout=5)
        except asyncio.TimeoutError:
            task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    for worker_task in list(listener_mod._workers.values()):
        worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker_task


@pytest.fixture
async def server():
    s = MockSignalServer()
    await s.start()
    yield s
    await s.stop()


async def test_own_only_transcribes_own_number(server, audio_fixtures) -> None:
    """own_only mode: bot's own number is transcribed."""
    server.attachment_map["att_001"] = audio_fixtures["short_2s"]
    shutdown, task = await _start_bot(server, transcribe_mode="own_only")

    try:
        envelope = make_voice_envelope(source=BOT_NUMBER, timestamp=1000)
        await server.inject_envelope(envelope)
        msgs = await server.wait_for_messages(1, timeout=15)
        assert msgs[0]["recipients"] == [BOT_NUMBER]
    finally:
        await _stop_bot(shutdown, task)


async def test_own_only_rejects_other_number(server, audio_fixtures) -> None:
    """own_only mode: messages from other numbers are NOT transcribed."""
    server.attachment_map["att_001"] = audio_fixtures["short_2s"]
    shutdown, task = await _start_bot(server, transcribe_mode="own_only")

    try:
        envelope = make_voice_envelope(source=ALICE, timestamp=1000)
        await server.inject_envelope(envelope)
        with pytest.raises(asyncio.TimeoutError):
            await server.wait_for_messages(1, timeout=3)
        assert len(server.sent_messages) == 0
    finally:
        await _stop_bot(shutdown, task)


async def test_allowlist_accepts_listed_number(server, audio_fixtures) -> None:
    """allowlist mode: numbers in the list are transcribed."""
    server.attachment_map["att_001"] = audio_fixtures["short_2s"]
    shutdown, task = await _start_bot(
        server, transcribe_mode="allowlist", allowed_numbers=[ALICE],
    )

    try:
        envelope = make_voice_envelope(source=ALICE, timestamp=1000)
        await server.inject_envelope(envelope)
        msgs = await server.wait_for_messages(1, timeout=15)
        assert msgs[0]["recipients"] == [ALICE]
    finally:
        await _stop_bot(shutdown, task)


async def test_allowlist_rejects_unlisted_number(server, audio_fixtures) -> None:
    """allowlist mode: numbers NOT in the list are NOT transcribed."""
    server.attachment_map["att_001"] = audio_fixtures["short_2s"]
    shutdown, task = await _start_bot(
        server, transcribe_mode="allowlist", allowed_numbers=[ALICE],
    )

    try:
        envelope = make_voice_envelope(source=BOB, timestamp=1000)
        await server.inject_envelope(envelope)
        with pytest.raises(asyncio.TimeoutError):
            await server.wait_for_messages(1, timeout=3)
        assert len(server.sent_messages) == 0
    finally:
        await _stop_bot(shutdown, task)
