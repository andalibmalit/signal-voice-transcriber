import json
from unittest.mock import patch, AsyncMock

from signal_transcriber.listener import _should_transcribe, _handle_message


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


def test_handle_voice_message_spawns_task(config):
    import signal_transcriber.listener as listener_mod
    listener_mod._config = config
    config.transcribe_mode = "all"

    envelope = {
        "envelope": {
            "source": "+10000000000",
            "timestamp": 1234567890,
            "dataMessage": {
                "attachments": [{"voiceNote": True, "id": "abc123", "size": 1000}],
            },
        }
    }

    with patch("signal_transcriber.listener.asyncio.create_task") as mock_task:
        mock_task.return_value = AsyncMock()
        mock_task.return_value.add_done_callback = lambda _: None
        _handle_message(json.dumps(envelope))

    mock_task.assert_called_once()


def test_handle_text_message_no_task(config):
    import signal_transcriber.listener as listener_mod
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

    with patch("signal_transcriber.listener.asyncio.create_task") as mock_task:
        _handle_message(json.dumps(envelope))

    mock_task.assert_not_called()


def test_handle_voice_message_skipped_by_privacy(config):
    import signal_transcriber.listener as listener_mod
    listener_mod._config = config
    config.transcribe_mode = "own_only"

    envelope = {
        "envelope": {
            "source": "+19999999999",
            "timestamp": 1234567890,
            "dataMessage": {
                "attachments": [{"voiceNote": True, "id": "abc123", "size": 1000}],
            },
        }
    }

    with patch("signal_transcriber.listener.asyncio.create_task") as mock_task:
        _handle_message(json.dumps(envelope))

    mock_task.assert_not_called()
