"""GPT formatting fallback behavior."""

from __future__ import annotations

import asyncio
import contextlib
import os
from unittest.mock import MagicMock

import pytest
from openai import OpenAI

import signal_transcriber.transcriber as transcriber_mod
import signal_transcriber.listener as listener_mod
from signal_transcriber.config import Config
from signal_transcriber.listener import listen
from .conftest import make_voice_envelope, requires_openai
from .mock_signal_server import MockSignalServer

pytestmark = [pytest.mark.e2e, requires_openai]


@pytest.fixture
async def server():
    s = MockSignalServer()
    await s.start()
    yield s
    await s.stop()


async def _start_bot(server, **config_overrides):
    defaults = dict(
        signal_api_url=server.url,
        signal_number="+10000000000",
        openai_api_key=os.environ["OPENAI_API_KEY"],
        transcribe_mode="all",
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
    for wt in list(listener_mod._workers.values()):
        wt.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await wt


async def test_gpt_failure_returns_raw_transcript(server, audio_fixtures) -> None:
    """When GPT formatting fails, the raw Whisper transcript is sent instead."""
    server.attachment_map["att_001"] = audio_fixtures["short_2s"]

    # Pre-create the real OpenAI client, then break only the GPT method.
    # Whisper (audio.transcriptions.create) is a separate method and still works.
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=30)
    client.chat = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError("Simulated GPT failure")
    transcriber_mod._openai_client = client

    shutdown, task = await _start_bot(server, enable_formatting=True)
    try:
        envelope = make_voice_envelope(source="+11111111111", timestamp=8000)
        await server.inject_envelope(envelope)

        msgs = await server.wait_for_messages(1, timeout=20)
        assert msgs[0]["recipients"] == ["+11111111111"]
        # formatter.py catches the exception and returns raw transcript
        assert "test" in msgs[0]["message"].lower()
    finally:
        await _stop_bot(shutdown, task)


async def test_formatting_disabled_skips_gpt(server, audio_fixtures) -> None:
    """When enable_formatting=False, GPT is never called."""
    server.attachment_map["att_001"] = audio_fixtures["short_2s"]
    transcriber_mod._openai_client = None

    shutdown, task = await _start_bot(server, enable_formatting=False)
    try:
        envelope = make_voice_envelope(source="+11111111111", timestamp=9000)
        await server.inject_envelope(envelope)

        msgs = await server.wait_for_messages(1, timeout=20)
        assert msgs[0]["recipients"] == ["+11111111111"]
        assert "test" in msgs[0]["message"].lower()
    finally:
        await _stop_bot(shutdown, task)
