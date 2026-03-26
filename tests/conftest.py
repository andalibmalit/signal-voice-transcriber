import pytest

from signal_transcriber.config import Config
import signal_transcriber.listener as listener_mod
import signal_transcriber.formatter as formatter_mod


@pytest.fixture(autouse=True)
def _reset_module_state() -> None:
    """Reset module-level state between tests (listener + formatter)."""
    listener_mod._config = None
    listener_mod._backend = None
    listener_mod._seen.clear()
    listener_mod._queues.clear()
    listener_mod._workers.clear()
    formatter_mod._openai_client = None


@pytest.fixture
def config() -> Config:
    return Config(
        signal_api_url="http://localhost:8080",
        signal_number="+10000000000",
        openai_api_key="test-key",
        whisper_model="whisper-1",
        gpt_model="gpt-4o-mini",
        enable_formatting=True,
        log_level="DEBUG",
        max_audio_size_mb=25,
        transcribe_mode="own_only",
        allowed_numbers=["+11111111111", "+12222222222"],
        openai_timeout=120,
    )
