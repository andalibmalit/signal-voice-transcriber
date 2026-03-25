import asyncio
import logging
import subprocess
import tempfile
from pathlib import Path

from openai import OpenAI

from .config import Config

logger = logging.getLogger(__name__)


def _convert_to_m4a(audio_path: Path) -> Path:
    """Remux raw AAC/ADTS to M4A container (lossless, instant)."""
    out = Path(tempfile.mktemp(suffix=".m4a"))
    subprocess.run(
        ["ffmpeg", "-i", str(audio_path), "-c:a", "copy",
         "-bsf:a", "aac_adtstoasc", str(out)],
        check=True, capture_output=True,
    )
    logger.debug("Converted %s -> %s", audio_path.name, out.name)
    return out


async def transcribe(audio_path: Path, config: Config) -> str:
    """Transcribe an audio file using OpenAI Whisper API."""
    m4a_path: Path | None = None

    try:
        # Remux to M4A if not already a Whisper-friendly format
        if audio_path.suffix.lower() not in (".m4a", ".mp3", ".mp4", ".ogg", ".wav", ".webm", ".flac"):
            loop = asyncio.get_running_loop()
            m4a_path = await loop.run_in_executor(None, _convert_to_m4a, audio_path)
            whisper_input = m4a_path
        else:
            whisper_input = audio_path

        client = OpenAI(api_key=config.openai_api_key)

        def _call_whisper() -> str:
            with open(whisper_input, "rb") as f:
                result = client.audio.transcriptions.create(
                    model=config.whisper_model,
                    file=f,
                    response_format="text",
                )
            return result

        loop = asyncio.get_running_loop()
        transcript = await loop.run_in_executor(None, _call_whisper)
        logger.info("Transcription complete (%d chars)", len(transcript))
        return transcript
    finally:
        if m4a_path and m4a_path.exists():
            m4a_path.unlink()
