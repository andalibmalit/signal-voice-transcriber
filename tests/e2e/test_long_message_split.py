"""Long transcript -> split into multiple replies."""

from __future__ import annotations

import pytest

from signal_transcriber.utils import MAX_MESSAGE_LENGTH
from .conftest import BotHandle, MockWhisper, make_voice_envelope

pytestmark = pytest.mark.e2e


async def test_long_transcript_splits_into_multiple_replies(
    bot: BotHandle, mock_openai: tuple, audio_fixtures,
) -> None:
    """Transcript exceeding MAX_MESSAGE_LENGTH splits; first chunk is quoted, rest are not."""
    _mock_client, whisper = mock_openai
    # Generate a transcript longer than MAX_MESSAGE_LENGTH after formatting + prefix
    long_text = "word " * (MAX_MESSAGE_LENGTH // 3)
    whisper.set_transcript(long_text)

    bot.server.attachment_map["att_001"] = audio_fixtures["long_60s"]

    envelope = make_voice_envelope(source="+11111111111", timestamp=1000)
    await bot.server.inject_envelope(envelope)

    msgs = await bot.server.wait_for_messages(2)

    # First message: quoted reply
    assert msgs[0]["recipients"] == ["+11111111111"]
    assert msgs[0]["quote_timestamp"] == 1000

    # Second message: continuation without quote
    assert msgs[1]["recipients"] == ["+11111111111"]
    assert msgs[1].get("quote_timestamp", 0) == 0

    # All chunks together should contain the transcript content
    full_text = " ".join(m["message"] for m in msgs)
    assert "word" in full_text
