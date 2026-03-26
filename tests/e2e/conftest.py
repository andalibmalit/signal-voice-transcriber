"""E2E test fixtures: mock server, bot lifecycle, OpenAI mock, envelope factories."""

from __future__ import annotations

import asyncio
import contextlib
import queue as queue_mod
from pathlib import Path
from typing import Any, NamedTuple
from unittest.mock import MagicMock

import pytest

from signal_transcriber.config import Config
from signal_transcriber.listener import listen
import signal_transcriber.listener as listener_mod
import signal_transcriber.transcriber as transcriber_mod

from .mock_signal_server import MockSignalServer

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Audio fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def audio_fixtures() -> dict[str, Path]:
    return {
        "hello_10s": FIXTURES_DIR / "hello_10s.ogg",
        "short_2s": FIXTURES_DIR / "short_2s.ogg",
        "long_60s": FIXTURES_DIR / "long_60s.ogg",
    }


# ---------------------------------------------------------------------------
# Mock Signal Server
# ---------------------------------------------------------------------------

@pytest.fixture
async def mock_signal_server() -> MockSignalServer:
    server = MockSignalServer()
    await server.start()
    yield server  # type: ignore[misc]
    await server.stop()


# ---------------------------------------------------------------------------
# OpenAI mock (thread-safe for run_in_executor calls)
# ---------------------------------------------------------------------------

class MockWhisper:
    """Thread-safe mock for Whisper transcription results."""

    def __init__(self) -> None:
        self._default = "Transcribed audio."
        self._queue: queue_mod.Queue[str] = queue_mod.Queue()

    def set_transcript(self, text: str) -> None:
        self._default = text

    def enqueue_transcript(self, text: str) -> None:
        self._queue.put(text)

    def __call__(self, **kwargs: Any) -> str:
        try:
            return self._queue.get_nowait()
        except queue_mod.Empty:
            return self._default


@pytest.fixture
def mock_openai() -> tuple[MagicMock, MockWhisper]:
    """Mock OpenAI client with thread-safe Whisper and GPT mocks."""
    mock_client = MagicMock()
    whisper = MockWhisper()

    mock_client.audio.transcriptions.create.side_effect = whisper

    def _format_side_effect(**kwargs: Any) -> MagicMock:
        raw = kwargs["messages"][1]["content"]
        result = MagicMock()
        result.choices = [MagicMock(message=MagicMock(content=f"[Formatted] {raw}"))]
        return result

    mock_client.chat.completions.create.side_effect = _format_side_effect

    return mock_client, whisper


# ---------------------------------------------------------------------------
# Bot lifecycle
# ---------------------------------------------------------------------------

class BotHandle(NamedTuple):
    config: Config
    shutdown: asyncio.Event
    task: asyncio.Task  # type: ignore[type-arg]
    server: MockSignalServer


@pytest.fixture(autouse=True)
def _reset_listener_state() -> None:
    """Reset module-level state in listener between tests."""
    listener_mod._config = None
    listener_mod._seen.clear()
    listener_mod._queues.clear()
    listener_mod._workers.clear()
    transcriber_mod._openai_client = None


@pytest.fixture
async def bot(
    mock_signal_server: MockSignalServer,
    mock_openai: tuple[MagicMock, MockWhisper],
) -> BotHandle:
    """Start the bot connected to the mock server, yield a handle, then shut down."""
    mock_client, _whisper = mock_openai
    transcriber_mod._openai_client = mock_client

    config = Config(
        signal_api_url=mock_signal_server.url,
        signal_number="+10000000000",
        openai_api_key="test-key",
        whisper_model="whisper-1",
        gpt_model="gpt-4o-mini",
        enable_formatting=True,
        log_level="DEBUG",
        max_audio_size_mb=25,
        transcribe_mode="all",
        allowed_numbers=[],
        openai_timeout=10,
    )

    shutdown = asyncio.Event()
    task = asyncio.create_task(listen(config, _shutdown=shutdown))

    await mock_signal_server.wait_for_connection(timeout=5)

    yield BotHandle(config=config, shutdown=shutdown, task=task, server=mock_signal_server)  # type: ignore[misc]

    shutdown.set()
    try:
        await asyncio.wait_for(task, timeout=5)
    except asyncio.TimeoutError:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


# ---------------------------------------------------------------------------
# Envelope factories
# ---------------------------------------------------------------------------

def make_voice_envelope(
    source: str,
    timestamp: int,
    attachment_id: str = "att_001",
    size: int = 5000,
    content_type: str = "audio/aac",
    voice_note: bool = True,
    group_id: str | None = None,
) -> dict[str, Any]:
    """Build a voice message envelope."""
    attachment = {
        "contentType": content_type,
        "id": attachment_id,
        "size": size,
        "voiceNote": voice_note,
    }
    data_message: dict[str, Any] = {
        "attachments": [attachment],
        "timestamp": timestamp,
    }
    if group_id is not None:
        data_message["groupInfo"] = {"groupId": group_id}

    return {
        "source": source,
        "sourceNumber": source,
        "timestamp": timestamp,
        "dataMessage": data_message,
    }


def make_sync_envelope(
    source: str,
    destination: str,
    timestamp: int,
    attachment_id: str = "att_001",
    size: int = 5000,
) -> dict[str, Any]:
    """Build a syncMessage.sentMessage envelope (Note to Self / linked device)."""
    attachment = {
        "contentType": "audio/aac",
        "id": attachment_id,
        "size": size,
        "voiceNote": True,
    }
    return {
        "source": source,
        "sourceNumber": source,
        "timestamp": timestamp,
        "syncMessage": {
            "sentMessage": {
                "destination": destination,
                "timestamp": timestamp,
                "attachments": [attachment],
            },
        },
    }


def make_text_envelope(
    source: str,
    timestamp: int,
    message: str,
) -> dict[str, Any]:
    """Build a plain text message envelope (should NOT trigger transcription)."""
    return {
        "source": source,
        "sourceNumber": source,
        "timestamp": timestamp,
        "dataMessage": {
            "message": message,
            "timestamp": timestamp,
        },
    }


def make_audio_file_envelope(
    source: str,
    timestamp: int,
    attachment_id: str = "att_002",
    filename: str = "song.mp3",
) -> dict[str, Any]:
    """Build an audio attachment WITH a filename (not a voice message)."""
    return {
        "source": source,
        "sourceNumber": source,
        "timestamp": timestamp,
        "dataMessage": {
            "attachments": [
                {
                    "contentType": "audio/mpeg",
                    "id": attachment_id,
                    "size": 5000,
                    "voiceNote": False,
                    "filename": filename,
                },
            ],
            "timestamp": timestamp,
        },
    }
