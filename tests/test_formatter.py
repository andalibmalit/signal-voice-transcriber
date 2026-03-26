import asyncio
from unittest.mock import MagicMock, patch

from signal_transcriber.backends import Segment, TranscriptionResult
from signal_transcriber.formatter import (
    format_transcript,
    format_with_pauses,
    _SYSTEM_PROMPT,
    PAUSE_THRESHOLD,
)


# --- Existing tests (string input, legacy path) ---


def test_format_calls_gpt(config):
    config.enable_formatting = True
    config.openai_api_key = "test-key"

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="Formatted text."))]
    )

    with patch("signal_transcriber.formatter.get_openai_client", return_value=mock_client):
        result = asyncio.run(format_transcript("raw text", config))

    assert result == "Formatted text."
    call_kwargs = mock_client.chat.completions.create.call_args[1]
    assert call_kwargs["model"] == "gpt-4o-mini"
    assert call_kwargs["messages"][0]["content"] == _SYSTEM_PROMPT
    assert call_kwargs["messages"][1]["content"] == "raw text"


def test_format_fallback_on_error(config):
    config.enable_formatting = True
    config.openai_api_key = "test-key"

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = RuntimeError("API down")

    with patch("signal_transcriber.formatter.get_openai_client", return_value=mock_client):
        result = asyncio.run(format_transcript("raw text", config))

    assert result == "raw text"


def test_format_passes_timeout_to_client(config):
    config.enable_formatting = True
    config.openai_api_key = "test-key"

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="Formatted."))]
    )

    with patch("signal_transcriber.formatter.get_openai_client", return_value=mock_client) as mock_get:
        asyncio.run(format_transcript("raw text", config))

    mock_get.assert_called_once_with(config.openai_api_key, timeout=config.openai_timeout)


# --- Pause-based formatting tests ---


def test_format_with_pauses_inserts_breaks():
    result = TranscriptionResult(
        text="Hello world How are you",
        segments=[
            Segment(text="Hello world", start=0.0, end=2.0),
            Segment(text="How are you", start=5.0, end=7.0),  # 3s gap
        ],
        language="en",
    )
    formatted = format_with_pauses(result)
    assert formatted == "Hello world\n\nHow are you"


def test_format_with_pauses_no_break_on_short_gap():
    result = TranscriptionResult(
        text="Hello world How are you",
        segments=[
            Segment(text="Hello world", start=0.0, end=2.0),
            Segment(text="How are you", start=2.5, end=4.0),  # 0.5s gap
        ],
        language="en",
    )
    formatted = format_with_pauses(result)
    assert formatted == "Hello world How are you"


def test_format_with_pauses_single_segment():
    result = TranscriptionResult(
        text="Hello world",
        segments=[Segment(text="Hello world", start=0.0, end=2.0)],
        language="en",
    )
    formatted = format_with_pauses(result)
    assert formatted == "Hello world"


def test_format_with_pauses_no_segments():
    result = TranscriptionResult(text="Hello world", segments=None, language=None)
    formatted = format_with_pauses(result)
    assert formatted == "Hello world"


def test_format_with_pauses_multiple_paragraphs():
    result = TranscriptionResult(
        text="A B C",
        segments=[
            Segment(text="A", start=0.0, end=1.0),
            Segment(text="B", start=3.0, end=4.0),   # 2s gap -> break
            Segment(text="C", start=6.0, end=7.0),   # 2s gap -> break
        ],
        language="en",
    )
    formatted = format_with_pauses(result)
    assert formatted == "A\n\nB\n\nC"


# --- format_transcript with TranscriptionResult ---


def test_format_transcript_uses_pauses_when_no_key(config):
    config.enable_formatting = True  # formatting requested but no key available
    result = TranscriptionResult(
        text="Hello world How are you",
        segments=[
            Segment(text="Hello world", start=0.0, end=2.0),
            Segment(text="How are you", start=5.0, end=7.0),
        ],
        language="en",
    )
    formatted = asyncio.run(format_transcript(result, config))
    assert formatted == "Hello world\n\nHow are you"


def test_format_transcript_uses_pauses_when_formatting_disabled(config):
    config.enable_formatting = False
    result = TranscriptionResult(
        text="Hello world How are you",
        segments=[
            Segment(text="Hello world", start=0.0, end=2.0),
            Segment(text="How are you", start=5.0, end=7.0),
        ],
        language="en",
    )
    formatted = asyncio.run(format_transcript(result, config))
    assert formatted == "Hello world\n\nHow are you"


def test_format_transcript_returns_raw_text_without_segments_or_key(config):
    result = TranscriptionResult(text="raw text", segments=None, language=None)
    formatted = asyncio.run(format_transcript(result, config))
    assert formatted == "raw text"


def test_format_transcript_falls_back_on_gpt_failure(config):
    config.enable_formatting = True
    config.openai_api_key = "test-key"

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = RuntimeError("GPT down")

    result = TranscriptionResult(
        text="Hello world How are you",
        segments=[
            Segment(text="Hello world", start=0.0, end=2.0),
            Segment(text="How are you", start=5.0, end=7.0),
        ],
        language="en",
    )
    with patch("signal_transcriber.formatter.get_openai_client", return_value=mock_client):
        formatted = asyncio.run(format_transcript(result, config))

    # Falls back to pause-based formatting
    assert formatted == "Hello world\n\nHow are you"
