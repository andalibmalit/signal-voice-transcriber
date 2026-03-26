"""Graceful shutdown: in-flight transcription completes before exit."""

from __future__ import annotations

import asyncio
import contextlib

import pytest

import signal_transcriber.listener as listener_mod
from .conftest import BotHandle, make_voice_envelope, requires_openai

pytestmark = [pytest.mark.e2e, requires_openai]


async def test_in_flight_transcription_completes_on_shutdown(
    bot: BotHandle, audio_fixtures,
) -> None:
    """When shutdown is signalled during transcription, the reply is still sent."""
    bot.server.attachment_map["att_001"] = audio_fixtures["hello_10s"]

    envelope = make_voice_envelope(source="+11111111111", timestamp=7000)
    await bot.server.inject_envelope(envelope)

    # Wait for the bot to start downloading the attachment
    await bot.server.wait_for_attachment_request(timeout=10)

    # Signal shutdown while processing is in flight
    bot.shutdown.set()

    # The listen() task should finish gracefully (sends sentinel to workers,
    # waits up to 30s for them)
    await asyncio.wait_for(bot.task, timeout=35)

    # The reply should still have been sent
    msgs = await bot.server.wait_for_messages(1, timeout=5)
    assert msgs[0]["recipients"] == ["+11111111111"]
    assert "test" in msgs[0]["message"].lower()
