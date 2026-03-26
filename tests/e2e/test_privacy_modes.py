"""Privacy / transcribe_mode filtering."""

from __future__ import annotations

import asyncio

import pytest

from .conftest import make_voice_envelope, start_bot, stop_bot
from .mock_signal_server import MockSignalServer

pytestmark = [pytest.mark.e2e]

BOT_NUMBER = "+10000000000"
ALICE = "+11111111111"
BOB = "+12222222222"


async def test_own_only_transcribes_own_number(
    mock_signal_server: MockSignalServer, audio_fixtures,
) -> None:
    """own_only mode: bot's own number is transcribed."""
    mock_signal_server.attachment_map["att_001"] = audio_fixtures["short_2s"]
    _, shutdown, task, patches = await start_bot(mock_signal_server, transcribe_mode="own_only")

    try:
        envelope = make_voice_envelope(source=BOT_NUMBER, timestamp=1000)
        await mock_signal_server.inject_envelope(envelope)
        msgs = await mock_signal_server.wait_for_messages(1, timeout=15)
        assert msgs[0]["recipients"] == [BOT_NUMBER]
    finally:
        await stop_bot(shutdown, task, patches)


async def test_own_only_rejects_other_number(
    mock_signal_server: MockSignalServer, audio_fixtures,
) -> None:
    """own_only mode: messages from other numbers are NOT transcribed."""
    mock_signal_server.attachment_map["att_001"] = audio_fixtures["short_2s"]
    _, shutdown, task, patches = await start_bot(mock_signal_server, transcribe_mode="own_only")

    try:
        envelope = make_voice_envelope(source=ALICE, timestamp=1000)
        await mock_signal_server.inject_envelope(envelope)
        with pytest.raises(asyncio.TimeoutError):
            await mock_signal_server.wait_for_messages(1, timeout=3)
        assert len(mock_signal_server.sent_messages) == 0
    finally:
        await stop_bot(shutdown, task, patches)


async def test_allowlist_accepts_listed_number(
    mock_signal_server: MockSignalServer, audio_fixtures,
) -> None:
    """allowlist mode: numbers in the list are transcribed."""
    mock_signal_server.attachment_map["att_001"] = audio_fixtures["short_2s"]
    _, shutdown, task, patches = await start_bot(
        mock_signal_server, transcribe_mode="allowlist", allowed_numbers=[ALICE],
    )

    try:
        envelope = make_voice_envelope(source=ALICE, timestamp=1000)
        await mock_signal_server.inject_envelope(envelope)
        msgs = await mock_signal_server.wait_for_messages(1, timeout=15)
        assert msgs[0]["recipients"] == [ALICE]
    finally:
        await stop_bot(shutdown, task, patches)


async def test_allowlist_rejects_unlisted_number(
    mock_signal_server: MockSignalServer, audio_fixtures,
) -> None:
    """allowlist mode: numbers NOT in the list are NOT transcribed."""
    mock_signal_server.attachment_map["att_001"] = audio_fixtures["short_2s"]
    _, shutdown, task, patches = await start_bot(
        mock_signal_server, transcribe_mode="allowlist", allowed_numbers=[ALICE],
    )

    try:
        envelope = make_voice_envelope(source=BOB, timestamp=1000)
        await mock_signal_server.inject_envelope(envelope)
        with pytest.raises(asyncio.TimeoutError):
            await mock_signal_server.wait_for_messages(1, timeout=3)
        assert len(mock_signal_server.sent_messages) == 0
    finally:
        await stop_bot(shutdown, task, patches)
