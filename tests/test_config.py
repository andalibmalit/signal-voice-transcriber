import pytest
from unittest.mock import patch

from signal_transcriber.config import Config
from signal_transcriber.__main__ import main


def test_invalid_transcribe_mode_raises():
    with pytest.raises(ValueError, match="Invalid TRANSCRIBE_MODE 'invalid'"):
        Config(transcribe_mode="invalid")


def test_transcribe_mode_all_normalized():
    cfg = Config(transcribe_mode="ALL")
    assert cfg.transcribe_mode == "all"


def test_transcribe_mode_own_only_normalized():
    cfg = Config(transcribe_mode="Own_Only")
    assert cfg.transcribe_mode == "own_only"


def test_missing_signal_number_exits():
    with patch(
        "signal_transcriber.__main__.Config",
        return_value=Config(
            signal_number="",
            openai_api_key="test-key",
            transcribe_mode="own_only",
        ),
    ), patch("signal_transcriber.__main__.load_dotenv"), pytest.raises(
        SystemExit, match="SIGNAL_NUMBER environment variable is required"
    ):
        main()


def test_missing_openai_api_key_exits():
    with patch(
        "signal_transcriber.__main__.Config",
        return_value=Config(
            signal_number="+10000000000",
            openai_api_key="",
            transcribe_mode="own_only",
        ),
    ), patch("signal_transcriber.__main__.load_dotenv"), pytest.raises(
        SystemExit, match="OPENAI_API_KEY environment variable is required"
    ):
        main()


def test_missing_ffmpeg_exits():
    with patch(
        "signal_transcriber.__main__.Config",
        return_value=Config(
            signal_number="+10000000000",
            openai_api_key="test-key",
            transcribe_mode="own_only",
        ),
    ), patch("signal_transcriber.__main__.load_dotenv"), patch(
        "signal_transcriber.__main__.shutil"
    ) as mock_shutil, pytest.raises(
        SystemExit, match="ffmpeg not found on PATH"
    ):
        mock_shutil.which.return_value = None
        main()
