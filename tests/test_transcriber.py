import asyncio
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

import pytest

import signal_transcriber.transcriber as transcriber_mod
from signal_transcriber.transcriber import transcribe, _convert_to_m4a, get_openai_client


def test_convert_to_m4a_uses_overwrite_flag():
    with patch("signal_transcriber.transcriber.subprocess.run") as mock_run, \
         patch("signal_transcriber.transcriber.make_temp_path", return_value=Path("/tmp/out.m4a")):
        mock_run.return_value = MagicMock(returncode=0)
        _convert_to_m4a(Path("/tmp/input.aac"))

    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "ffmpeg"
    assert "-y" in cmd


def test_transcribe_calls_whisper(config):
    mock_client = MagicMock()
    mock_client.audio.transcriptions.create.return_value = "Hello world"

    with patch("signal_transcriber.transcriber.get_openai_client", return_value=mock_client), \
         patch("builtins.open", mock_open(read_data=b"audio data")):
        result = asyncio.run(transcribe(Path("/tmp/test.m4a"), config))

    assert result == "Hello world"
    call_kwargs = mock_client.audio.transcriptions.create.call_args[1]
    assert call_kwargs["model"] == "whisper-1"
    assert call_kwargs["response_format"] == "text"


def test_transcribe_converts_non_standard_format(config):
    mock_client = MagicMock()
    mock_client.audio.transcriptions.create.return_value = "Transcribed"

    with patch("signal_transcriber.transcriber.get_openai_client", return_value=mock_client), \
         patch("signal_transcriber.transcriber._convert_to_m4a", return_value=Path("/tmp/converted.m4a")) as mock_convert, \
         patch("builtins.open", mock_open(read_data=b"audio")), \
         patch.object(Path, "exists", return_value=True), \
         patch.object(Path, "unlink"):
        result = asyncio.run(transcribe(Path("/tmp/test.aac"), config))

    mock_convert.assert_called_once()
    assert result == "Transcribed"


def test_get_openai_client_passes_timeout():
    """get_openai_client passes the timeout parameter to the OpenAI constructor."""
    transcriber_mod._openai_client = None
    try:
        with patch("signal_transcriber.transcriber.OpenAI") as mock_cls:
            mock_cls.return_value = MagicMock()
            get_openai_client("test-key", timeout=60)
            mock_cls.assert_called_once_with(api_key="test-key", timeout=60)
    finally:
        transcriber_mod._openai_client = None


def test_get_openai_client_default_timeout():
    """get_openai_client uses 120s default timeout when none is specified."""
    transcriber_mod._openai_client = None
    try:
        with patch("signal_transcriber.transcriber.OpenAI") as mock_cls:
            mock_cls.return_value = MagicMock()
            get_openai_client("test-key")
            mock_cls.assert_called_once_with(api_key="test-key", timeout=120)
    finally:
        transcriber_mod._openai_client = None


def test_get_openai_client_caching():
    """Calling get_openai_client twice returns the same cached instance."""
    transcriber_mod._openai_client = None
    try:
        with patch("signal_transcriber.transcriber.OpenAI") as mock_cls:
            mock_cls.return_value = MagicMock()
            client1 = get_openai_client("test-key", timeout=60)
            client2 = get_openai_client("test-key", timeout=60)
            assert client1 is client2
            mock_cls.assert_called_once()
    finally:
        transcriber_mod._openai_client = None


def test_convert_to_m4a_cleans_up_on_failure():
    """_convert_to_m4a removes the temp file when ffmpeg fails."""
    mock_path = MagicMock(spec=Path)
    with patch("signal_transcriber.transcriber.make_temp_path", return_value=mock_path), \
         patch("signal_transcriber.transcriber.subprocess.run",
               side_effect=subprocess.CalledProcessError(1, "ffmpeg")), \
         pytest.raises(subprocess.CalledProcessError):
        _convert_to_m4a(Path("/tmp/input.aac"))

    mock_path.unlink.assert_called_once_with(missing_ok=True)
