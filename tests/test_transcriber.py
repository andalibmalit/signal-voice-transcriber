import asyncio
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

from signal_transcriber.transcriber import transcribe, _convert_to_m4a


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

    with patch("signal_transcriber.transcriber._get_client", return_value=mock_client), \
         patch("builtins.open", mock_open(read_data=b"audio data")):
        result = asyncio.run(transcribe(Path("/tmp/test.m4a"), config))

    assert result == "Hello world"
    call_kwargs = mock_client.audio.transcriptions.create.call_args[1]
    assert call_kwargs["model"] == "whisper-1"
    assert call_kwargs["response_format"] == "text"


def test_transcribe_converts_non_standard_format(config):
    mock_client = MagicMock()
    mock_client.audio.transcriptions.create.return_value = "Transcribed"

    with patch("signal_transcriber.transcriber._get_client", return_value=mock_client), \
         patch("signal_transcriber.transcriber._convert_to_m4a", return_value=Path("/tmp/converted.m4a")) as mock_convert, \
         patch("builtins.open", mock_open(read_data=b"audio")), \
         patch.object(Path, "exists", return_value=True), \
         patch.object(Path, "unlink"):
        result = asyncio.run(transcribe(Path("/tmp/test.aac"), config))

    mock_convert.assert_called_once()
    assert result == "Transcribed"
