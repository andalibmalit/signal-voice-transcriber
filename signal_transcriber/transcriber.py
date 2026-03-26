"""Audio conversion utilities for the OpenAI Whisper backend."""

import logging
import subprocess
from pathlib import Path

from .utils import make_temp_path

logger = logging.getLogger(__name__)


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
