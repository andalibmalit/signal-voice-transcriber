"""Long transcript -> split into multiple replies."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from signal_transcriber.backends import TranscriptionResult
from signal_transcriber.utils import MAX_MESSAGE_LENGTH
import signal_transcriber.listener as listener_mod
from .conftest import BotHandle, make_voice_envelope

pytestmark = [pytest.mark.e2e]

# Long text guaranteed to exceed MAX_MESSAGE_LENGTH after prefix
LONG_TRANSCRIPT = "word " * (MAX_MESSAGE_LENGTH // 3)


async def test_long_transcript_splits_into_multiple_replies(
    mock_bot: BotHandle, audio_fixtures,
) -> None:
    """Transcript exceeding MAX_MESSAGE_LENGTH splits; first chunk is quoted, rest are not."""
    # Override mock backend to return a very long transcript
    mock_backend = AsyncMock()
    mock_backend.transcribe.return_value = TranscriptionResult(
        text=LONG_TRANSCRIPT, segments=None, language="en",
    )
    listener_mod._backend = mock_backend

    mock_bot.server.attachment_map["att_001"] = audio_fixtures["long_60s"]

    envelope = make_voice_envelope(source="+11111111111", timestamp=1000)
    await mock_bot.server.inject_envelope(envelope)

    msgs = await mock_bot.server.wait_for_messages(2)

    # First message: quoted reply
    assert msgs[0]["recipients"] == ["+11111111111"]
    assert msgs[0]["quote_timestamp"] == 1000

    # Second message: continuation without quote
    assert msgs[1]["recipients"] == ["+11111111111"]
    assert msgs[1].get("quote_timestamp", 0) == 0

    # All chunks together should contain the transcript content
    full_text = " ".join(m["message"] for m in msgs)
    assert "word" in full_text
