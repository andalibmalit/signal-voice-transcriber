import pytest

from signal_transcriber.config import Config


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
        attachment_dir="/tmp/attachments",
        max_audio_size_mb=25,
        transcribe_mode="own_only",
        allowed_numbers=["+11111111111", "+12222222222"],
        openai_timeout=120,
    )
