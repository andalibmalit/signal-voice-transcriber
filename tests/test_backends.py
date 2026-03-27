import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

import pytest

from signal_transcriber.config import Config


def _make_config(**overrides) -> Config:
    defaults = dict(
        signal_number="+10000000000",
        openai_api_key="test-key",
        whisper_model="small",
        transcribe_mode="own_only",
    )
    defaults.update(overrides)
    return Config(**defaults)


def _mock_faster_whisper():
    """Create a mock faster_whisper module with a working WhisperModel."""
    mock_fw = MagicMock()
    mock_segment = MagicMock()
    mock_segment.text = " Hello world "
    mock_segment.start = 0.0
    mock_segment.end = 2.5
    mock_info = MagicMock()
    mock_info.language = "en"
    mock_fw.WhisperModel.return_value.transcribe.return_value = (
        iter([mock_segment]),
        mock_info,
    )
    return mock_fw


# --- LocalWhisperBackend ---


async def test_local_backend_transcribes():
    mock_fw = _mock_faster_whisper()
    with patch.dict(sys.modules, {"faster_whisper": mock_fw}):
        from signal_transcriber.backends import LocalWhisperBackend, TranscriptionResult
        config = _make_config()
        backend = LocalWhisperBackend(config)
        result = await backend.transcribe(Path("/tmp/test.m4a"))

    assert isinstance(result, TranscriptionResult)
    assert result.text == "Hello world"
    assert len(result.segments) == 1
    assert result.segments[0].text == "Hello world"
    assert result.segments[0].start == 0.0
    assert result.segments[0].end == 2.5
    assert result.language == "en"
    await backend.close()


async def test_local_backend_model_loaded_once():
    mock_fw = _mock_faster_whisper()
    with patch.dict(sys.modules, {"faster_whisper": mock_fw}):
        from signal_transcriber.backends import LocalWhisperBackend
        config = _make_config()
        backend = LocalWhisperBackend(config)

        # Re-setup the mock to return a fresh iterator each call
        mock_model = mock_fw.WhisperModel.return_value
        mock_seg = MagicMock(text=" test ", start=0.0, end=1.0)
        mock_info = MagicMock(language="en")
        mock_model.transcribe.side_effect = [
            (iter([mock_seg]), mock_info),
            (iter([mock_seg]), mock_info),
        ]

        await backend.transcribe(Path("/tmp/a.m4a"))
        await backend.transcribe(Path("/tmp/b.m4a"))

    mock_fw.WhisperModel.assert_called_once()
    assert mock_model.transcribe.call_count == 2
    await backend.close()


async def test_local_backend_passes_config():
    mock_fw = _mock_faster_whisper()
    with patch.dict(sys.modules, {"faster_whisper": mock_fw}):
        from signal_transcriber.backends import LocalWhisperBackend
        config = _make_config(
            whisper_model="medium",
            whisper_device="auto",
            whisper_compute_type="float16",
            whisper_cpu_threads=8,
            whisper_model_dir="/custom/models",
        )
        backend = LocalWhisperBackend(config)
        await backend.transcribe(Path("/tmp/test.m4a"))

    mock_fw.WhisperModel.assert_called_once_with(
        "medium",
        device="auto",
        compute_type="float16",
        cpu_threads=8,
        download_root="/custom/models",
    )
    await backend.close()


async def test_local_backend_close():
    mock_fw = _mock_faster_whisper()
    with patch.dict(sys.modules, {"faster_whisper": mock_fw}):
        from signal_transcriber.backends import LocalWhisperBackend
        config = _make_config()
        backend = LocalWhisperBackend(config)
        with patch.object(backend._executor, "shutdown") as mock_shutdown:
            await backend.close()
        mock_shutdown.assert_called_once_with(wait=False)


# --- OpenAIWhisperBackend ---


async def test_openai_backend_transcribes():
    from signal_transcriber.backends import OpenAIWhisperBackend, TranscriptionResult
    config = _make_config(whisper_model="whisper-1")

    mock_client = MagicMock()
    mock_client.audio.transcriptions.create.return_value = "Hello world"

    with patch("openai.OpenAI", return_value=mock_client), \
         patch("builtins.open", mock_open(read_data=b"audio data")):
        backend = OpenAIWhisperBackend(config)
        result = await backend.transcribe(Path("/tmp/test.m4a"))

    assert isinstance(result, TranscriptionResult)
    assert result.text == "Hello world"
    assert result.segments is None
    assert result.language is None
    mock_client.audio.transcriptions.create.assert_called_once()
    call_kwargs = mock_client.audio.transcriptions.create.call_args[1]
    assert call_kwargs["model"] == "whisper-1"
    assert call_kwargs["response_format"] == "text"


async def test_openai_backend_converts_non_standard_format():
    from signal_transcriber.backends import OpenAIWhisperBackend
    config = _make_config(whisper_model="whisper-1")

    mock_client = MagicMock()
    mock_client.audio.transcriptions.create.return_value = "Transcribed"

    with patch("openai.OpenAI", return_value=mock_client), \
         patch("signal_transcriber.backends._convert_to_m4a", return_value=Path("/tmp/converted.m4a")) as mock_convert, \
         patch("builtins.open", mock_open(read_data=b"audio")), \
         patch.object(Path, "exists", return_value=True), \
         patch.object(Path, "unlink"):
        backend = OpenAIWhisperBackend(config)
        await backend.transcribe(Path("/tmp/test.aac"))

    mock_convert.assert_called_once()


# --- create_backend ---


async def test_create_backend_local():
    mock_fw = _mock_faster_whisper()
    with patch.dict(sys.modules, {"faster_whisper": mock_fw}):
        from signal_transcriber.backends import create_backend, LocalWhisperBackend
        config = _make_config(transcription_backend="local")
        backend = create_backend(config)
    assert isinstance(backend, LocalWhisperBackend)


async def test_create_backend_openai():
    from signal_transcriber.backends import create_backend, OpenAIWhisperBackend
    config = _make_config(transcription_backend="openai", whisper_model="whisper-1")
    backend = create_backend(config)
    assert isinstance(backend, OpenAIWhisperBackend)


async def test_create_backend_openai_no_key():
    from signal_transcriber.backends import create_backend
    config = _make_config(transcription_backend="openai", openai_api_key="")
    with pytest.raises(ValueError, match="requires OPENAI_API_KEY"):
        create_backend(config)


async def test_create_backend_local_rejects_openai_model():
    from signal_transcriber.backends import create_backend
    config = _make_config(transcription_backend="local", whisper_model="whisper-1")
    with pytest.raises(ValueError, match="not a valid local model"):
        create_backend(config)


async def test_create_backend_openai_rejects_local_model():
    from signal_transcriber.backends import create_backend
    config = _make_config(transcription_backend="openai", whisper_model="small")
    with pytest.raises(ValueError, match="local model name"):
        create_backend(config)

    # Verify the error message suggests the fix
    with pytest.raises(ValueError, match="whisper-1"):
        create_backend(config)


