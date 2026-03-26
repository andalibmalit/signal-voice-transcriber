"""Group voice message -> transcription reply to group."""

from __future__ import annotations

import pytest

from .conftest import BotHandle, make_voice_envelope

pytestmark = [pytest.mark.e2e]


async def test_group_voice_message_replies_to_group(bot: BotHandle, audio_fixtures) -> None:
    """Voice message in a group chat should reply to the group, not the sender."""
    bot.server.attachment_map["att_001"] = audio_fixtures["hello_10s"]

    envelope = make_voice_envelope(
        source="+11111111111", timestamp=1000,
        group_id="dGVzdGdyb3Vw",
    )
    await bot.server.inject_envelope(envelope)

    msgs = await bot.server.wait_for_messages(1)
    assert msgs[0]["recipients"] == ["group.dGVzdGdyb3Vw"]
    assert "test" in msgs[0]["message"].lower()
