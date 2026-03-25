import asyncio
import logging

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

    logging.getLogger(__name__).info(
        "Starting Signal Voice Transcriber for %s", config.signal_number
    )
    asyncio.run(listen(config))


main()
