import asyncio
import json
import logging
import signal

import aiohttp

from .config import Config
from .utils import is_voice_message

logger = logging.getLogger(__name__)


async def listen(config: Config) -> None:
    """Connect to signal-cli-rest-api WebSocket and log received messages."""
    url = f"{config.signal_api_url}/v1/receive/{config.signal_number}"
    ws_url = url.replace("http://", "ws://").replace("https://", "wss://")

    backoff = 1
    max_backoff = 60
    shutdown = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, shutdown.set)

    while not shutdown.is_set():
        try:
            async with aiohttp.ClientSession() as session:
                logger.info("Connecting to %s", ws_url)
                async with session.ws_connect(ws_url, heartbeat=30) as ws:
                    logger.info("WebSocket connected")
                    backoff = 1

                    async for msg in ws:
                        if shutdown.is_set():
                            break
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            _handle_message(msg.data)
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            logger.error("WebSocket error: %s", ws.exception())
                            break
        except (aiohttp.ClientError, OSError) as exc:
            logger.warning("Connection failed: %s", exc)

        if not shutdown.is_set():
            logger.info("Reconnecting in %ds...", backoff)
            try:
                await asyncio.wait_for(shutdown.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 2, max_backoff)

    logger.info("Listener shut down")


def _handle_message(raw: str) -> None:
    """Parse and log a message envelope."""
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Non-JSON message: %s", raw[:200])
        return

    logger.debug("Raw: %s", raw[:2000])

    # WebSocket sends {"envelope": {…signal data…}, "account": "…"}
    envelope = msg.get("envelope", msg)

    source = envelope.get("source", envelope.get("sourceNumber", "unknown"))
    timestamp = envelope.get("timestamp", "")

    # Check dataMessage first, fall back to syncMessage.sentMessage (Note to Self)
    data_message = envelope.get("dataMessage")
    if data_message is None:
        sync_sent = envelope.get("syncMessage", {}).get("sentMessage")
        if sync_sent is not None:
            data_message = sync_sent
            source = envelope.get("source", "self")

    if data_message is None:
        logger.info("Envelope from %s (no dataMessage or syncMessage), keys: %s",
                     source, list(envelope.keys()))
        return

    attachments = data_message.get("attachments", [])
    voice_attachments = [a for a in attachments if is_voice_message(a)]

    if voice_attachments:
        group_info = data_message.get("groupInfo")
        context = f"group {group_info['groupId']}" if group_info else "direct"
        logger.info("Voice message detected from %s (%s) — %d attachment(s), timestamp=%s",
                     source, context, len(voice_attachments), timestamp)
    elif data_message.get("message"):
        logger.info("Text message from %s", source)
    else:
        logger.info("Message from %s (no text, no voice)", source)
