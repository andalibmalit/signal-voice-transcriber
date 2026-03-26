import json

import pytest
from unittest.mock import patch, AsyncMock

import signal_transcriber.listener as listener_mod
from signal_transcriber.listener import (
    _should_transcribe,
    _handle_message,
    _VoiceJob,
)


@pytest.fixture(autouse=True)
def clear_seen():
    """Reset dedup state between tests."""
    listener_mod._seen.clear()


@pytest.fixture(autouse=True)
def clear_queues_and_workers():
    """Reset per-recipient queues and workers between tests."""
    listener_mod._queues.clear()
    listener_mod._workers.clear()


def _voice_envelope(source: str, timestamp: int, attachment_id: str = "abc123") -> str:
    """Helper to build a JSON envelope with a voice attachment."""
    return json.dumps({
        "envelope": {
            "source": source,
            "timestamp": timestamp,
            "dataMessage": {
                "attachments": [
                    {"voiceNote": True, "id": attachment_id, "size": 1000}
                ],
            },
        }
    })


def test_should_transcribe_all(config):
    config.transcribe_mode = "all"
    assert _should_transcribe("+19999999999", config) is True


def test_should_transcribe_own_only(config):
    assert _should_transcribe(config.signal_number, config) is True
    assert _should_transcribe("+19999999999", config) is False


def test_should_transcribe_allowlist(config):
    config.transcribe_mode = "allowlist"
    assert _should_transcribe("+11111111111", config) is True
    assert _should_transcribe("+19999999999", config) is False


def test_handle_voice_message_enqueues_job(config):
    listener_mod._config = config
    config.transcribe_mode = "all"

    raw = _voice_envelope("+10000000000", 1234567890)

    with patch("signal_transcriber.listener.asyncio.create_task") as mock_task:
        mock_task.return_value = AsyncMock()
        _handle_message(raw)

    recipient = "+10000000000"
    assert recipient in listener_mod._queues
    queue = listener_mod._queues[recipient]
    assert queue.qsize() == 1
    job = queue.get_nowait()
    assert isinstance(job, _VoiceJob)
    assert job.attachment["id"] == "abc123"
    assert job.recipient == recipient
    assert job.quote_timestamp == 1234567890
    assert job.quote_author == "+10000000000"


def test_handle_text_message_no_queue(config):
    listener_mod._config = config

    envelope = {
        "envelope": {
            "source": "+10000000000",
            "timestamp": 1234567890,
            "dataMessage": {
                "message": "Hello",
                "attachments": [],
            },
        }
    }

    _handle_message(json.dumps(envelope))

    assert len(listener_mod._queues) == 0


def test_handle_voice_message_skipped_by_privacy(config):
    listener_mod._config = config
    config.transcribe_mode = "own_only"

    raw = _voice_envelope("+19999999999", 1234567890)

    _handle_message(raw)

    assert len(listener_mod._queues) == 0


def test_duplicate_message_skipped(config):
    listener_mod._config = config
    config.transcribe_mode = "all"

    raw = _voice_envelope("+10000000000", 9999999999)

    with patch("signal_transcriber.listener.asyncio.create_task") as mock_task:
        mock_task.return_value = AsyncMock()
        _handle_message(raw)
        _handle_message(raw)  # duplicate

    recipient = "+10000000000"
    assert listener_mod._queues[recipient].qsize() == 1


def test_two_messages_same_recipient_one_worker(config):
    """Two voice messages for the same recipient should create only one worker."""
    listener_mod._config = config
    config.transcribe_mode = "all"

    raw1 = _voice_envelope("+10000000000", 1111111111, "att1")
    raw2 = _voice_envelope("+10000000000", 2222222222, "att2")

    with patch("signal_transcriber.listener.asyncio.create_task") as mock_task:
        mock_task.return_value = AsyncMock()
        _handle_message(raw1)
        _handle_message(raw2)

    mock_task.assert_called_once()
    recipient = "+10000000000"
    assert listener_mod._queues[recipient].qsize() == 2


def test_two_messages_different_recipients_two_workers(config):
    """Two voice messages for different recipients should create two workers."""
    listener_mod._config = config
    config.transcribe_mode = "all"

    raw1 = _voice_envelope("+10000000000", 1111111111, "att1")
    raw2 = _voice_envelope("+20000000000", 2222222222, "att2")

    with patch("signal_transcriber.listener.asyncio.create_task") as mock_task:
        mock_task.return_value = AsyncMock()
        _handle_message(raw1)
        _handle_message(raw2)

    assert mock_task.call_count == 2
    assert "+10000000000" in listener_mod._queues
    assert "+20000000000" in listener_mod._queues
