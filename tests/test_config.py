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


def test_openai_backend_requires_api_key():
    with patch(
        "signal_transcriber.__main__.Config",
        return_value=Config(
            signal_number="+10000000000",
            openai_api_key="",
            transcription_backend="openai",
            transcribe_mode="own_only",
        ),
    ), patch("signal_transcriber.__main__.load_dotenv"), pytest.raises(
        SystemExit, match="TRANSCRIPTION_BACKEND=openai requires OPENAI_API_KEY"
    ):
        main()


def test_openai_backend_requires_ffmpeg():
    with patch(
        "signal_transcriber.__main__.Config",
        return_value=Config(
            signal_number="+10000000000",
            openai_api_key="test-key",
            whisper_model="whisper-1",
            transcription_backend="openai",
            transcribe_mode="own_only",
        ),
    ), patch("signal_transcriber.__main__.load_dotenv"), patch(
        "signal_transcriber.__main__.shutil"
    ) as mock_shutil, pytest.raises(
        SystemExit, match="ffmpeg not found"
    ):
        mock_shutil.which.return_value = None
        main()


def test_local_backend_starts_without_api_key():
    """Local backend does not require OPENAI_API_KEY or ffmpeg."""
    with patch(
        "signal_transcriber.__main__.Config",
        return_value=Config(
            signal_number="+10000000000",
            openai_api_key="",
            transcription_backend="local",
            transcribe_mode="own_only",
        ),
    ), patch("signal_transcriber.__main__.load_dotenv"), patch(
        "signal_transcriber.__main__.listen"
    ), patch(
        "signal_transcriber.__main__.asyncio"
    ):
        main()  # Should not raise


# --- Config field defaults ---


def test_default_backend_is_local(monkeypatch):
    monkeypatch.delenv("TRANSCRIPTION_BACKEND", raising=False)
    cfg = Config(transcribe_mode="own_only")
    assert cfg.transcription_backend == "local"


def test_default_whisper_model_is_small(monkeypatch):
    monkeypatch.delenv("WHISPER_MODEL", raising=False)
    cfg = Config(transcribe_mode="own_only")
    assert cfg.whisper_model == "small"


def test_new_config_fields_have_defaults(monkeypatch):
    for var in ("WHISPER_COMPUTE_TYPE", "WHISPER_DEVICE", "WHISPER_CPU_THREADS",
                "WHISPER_LANGUAGE", "WHISPER_MODEL_DIR"):
        monkeypatch.delenv(var, raising=False)
    cfg = Config(transcribe_mode="own_only")
    assert cfg.whisper_compute_type == "int8"
    assert cfg.whisper_device == "cpu"
    assert cfg.whisper_cpu_threads == 4
    assert cfg.whisper_language == "auto"
    assert cfg.whisper_model_dir == "/models"
