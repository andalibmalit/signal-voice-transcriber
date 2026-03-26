import asyncio
import logging
import shutil

from dotenv import load_dotenv

from .backends import create_backend
from .config import Config
from .listener import listen


def main() -> None:
    load_dotenv()
    config = Config()

    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger(__name__)

    if not config.signal_number:
        raise SystemExit("SIGNAL_NUMBER environment variable is required")

    if config.transcription_backend == "openai" and not config.openai_api_key:
        raise SystemExit("TRANSCRIPTION_BACKEND=openai requires OPENAI_API_KEY")

    if config.enable_formatting and config.openai_api_key:
        logger.info(
            "GPT formatting enabled — transcripts will be sent to OpenAI"
        )
    elif config.enable_formatting and not config.openai_api_key:
        logger.info(
            "OPENAI_API_KEY not set — GPT formatting disabled, using pause-based formatting"
        )

    # ffmpeg only needed for OpenAI backend's AAC remux
    if config.transcription_backend == "openai" and not shutil.which("ffmpeg"):
        raise SystemExit(
            "ffmpeg not found on PATH (required for TRANSCRIPTION_BACKEND=openai)"
        )

    # Validate backend config early (catches model name mismatches at startup)
    try:
        backend = create_backend(config)
    except ValueError as e:
        raise SystemExit(str(e))

    logger.info(
        "Starting Signal Voice Transcriber for %s (backend=%s, model=%s)",
        config.signal_number, config.transcription_backend, config.whisper_model,
    )
    asyncio.run(listen(config, backend=backend))


if __name__ == "__main__":
    main()
