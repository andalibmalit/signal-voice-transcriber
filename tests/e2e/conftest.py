"""E2E test fixtures: mock server, bot lifecycle, envelope factories."""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any, NamedTuple
from unittest.mock import AsyncMock, patch

import pytest
from dotenv import load_dotenv

# Load .env before imports that read os.environ for Config defaults
load_dotenv()

from signal_transcriber.backends import TranscriptionResult  # noqa: E402
from signal_transcriber.config import Config  # noqa: E402
from signal_transcriber.listener import listen  # noqa: E402
import signal_transcriber.listener as listener_mod  # noqa: E402
import signal_transcriber.formatter as formatter_mod  # noqa: E402

from .mock_signal_server import MockSignalServer  # noqa: E402

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def audio_fixtures() -> dict[str, Path]:
    return {
        "hello_10s": FIXTURES_DIR / "hello_10s.m4a",
        "short_2s": FIXTURES_DIR / "short_2s.m4a",
        "long_60s": FIXTURES_DIR / "long_60s.m4a",
    }


@pytest.fixture
async def mock_signal_server() -> MockSignalServer:
    server = MockSignalServer()
    await server.start()
    yield server  # type: ignore[misc]
    await server.stop()


class BotHandle(NamedTuple):
    config: Config
    shutdown: asyncio.Event
    task: asyncio.Task  # type: ignore[type-arg]
    server: MockSignalServer
    patches: list  # type: ignore[type-arg]


@pytest.fixture
async def bot(
    mock_signal_server: MockSignalServer,
) -> BotHandle:
    """Start the bot with real local transcription (no OpenAI API key needed).

    Uses a real LocalWhisperBackend created by create_backend().
    """
    config, shutdown, task, patches = await start_bot(mock_signal_server)
    yield BotHandle(config=config, shutdown=shutdown, task=task, server=mock_signal_server, patches=patches)  # type: ignore[misc]
    await stop_bot(shutdown, task, patches)


@pytest.fixture
async def mock_bot(
    mock_signal_server: MockSignalServer,
) -> BotHandle:
    """Start the bot with a mocked backend (no real transcription).

    Use for tests that need to control transcription behavior
    (error injection, long output, etc.).
    """
    mock_backend = AsyncMock()
    mock_backend.transcribe.return_value = TranscriptionResult(
        text="Mock transcription.", segments=None, language="en",
    )

    config, shutdown, task, patches = await start_bot(
        mock_signal_server,
        mock_backend=mock_backend,
    )
    yield BotHandle(config=config, shutdown=shutdown, task=task, server=mock_signal_server, patches=patches)  # type: ignore[misc]
    await stop_bot(shutdown, task, patches)


async def start_bot(
    server: MockSignalServer,
    *,
    mock_backend: AsyncMock | None = None,
    **config_overrides: Any,
) -> tuple[Config, asyncio.Event, asyncio.Task, list]:  # type: ignore[type-arg]
    """Start a bot with custom config. Returns (config, shutdown_event, listen_task, patches).

    If mock_backend is provided, create_backend() is patched to return it.
    Otherwise, create_backend() runs normally (creating a real LocalWhisperBackend).
    """
    formatter_mod._openai_client = None

    defaults: dict[str, Any] = dict(
        signal_api_url=server.url,
        signal_number="+10000000000",
        openai_api_key="",
        whisper_model="small",
        whisper_model_dir=None,  # Use faster-whisper default (~/.cache/huggingface)
        transcribe_mode="all",
        enable_formatting=False,
        log_level="DEBUG",
        openai_timeout=30,
    )
    defaults.update(config_overrides)
    config = Config(**defaults)

    patches: list = []
    if mock_backend is not None:
        p = patch("signal_transcriber.listener.create_backend", return_value=mock_backend)
        p.start()
        patches.append(p)

    try:
        shutdown = asyncio.Event()
        task = asyncio.create_task(listen(config, _shutdown=shutdown))
        await server.wait_for_connection(timeout=5)
    except BaseException:
        for p in patches:
            p.stop()
        raise
    return config, shutdown, task, patches


async def stop_bot(
    shutdown: asyncio.Event,
    task: asyncio.Task,  # type: ignore[type-arg]
    patches: list | None = None,
) -> None:
    """Shut down a bot started with start_bot()."""
    shutdown.set()
    if not task.done():
        try:
            await asyncio.wait_for(task, timeout=5)
        except asyncio.TimeoutError:
            task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    for worker_task in list(listener_mod._workers.values()):
        worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker_task
    for p in (patches or []):
        p.stop()


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
