import logging
from pathlib import Path

import aiohttp

from .config import Config
from .utils import make_temp_path

logger = logging.getLogger(__name__)


async def download_attachment(attachment_id: str, config: Config) -> Path:
    """Download an attachment via the signal-cli REST API."""
    suffix = Path(attachment_id).suffix or ".m4a"
    url = f"{config.signal_api_url}/v1/attachments/{attachment_id}"
    logger.info("Downloading attachment %s via REST API", attachment_id)

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            resp.raise_for_status()
            tmp = make_temp_path(suffix=suffix)
            with open(tmp, "wb") as f:
                async for chunk in resp.content.iter_chunked(8192):
                    f.write(chunk)

    logger.info("Attachment %s downloaded (%d bytes)", attachment_id, tmp.stat().st_size)
    return tmp


async def send_reply(
    config: Config,
    recipient: str,
    message: str,
    quote_timestamp: int,
    quote_author: str,
) -> None:
    """Send a quote-reply via signal-cli-rest-api."""
    url = f"{config.signal_api_url}/v2/send"

    payload: dict = {
        "message": message,
        "number": config.signal_number,
        "recipients": [recipient],
    }

    if quote_timestamp:
        payload["quote_timestamp"] = quote_timestamp
        payload["quote_author"] = quote_author
        payload["quote_message"] = "\U0001f3a4 Voice message"

    logger.info("Sending reply to %s", recipient)

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            body = await resp.text()
            if resp.status >= 400:
                logger.error("Send failed (%d): %s", resp.status, body[:500])
                resp.raise_for_status()
            logger.info("Reply sent successfully")
