import asyncio
import logging
import shutil

from dotenv import load_dotenv

from .config import Config
from .listener import listen


def main() -> None:
    load_dotenv()
    config = Config()

    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if not config.signal_number:
        raise SystemExit("SIGNAL_NUMBER environment variable is required")

    if not config.openai_api_key:
        raise SystemExit("OPENAI_API_KEY environment variable is required")

    if not shutil.which("ffmpeg"):
        raise SystemExit(
            "ffmpeg not found on PATH; install it or add it to your PATH"
        )

    logging.getLogger(__name__).info(
        "Starting Signal Voice Transcriber for %s", config.signal_number
    )
    asyncio.run(listen(config))


if __name__ == "__main__":
    main()
