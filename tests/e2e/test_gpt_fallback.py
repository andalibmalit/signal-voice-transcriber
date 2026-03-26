"""GPT formatting fallback behavior."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import signal_transcriber.formatter as formatter_mod
from .conftest import make_voice_envelope, start_bot, stop_bot
from .mock_signal_server import MockSignalServer

pytestmark = [pytest.mark.e2e]


async def test_gpt_failure_returns_raw_transcript(
    mock_signal_server: MockSignalServer, audio_fixtures,
) -> None:
    """When GPT formatting fails, the raw Whisper transcript is sent instead."""
    mock_signal_server.attachment_map["att_001"] = audio_fixtures["short_2s"]

    _, shutdown, task, patches = await start_bot(
        mock_signal_server, enable_formatting=True, openai_api_key="dummy-key",
    )

    # Break only the GPT method — transcription uses real LocalWhisperBackend.
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = RuntimeError("Simulated GPT failure")
    formatter_mod._openai_client = mock_client
    try:
        envelope = make_voice_envelope(source="+11111111111", timestamp=8000)
        await mock_signal_server.inject_envelope(envelope)

        msgs = await mock_signal_server.wait_for_messages(1, timeout=20)
        assert msgs[0]["recipients"] == ["+11111111111"]
        # formatter.py catches the exception and returns raw transcript
        assert "test" in msgs[0]["message"].lower()
    finally:
        await stop_bot(shutdown, task, patches)


async def test_formatting_disabled_skips_gpt(
    mock_signal_server: MockSignalServer, audio_fixtures,
) -> None:
    """When enable_formatting=False, GPT is never called."""
    mock_signal_server.attachment_map["att_001"] = audio_fixtures["short_2s"]

    _, shutdown, task, patches = await start_bot(mock_signal_server, enable_formatting=False)

    # Plant a mock that would explode if GPT were called
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = AssertionError(
        "GPT should not be called when formatting is disabled"
    )
    formatter_mod._openai_client = mock_client
    try:
        envelope = make_voice_envelope(source="+11111111111", timestamp=9000)
        await mock_signal_server.inject_envelope(envelope)

        msgs = await mock_signal_server.wait_for_messages(1, timeout=20)
        assert msgs[0]["recipients"] == ["+11111111111"]
        assert "test" in msgs[0]["message"].lower()
        mock_client.chat.completions.create.assert_not_called()
    finally:
        await stop_bot(shutdown, task, patches)
