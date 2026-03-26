"""GPT formatting fallback behavior."""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest
from openai import OpenAI

import signal_transcriber.transcriber as transcriber_mod
from .conftest import make_voice_envelope, requires_openai, start_bot, stop_bot
from .mock_signal_server import MockSignalServer

pytestmark = [pytest.mark.e2e, requires_openai]


async def test_gpt_failure_returns_raw_transcript(
    mock_signal_server: MockSignalServer, audio_fixtures,
) -> None:
    """When GPT formatting fails, the raw Whisper transcript is sent instead."""
    mock_signal_server.attachment_map["att_001"] = audio_fixtures["short_2s"]

    shutdown, task = await start_bot(mock_signal_server, enable_formatting=True)

    # Pre-create the real OpenAI client, then break only the GPT method.
    # Whisper (audio.transcriptions.create) is a separate method and still works.
    # Set AFTER start_bot() since it resets _openai_client to None.
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=30)
    client.chat = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError("Simulated GPT failure")
    transcriber_mod._openai_client = client
    try:
        envelope = make_voice_envelope(source="+11111111111", timestamp=8000)
        await mock_signal_server.inject_envelope(envelope)

        msgs = await mock_signal_server.wait_for_messages(1, timeout=20)
        assert msgs[0]["recipients"] == ["+11111111111"]
        # formatter.py catches the exception and returns raw transcript
        assert "test" in msgs[0]["message"].lower()
    finally:
        await stop_bot(shutdown, task)


async def test_formatting_disabled_skips_gpt(
    mock_signal_server: MockSignalServer, audio_fixtures,
) -> None:
    """When enable_formatting=False, GPT is never called."""
    mock_signal_server.attachment_map["att_001"] = audio_fixtures["short_2s"]
    transcriber_mod._openai_client = None

    shutdown, task = await start_bot(mock_signal_server, enable_formatting=False)
    try:
        envelope = make_voice_envelope(source="+11111111111", timestamp=9000)
        await mock_signal_server.inject_envelope(envelope)

        msgs = await mock_signal_server.wait_for_messages(1, timeout=20)
        assert msgs[0]["recipients"] == ["+11111111111"]
        assert "test" in msgs[0]["message"].lower()
    finally:
        await stop_bot(shutdown, task)
