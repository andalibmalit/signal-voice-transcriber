"""E2E test fixtures: mock server, bot lifecycle, envelope factories."""

from __future__ import annotations

import asyncio
import contextlib
import os
from pathlib import Path
from typing import Any, NamedTuple

import pytest
from dotenv import load_dotenv

# Load .env before imports that read os.environ for Config defaults
load_dotenv()

from signal_transcriber.config import Config  # noqa: E402
from signal_transcriber.listener import listen  # noqa: E402
import signal_transcriber.listener as listener_mod  # noqa: E402
import signal_transcriber.transcriber as transcriber_mod  # noqa: E402

from .mock_signal_server import MockSignalServer  # noqa: E402

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# Marker for tests that require a real OpenAI API key
requires_openai = pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set",
)


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


@pytest.fixture
async def bot(
    mock_signal_server: MockSignalServer,
) -> BotHandle:
    """Start the bot connected to the mock server with real OpenAI client."""
    # Ensure a fresh OpenAI client is created with the real API key
    transcriber_mod._openai_client = None

    config = Config(
        signal_api_url=mock_signal_server.url,
        signal_number="+10000000000",
        openai_api_key=os.environ["OPENAI_API_KEY"],
        transcribe_mode="all",
        log_level="DEBUG",
        openai_timeout=30,
    )

    shutdown = asyncio.Event()
    task = asyncio.create_task(listen(config, _shutdown=shutdown))

    await mock_signal_server.wait_for_connection(timeout=5)

    yield BotHandle(config=config, shutdown=shutdown, task=task, server=mock_signal_server)  # type: ignore[misc]

    shutdown.set()
    if not task.done():
        try:
            await asyncio.wait_for(task, timeout=5)
        except asyncio.TimeoutError:
            task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    # Cancel any lingering worker tasks to avoid "Event loop is closed" warnings
    for worker_task in list(listener_mod._workers.values()):
        worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker_task


async def start_bot(
    server: MockSignalServer,
    **config_overrides: Any,
) -> tuple[asyncio.Event, asyncio.Task]:  # type: ignore[type-arg]
    """Start a bot with custom config. Returns (shutdown_event, listen_task)."""
    transcriber_mod._openai_client = None

    defaults: dict[str, Any] = dict(
        signal_api_url=server.url,
        signal_number="+10000000000",
        openai_api_key=os.environ["OPENAI_API_KEY"],
        transcribe_mode="all",
        log_level="DEBUG",
        openai_timeout=30,
    )
    defaults.update(config_overrides)
    config = Config(**defaults)

    shutdown = asyncio.Event()
    task = asyncio.create_task(listen(config, _shutdown=shutdown))
    await server.wait_for_connection(timeout=5)
    return shutdown, task


async def stop_bot(
    shutdown: asyncio.Event,
    task: asyncio.Task,  # type: ignore[type-arg]
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
