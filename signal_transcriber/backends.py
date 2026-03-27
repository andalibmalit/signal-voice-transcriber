"""Transcription backend abstraction: local (faster-whisper) and cloud (OpenAI)."""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .config import Config

logger = logging.getLogger(__name__)

_LOCAL_MODEL_NAMES = {
    "tiny", "tiny.en", "base", "base.en", "small", "small.en",
    "medium", "medium.en", "large", "large-v1", "large-v2", "large-v3",
    "large-v3-turbo", "turbo",
    "distil-small.en", "distil-medium.en",
    "distil-large-v2", "distil-large-v3", "distil-large-v3.5",
}

# Suffixes accepted by the OpenAI Whisper API without conversion
WHISPER_ACCEPTED_SUFFIXES = frozenset(
    {".m4a", ".mp3", ".mp4", ".ogg", ".wav", ".webm", ".flac"}
)


@dataclass
class Segment:
    """A transcription segment with timing info."""
    text: str
    start: float  # seconds
    end: float    # seconds


@dataclass
class TranscriptionResult:
    """Result from a transcription backend."""
    text: str
    segments: list[Segment] | None  # None for cloud backends
    language: str | None


class TranscriptionBackend(Protocol):
    async def transcribe(self, audio_path: Path) -> TranscriptionResult: ...
    async def close(self) -> None: ...


class LocalWhisperBackend:
    """In-process transcription using faster-whisper (CTranslate2)."""

    def __init__(self, config: Config) -> None:
        self._model = None
        self._config = config
        self._executor = ThreadPoolExecutor(max_workers=1)

    def _ensure_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(
                self._config.whisper_model,
                device=self._config.whisper_device,
                compute_type=self._config.whisper_compute_type,
                cpu_threads=self._config.whisper_cpu_threads,
                download_root=self._config.whisper_model_dir,
            )
        return self._model

    async def transcribe(self, audio_path: Path) -> TranscriptionResult:
        loop = asyncio.get_running_loop()

        def _run() -> TranscriptionResult:
            model = self._ensure_model()
            language = None if self._config.whisper_language == "auto" else self._config.whisper_language
            segments_gen, info = model.transcribe(
                str(audio_path),
                beam_size=5,
                language=language,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=1500),
            )
            segments = [
                Segment(text=seg.text.strip(), start=seg.start, end=seg.end)
                for seg in segments_gen
            ]
            return TranscriptionResult(
                text=" ".join(s.text for s in segments),
                segments=segments,
                language=info.language,
            )

        return await loop.run_in_executor(self._executor, _run)

    async def close(self) -> None:
        self._executor.shutdown(wait=False)


class OpenAIWhisperBackend:
    """Cloud transcription using the OpenAI Whisper API."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._client = None

    async def transcribe(self, audio_path: Path) -> TranscriptionResult:
        from .transcriber import _convert_to_m4a
        loop = asyncio.get_running_loop()
        m4a_path: Path | None = None

        try:
            if audio_path.suffix.lower() not in WHISPER_ACCEPTED_SUFFIXES:
                m4a_path = await loop.run_in_executor(None, _convert_to_m4a, audio_path)
                whisper_input = m4a_path
            else:
                whisper_input = audio_path

            def _run() -> TranscriptionResult:
                if self._client is None:
                    from openai import OpenAI
                    self._client = OpenAI(
                        api_key=self._config.openai_api_key,
                        timeout=self._config.openai_timeout,
                    )
                with open(whisper_input, "rb") as f:
                    text = self._client.audio.transcriptions.create(
                        model=self._config.whisper_model,
                        file=f,
                        response_format="text",
                    )
                return TranscriptionResult(text=text, segments=None, language=None)

            return await loop.run_in_executor(None, _run)
        finally:
            if m4a_path and m4a_path.exists():
                m4a_path.unlink()

    async def close(self) -> None:
        pass


def create_backend(config: Config) -> TranscriptionBackend:
    """Create the appropriate transcription backend based on config."""
    if config.transcription_backend == "openai":
        if not config.openai_api_key:
            raise ValueError("TRANSCRIPTION_BACKEND=openai requires OPENAI_API_KEY")
        if config.whisper_model in _LOCAL_MODEL_NAMES:
            raise ValueError(
                f"WHISPER_MODEL='{config.whisper_model}' is a local model name. "
                f"When TRANSCRIPTION_BACKEND=openai, use 'whisper-1' or another OpenAI model. "
                f"Did you mean TRANSCRIPTION_BACKEND=local?"
            )
        return OpenAIWhisperBackend(config)
    if config.whisper_model not in _LOCAL_MODEL_NAMES:
        raise ValueError(
            f"WHISPER_MODEL='{config.whisper_model}' is not a valid local model. "
            f"Valid models: {', '.join(sorted(_LOCAL_MODEL_NAMES))}. "
            f"Did you mean TRANSCRIPTION_BACKEND=openai?"
        )
    return LocalWhisperBackend(config)
