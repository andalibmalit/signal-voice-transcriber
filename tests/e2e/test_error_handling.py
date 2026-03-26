"""Error handling: Whisper failure, non-voice audio, oversized file, text-only."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

import signal_transcriber.listener as listener_mod
from .conftest import (
    BotHandle,
    make_voice_envelope,
    make_text_envelope,
    make_audio_file_envelope,
)

pytestmark = [pytest.mark.e2e]


async def test_whisper_failure_sends_error_reply(mock_bot: BotHandle, audio_fixtures) -> None:
    """When the backend raises an exception, an error message is sent to the user."""
    mock_bot.server.attachment_map["att_001"] = audio_fixtures["short_2s"]

    # Override the mock backend to raise on transcribe
    mock_backend = AsyncMock()
    mock_backend.transcribe.side_effect = RuntimeError("Whisper exploded")
    listener_mod._backend = mock_backend

    envelope = make_voice_envelope(source="+11111111111", timestamp=10000)
    await mock_bot.server.inject_envelope(envelope)

    msgs = await mock_bot.server.wait_for_messages(1, timeout=10)
    assert msgs[0]["recipients"] == ["+11111111111"]
    assert "could not transcribe" in msgs[0]["message"].lower()


async def test_text_message_does_not_trigger_transcription(mock_bot: BotHandle) -> None:
    """A plain text message should NOT produce any reply."""
    envelope = make_text_envelope(
        source="+11111111111", timestamp=11000, message="Hello world",
    )
    await mock_bot.server.inject_envelope(envelope)

    with pytest.raises(asyncio.TimeoutError):
        await mock_bot.server.wait_for_messages(1, timeout=3)
    assert len(mock_bot.server.sent_messages) == 0


async def test_audio_file_with_filename_not_transcribed(mock_bot: BotHandle) -> None:
    """An audio attachment with a filename (not a voice note) should NOT trigger."""
    envelope = make_audio_file_envelope(
        source="+11111111111", timestamp=12000,
        attachment_id="att_002", filename="song.mp3",
    )
    await mock_bot.server.inject_envelope(envelope)

    with pytest.raises(asyncio.TimeoutError):
        await mock_bot.server.wait_for_messages(1, timeout=3)
    assert len(mock_bot.server.sent_messages) == 0


async def test_oversized_attachment_skipped(mock_bot: BotHandle) -> None:
    """A voice attachment exceeding max_audio_size_mb should be silently skipped."""
    envelope = make_voice_envelope(
        source="+11111111111", timestamp=13000,
        attachment_id="att_big", size=30 * 1024 * 1024,
    )
    await mock_bot.server.inject_envelope(envelope)

    with pytest.raises(asyncio.TimeoutError):
        await mock_bot.server.wait_for_messages(1, timeout=3)
    assert len(mock_bot.server.sent_messages) == 0
    assert "att_big" not in mock_bot.server.attachment_requests
