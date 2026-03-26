"""Long transcript -> split into multiple replies."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from signal_transcriber.utils import MAX_MESSAGE_LENGTH
import signal_transcriber.transcriber as transcriber_mod
from .conftest import BotHandle, make_voice_envelope

pytestmark = [pytest.mark.e2e]

# Long text guaranteed to exceed MAX_MESSAGE_LENGTH after formatting + prefix
LONG_TRANSCRIPT = "word " * (MAX_MESSAGE_LENGTH // 3)


async def test_long_transcript_splits_into_multiple_replies(
    mock_bot: BotHandle, audio_fixtures,
) -> None:
    """Transcript exceeding MAX_MESSAGE_LENGTH splits; first chunk is quoted, rest are not."""
    # Mock Whisper to return a very long transcript (real audio won't produce >1800 chars)
    mock_client = MagicMock()
    mock_client.audio.transcriptions.create.return_value = LONG_TRANSCRIPT

    def _format_side_effect(**kwargs):
        raw = kwargs["messages"][1]["content"]
        result = MagicMock()
        result.choices = [MagicMock(message=MagicMock(content=raw))]
        return result

    mock_client.chat.completions.create.side_effect = _format_side_effect
    transcriber_mod._openai_client = mock_client

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
