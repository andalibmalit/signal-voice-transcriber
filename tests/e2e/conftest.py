"""E2E test fixtures: mock server, bot lifecycle, envelope factories."""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any, NamedTuple
from unittest.mock import patch

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

_whisper_model = None


def _get_whisper_model():
    """Return a cached WhisperModel (loaded once per test session)."""
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        _whisper_model = WhisperModel("small", device="cpu", compute_type="int8")
    return _whisper_model


async def _local_transcribe(audio_path: Path, config: Config) -> str:
    """Drop-in replacement for transcriber.transcribe using local faster-whisper."""
    loop = asyncio.get_running_loop()

    def _run() -> str:
        model = _get_whisper_model()
        segments, _info = model.transcribe(
            str(audio_path), beam_size=5, vad_filter=True,
        )
        return " ".join(seg.text.strip() for seg in segments)

    return await loop.run_in_executor(None, _run)


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
    """Start the bot with real local transcription (no OpenAI API key needed)."""
    config, shutdown, task, patches = await start_bot(mock_signal_server)
    yield BotHandle(config=config, shutdown=shutdown, task=task, server=mock_signal_server, patches=patches)  # type: ignore[misc]
    await stop_bot(shutdown, task, patches)


@pytest.fixture
async def mock_bot(
    mock_signal_server: MockSignalServer,
) -> BotHandle:
    """Start the bot with a dummy API key (no real transcription).

    Use for tests that mock the OpenAI client or never trigger transcription.
    Does not require OPENAI_API_KEY in the environment.
    """
    config, shutdown, task, patches = await start_bot(
        mock_signal_server,
        openai_api_key="dummy-key",
        use_local_transcribe=False,
    )
    yield BotHandle(config=config, shutdown=shutdown, task=task, server=mock_signal_server, patches=patches)  # type: ignore[misc]
    await stop_bot(shutdown, task, patches)


async def start_bot(
    server: MockSignalServer,
    *,
    use_local_transcribe: bool = True,
    **config_overrides: Any,
) -> tuple[Config, asyncio.Event, asyncio.Task, list]:  # type: ignore[type-arg]
    """Start a bot with custom config. Returns (config, shutdown_event, listen_task, patches)."""
    transcriber_mod._openai_client = None

    defaults: dict[str, Any] = dict(
        signal_api_url=server.url,
        signal_number="+10000000000",
        openai_api_key="",
        transcribe_mode="all",
        enable_formatting=False,
        log_level="DEBUG",
        openai_timeout=30,
    )
    defaults.update(config_overrides)
    config = Config(**defaults)

    patches: list = []
    if use_local_transcribe:
        p = patch("signal_transcriber.listener.transcribe", new=_local_transcribe)
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
