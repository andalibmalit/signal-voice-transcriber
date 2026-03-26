"""Error handling: Whisper failure, non-voice audio, oversized file, text-only."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

import signal_transcriber.transcriber as transcriber_mod
from .conftest import (
    BotHandle,
    make_voice_envelope,
    make_text_envelope,
    make_audio_file_envelope,
    requires_openai,
)

pytestmark = [pytest.mark.e2e, requires_openai]


async def test_whisper_failure_sends_error_reply(bot: BotHandle, audio_fixtures) -> None:
    """When Whisper raises an exception, an error message is sent to the user."""
    bot.server.attachment_map["att_001"] = audio_fixtures["short_2s"]

    # Replace OpenAI client with one that fails on transcription
    mock_client = MagicMock()
    mock_client.audio.transcriptions.create.side_effect = RuntimeError("Whisper exploded")
    transcriber_mod._openai_client = mock_client

    envelope = make_voice_envelope(source="+11111111111", timestamp=10000)
    await bot.server.inject_envelope(envelope)

    msgs = await bot.server.wait_for_messages(1, timeout=10)
    assert msgs[0]["recipients"] == ["+11111111111"]
    assert "could not transcribe" in msgs[0]["message"].lower()


async def test_text_message_does_not_trigger_transcription(bot: BotHandle) -> None:
    """A plain text message should NOT produce any reply."""
    envelope = make_text_envelope(
        source="+11111111111", timestamp=11000, message="Hello world",
    )
    await bot.server.inject_envelope(envelope)

    with pytest.raises(asyncio.TimeoutError):
        await bot.server.wait_for_messages(1, timeout=3)
    assert len(bot.server.sent_messages) == 0


async def test_audio_file_with_filename_not_transcribed(bot: BotHandle) -> None:
    """An audio attachment with a filename (not a voice note) should NOT trigger."""
    envelope = make_audio_file_envelope(
        source="+11111111111", timestamp=12000,
        attachment_id="att_002", filename="song.mp3",
    )
    await bot.server.inject_envelope(envelope)

    with pytest.raises(asyncio.TimeoutError):
        await bot.server.wait_for_messages(1, timeout=3)
    assert len(bot.server.sent_messages) == 0


async def test_oversized_attachment_skipped(bot: BotHandle) -> None:
    """A voice attachment exceeding max_audio_size_mb should be silently skipped."""
    # Config default max is 25 MB = 26_214_400 bytes.
    # Create an envelope claiming the attachment is 30 MB.
    envelope = make_voice_envelope(
        source="+11111111111", timestamp=13000,
        attachment_id="att_big", size=30 * 1024 * 1024,
    )
    await bot.server.inject_envelope(envelope)

    with pytest.raises(asyncio.TimeoutError):
        await bot.server.wait_for_messages(1, timeout=3)
    assert len(bot.server.sent_messages) == 0
    # The attachment should NOT have been downloaded
    assert "att_big" not in bot.server.attachment_requests
