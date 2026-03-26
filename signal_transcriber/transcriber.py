import asyncio
import logging
import subprocess
from pathlib import Path

from openai import OpenAI

from .config import Config
from .utils import make_temp_path

logger = logging.getLogger(__name__)

_openai_client: OpenAI | None = None


def get_openai_client(api_key: str, timeout: float = 120) -> OpenAI:
    """Return a cached OpenAI client, creating one if needed."""
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI(api_key=api_key, timeout=timeout)
    return _openai_client


def _convert_to_m4a(audio_path: Path) -> Path:
    """Remux raw AAC/ADTS to M4A container (lossless, instant)."""
    out = make_temp_path(suffix=".m4a")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(audio_path), "-c:a", "copy",
             "-bsf:a", "aac_adtstoasc", str(out)],
            check=True, capture_output=True,
        )
    except subprocess.CalledProcessError:
        out.unlink(missing_ok=True)
        raise
    logger.debug("Converted %s -> %s", audio_path.name, out.name)
    return out


async def transcribe(audio_path: Path, config: Config) -> str:
    """Transcribe an audio file using OpenAI Whisper API."""
    m4a_path: Path | None = None
    loop = asyncio.get_running_loop()

    try:
        # Remux to M4A if not already a Whisper-friendly format
        if audio_path.suffix.lower() not in (".m4a", ".mp3", ".mp4", ".ogg", ".wav", ".webm", ".flac"):
            m4a_path = await loop.run_in_executor(None, _convert_to_m4a, audio_path)
            whisper_input = m4a_path
        else:
            whisper_input = audio_path

        client = get_openai_client(config.openai_api_key, timeout=config.openai_timeout)

        def _call_whisper() -> str:
            with open(whisper_input, "rb") as f:
                result = client.audio.transcriptions.create(
                    model=config.whisper_model,
                    file=f,
                    response_format="text",
                )
            return result

        transcript = await loop.run_in_executor(None, _call_whisper)
        logger.info("Transcription complete (%d chars)", len(transcript))
        return transcript
    finally:
        if m4a_path and m4a_path.exists():
            m4a_path.unlink()
