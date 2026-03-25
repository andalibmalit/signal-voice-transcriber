import asyncio
import json
import logging
import signal
from pathlib import Path

import aiohttp

from .config import Config
from .signal_client import download_attachment, send_reply
from .transcriber import transcribe
from .utils import is_voice_message

logger = logging.getLogger(__name__)

# Module-level reference so _handle_message can access it
_config: Config | None = None
_tasks: set[asyncio.Task] = set()


async def listen(config: Config) -> None:
    """Connect to signal-cli-rest-api WebSocket and process messages."""
    global _config
    _config = config

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


def _should_transcribe(source: str, config: Config) -> bool:
    """Check if this sender's voice messages should be transcribed."""
    mode = config.transcribe_mode.lower()
    if mode == "all":
        return True
    if mode == "allowlist":
        return source in config.allowed_numbers
    # own_only (default)
    return source == config.signal_number


def _handle_message(raw: str) -> None:
    """Parse a message envelope and spawn transcription if voice message."""
    assert _config is not None

    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Non-JSON message: %s", raw[:200])
        return

    logger.debug("Raw: %s", raw[:2000])

    envelope = msg.get("envelope", msg)
    source = envelope.get("source", envelope.get("sourceNumber", "unknown"))
    timestamp = envelope.get("timestamp", "")

    # Check dataMessage first, fall back to syncMessage.sentMessage (Note to Self)
    data_message = envelope.get("dataMessage")
    is_sync = False
    if data_message is None:
        sync_sent = envelope.get("syncMessage", {}).get("sentMessage")
        if sync_sent is not None:
            data_message = sync_sent
            source = envelope.get("source", "self")
            is_sync = True

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

        if not _should_transcribe(source, _config):
            logger.info("Skipped voice message (sender not in allowlist)")
            return

        # Determine reply recipient
        if group_info:
            recipient = f"group.{group_info['groupId']}"
        elif is_sync:
            # syncMessage.sentMessage: reply to the destination, not ourselves
            dest = data_message.get("destination")
            recipient = dest if dest else source
        else:
            recipient = source

        for attachment in voice_attachments:
            task = asyncio.create_task(
                _process_voice_message(
                    attachment=attachment,
                    config=_config,
                    recipient=recipient,
                    quote_timestamp=int(timestamp) if timestamp else 0,
                    quote_author=source,
                )
            )
            _tasks.add(task)
            task.add_done_callback(_tasks.discard)

    elif data_message.get("message"):
        logger.info("Text message from %s", source)
    else:
        logger.info("Message from %s (no text, no voice)", source)


async def _process_voice_message(
    attachment: dict,
    config: Config,
    recipient: str,
    quote_timestamp: int,
    quote_author: str,
) -> None:
    """Download, transcribe, and reply with the transcript."""
    attachment_id = attachment.get("id", "")
    audio_path: Path | None = None

    try:
        # Check file size
        size = attachment.get("size", 0)
        max_bytes = config.max_audio_size_mb * 1024 * 1024
        if size > max_bytes:
            logger.warning("Attachment %s too large (%d bytes), skipping", attachment_id, size)
            return

        audio_path = await download_attachment(attachment_id, config)
        transcript = await transcribe(audio_path, config)

        reply_text = f"Transcription:\n\n{transcript}"
        await send_reply(config, recipient, reply_text, quote_timestamp, quote_author)

    except Exception:
        logger.exception("Failed to process voice message %s", attachment_id)
        try:
            await send_reply(
                config, recipient,
                "Could not transcribe this voice message.",
                quote_timestamp, quote_author,
            )
        except Exception:
            logger.exception("Failed to send error reply")
    finally:
        if audio_path and audio_path.exists():
            audio_path.unlink()
            logger.debug("Cleaned up temp file %s", audio_path)
