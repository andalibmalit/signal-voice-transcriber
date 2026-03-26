"""WebSocket reconnection after drop."""

from __future__ import annotations

import pytest

from .conftest import BotHandle, make_voice_envelope

pytestmark = [pytest.mark.e2e]


async def test_reconnects_after_ws_drop(bot: BotHandle, audio_fixtures) -> None:
    """After the WebSocket is forcibly closed, the bot reconnects and transcribes."""
    # Drop the connection
    await bot.server.drop_websocket()
    assert bot.server.connection_count == 0

    # Wait for bot to reconnect (backoff starts at 1s)
    await bot.server.wait_for_connection(timeout=10)
    assert bot.server.connection_count == 1

    # Verify transcription still works after reconnection
    bot.server.attachment_map["att_001"] = audio_fixtures["short_2s"]
    envelope = make_voice_envelope(source="+11111111111", timestamp=5000)
    await bot.server.inject_envelope(envelope)

    msgs = await bot.server.wait_for_messages(1, timeout=15)
    assert msgs[0]["recipients"] == ["+11111111111"]
    assert "test" in msgs[0]["message"].lower()


async def test_backoff_resets_after_successful_reconnect(
    bot: BotHandle, audio_fixtures,
) -> None:
    """After reconnecting, the backoff resets so the next drop reconnects quickly."""
    # First drop + reconnect
    await bot.server.drop_websocket()
    await bot.server.wait_for_connection(timeout=10)

    # Second drop + reconnect (should still be fast since backoff reset)
    await bot.server.drop_websocket()
    await bot.server.wait_for_connection(timeout=10)

    # Verify it works
    bot.server.attachment_map["att_001"] = audio_fixtures["short_2s"]
    envelope = make_voice_envelope(source="+11111111111", timestamp=6000)
    await bot.server.inject_envelope(envelope)

    msgs = await bot.server.wait_for_messages(1, timeout=15)
    assert msgs[0]["recipients"] == ["+11111111111"]
    assert "test" in msgs[0]["message"].lower()
