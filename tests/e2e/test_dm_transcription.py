"""DM voice message -> transcription reply."""

from __future__ import annotations

import pytest

from .conftest import BotHandle, make_voice_envelope, requires_openai

pytestmark = [pytest.mark.e2e, requires_openai]


async def test_single_voice_message_transcribed(bot: BotHandle, audio_fixtures) -> None:
    """Inject a voice envelope, verify the bot replies with a transcription."""
    bot.server.attachment_map["att_001"] = audio_fixtures["hello_10s"]

    envelope = make_voice_envelope(source="+11111111111", timestamp=1000)
    await bot.server.inject_envelope(envelope)

    msgs = await bot.server.wait_for_messages(1)
    msg = msgs[0]
    assert msg["recipients"] == ["+11111111111"]
    # Fuzzy match — Whisper is nondeterministic but the fixture says "test"
    assert "test" in msg["message"].lower()
    assert msg["quote_timestamp"] == 1000
    assert msg["quote_author"] == "+11111111111"
    assert msg["quote_message"] == "\U0001f3a4 Voice message"


async def test_voice_note_flag_detected(bot: BotHandle, audio_fixtures) -> None:
    """voiceNote=True with audio/aac triggers transcription."""
    bot.server.attachment_map["att_001"] = audio_fixtures["short_2s"]

    envelope = make_voice_envelope(
        source="+11111111111", timestamp=2000,
        content_type="audio/aac", voice_note=True,
    )
    await bot.server.inject_envelope(envelope)

    msgs = await bot.server.wait_for_messages(1)
    assert msgs[0]["recipients"] == ["+11111111111"]
    assert "test" in msgs[0]["message"].lower()


async def test_audio_wildcard_content_type(bot: BotHandle, audio_fixtures) -> None:
    """audio/* without filename and voiceNote=False still triggers (fallback heuristic)."""
    bot.server.attachment_map["att_001"] = audio_fixtures["short_2s"]

    envelope = make_voice_envelope(
        source="+11111111111", timestamp=3000,
        content_type="audio/ogg", voice_note=False,
    )
    await bot.server.inject_envelope(envelope)

    msgs = await bot.server.wait_for_messages(1)
    assert msgs[0]["recipients"] == ["+11111111111"]
    assert "test" in msgs[0]["message"].lower()
