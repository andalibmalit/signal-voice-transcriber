import asyncio
from unittest.mock import MagicMock, patch

from signal_transcriber.formatter import format_transcript, _SYSTEM_PROMPT


def test_format_calls_gpt(config):
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="Formatted text."))]
    )

    with patch("signal_transcriber.formatter._get_client", return_value=mock_client):
        result = asyncio.run(format_transcript("raw text", config))

    assert result == "Formatted text."
    call_kwargs = mock_client.chat.completions.create.call_args[1]
    assert call_kwargs["model"] == "gpt-4o-mini"
    assert call_kwargs["messages"][0]["content"] == _SYSTEM_PROMPT
    assert call_kwargs["messages"][1]["content"] == "raw text"


def test_format_fallback_on_error(config):
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = RuntimeError("API down")

    with patch("signal_transcriber.formatter._get_client", return_value=mock_client):
        result = asyncio.run(format_transcript("raw text", config))

    assert result == "raw text"
