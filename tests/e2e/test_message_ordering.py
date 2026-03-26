"""Message ordering: per-recipient FIFO guarantee."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import signal_transcriber.transcriber as transcriber_mod
from .conftest import BotHandle, make_voice_envelope, requires_openai

pytestmark = [pytest.mark.e2e, requires_openai]


async def test_three_messages_same_sender_in_order(
    bot: BotHandle, audio_fixtures,
) -> None:
    """Three voice messages from the same sender are transcribed in FIFO order."""
    bot.server.attachment_map["att_A"] = audio_fixtures["short_2s"]
    bot.server.attachment_map["att_B"] = audio_fixtures["short_2s"]
    bot.server.attachment_map["att_C"] = audio_fixtures["short_2s"]

    for i, att_id in enumerate(["att_A", "att_B", "att_C"]):
        envelope = make_voice_envelope(
            source="+11111111111", timestamp=1000 + i,
            attachment_id=att_id,
        )
        await bot.server.inject_envelope(envelope)

    msgs = await bot.server.wait_for_messages(3, timeout=30)

    # All replies go to the same sender
    for m in msgs:
        assert m["recipients"] == ["+11111111111"]

    # quote_timestamp preserves injection order (per-recipient queue is FIFO)
    timestamps = [m["quote_timestamp"] for m in msgs]
    assert timestamps == [1000, 1001, 1002]


async def test_two_senders_interleave_correctly(
    bot: BotHandle, audio_fixtures,
) -> None:
    """Messages from two different senders are processed independently."""
    bot.server.attachment_map["att_1"] = audio_fixtures["short_2s"]
    bot.server.attachment_map["att_2"] = audio_fixtures["short_2s"]
    bot.server.attachment_map["att_3"] = audio_fixtures["short_2s"]
    bot.server.attachment_map["att_4"] = audio_fixtures["short_2s"]

    # Interleave: Alice, Bob, Alice, Bob
    for i, (source, att_id) in enumerate([
        ("+11111111111", "att_1"),
        ("+12222222222", "att_2"),
        ("+11111111111", "att_3"),
        ("+12222222222", "att_4"),
    ]):
        envelope = make_voice_envelope(
            source=source, timestamp=2000 + i,
            attachment_id=att_id,
        )
        await bot.server.inject_envelope(envelope)

    msgs = await bot.server.wait_for_messages(4, timeout=30)

    # Within each sender, order is preserved
    alice_msgs = [m for m in msgs if m["recipients"] == ["+11111111111"]]
    bob_msgs = [m for m in msgs if m["recipients"] == ["+12222222222"]]

    assert len(alice_msgs) == 2
    assert len(bob_msgs) == 2

    alice_ts = [m["quote_timestamp"] for m in alice_msgs]
    bob_ts = [m["quote_timestamp"] for m in bob_msgs]

    assert alice_ts == [2000, 2002]
    assert bob_ts == [2001, 2003]
