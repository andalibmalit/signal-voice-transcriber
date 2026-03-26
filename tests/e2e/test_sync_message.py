"""Sync message (Note to Self / linked device) -> transcription reply."""

from __future__ import annotations

import pytest

from .conftest import BotHandle, make_sync_envelope

pytestmark = [pytest.mark.e2e]


async def test_sync_message_replies_to_destination(bot: BotHandle, audio_fixtures) -> None:
    """syncMessage.sentMessage should reply to the destination, not the bot itself."""
    bot.server.attachment_map["att_001"] = audio_fixtures["hello_10s"]

    envelope = make_sync_envelope(
        source="+10000000000",  # bot's own number
        destination="+11111111111",
        timestamp=1000,
    )
    await bot.server.inject_envelope(envelope)

    msgs = await bot.server.wait_for_messages(1)
    assert msgs[0]["recipients"] == ["+11111111111"]
    assert "test" in msgs[0]["message"].lower()
