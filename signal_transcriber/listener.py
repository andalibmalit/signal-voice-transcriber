import asyncio
import json
import logging
import signal
from collections import OrderedDict
from pathlib import Path
from typing import NamedTuple

import aiohttp

from .backends import TranscriptionBackend, create_backend
from .config import Config
from .formatter import format_transcript
from .signal_client import download_attachment, send_reply
from .utils import is_voice_message, split_message

logger = logging.getLogger(__name__)

_config: Config | None = None
_backend: TranscriptionBackend | None = None
_seen: OrderedDict[tuple[str, str], None] = OrderedDict()
_SEEN_MAX = 1000

# Per-recipient queues and worker tasks for ordered processing
_queues: dict[str, asyncio.Queue] = {}
_workers: dict[str, asyncio.Task] = {}


class _VoiceJob(NamedTuple):
    attachment: dict
    config: Config
    recipient: str
    quote_timestamp: int
    quote_author: str


async def listen(
    config: Config,
    _shutdown: asyncio.Event | None = None,
    *,
    backend: TranscriptionBackend | None = None,
) -> None:
    """Connect to signal-cli-rest-api WebSocket and process messages."""
    global _config, _backend
    _config = config
    _backend = backend or create_backend(config)

    url = f"{config.signal_api_url}/v1/receive/{config.signal_number}"
    ws_url = url.replace("http://", "ws://").replace("https://", "wss://")

    backoff = 1
    max_backoff = 60
    shutdown = _shutdown or asyncio.Event()

    if _shutdown is None:
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

                    shutdown_task = asyncio.create_task(shutdown.wait())
                    try:
                        while True:
                            receive_task = asyncio.create_task(ws.receive())
                            done, _ = await asyncio.wait(
                                {shutdown_task, receive_task},
                                return_when=asyncio.FIRST_COMPLETED,
                            )
                            if shutdown_task in done:
                                receive_task.cancel()
                                break
                            msg = receive_task.result()
                            if msg.type in (
                                aiohttp.WSMsgType.CLOSE,
                                aiohttp.WSMsgType.CLOSING,
                                aiohttp.WSMsgType.CLOSED,
                            ):
                                break
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                _handle_message(msg.data)
                            elif msg.type == aiohttp.WSMsgType.ERROR:
                                logger.error(
                                    "WebSocket error: %s", ws.exception()
                                )
                                break
                    finally:
                        if not shutdown_task.done():
                            shutdown_task.cancel()
        except (aiohttp.ClientError, OSError) as exc:
            logger.warning("Connection failed: %s", exc)

        if not shutdown.is_set():
            logger.info("Reconnecting in %ds...", backoff)
            try:
                await asyncio.wait_for(shutdown.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 2, max_backoff)

    # Graceful shutdown: signal workers to stop and wait
    if _workers:
        logger.info("Shutting down %d worker(s)...", len(_workers))
        for q in _queues.values():
            q.put_nowait(None)  # Sentinel
        done, pending = await asyncio.wait(
            list(_workers.values()), timeout=30
        )
        for task in pending:
            task.cancel()
        if pending:
            logger.warning("Cancelled %d worker(s) after timeout", len(pending))

    if _backend:
        await _backend.close()

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
    if _config is None:
        logger.error("_handle_message called before listen()")
        return

    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Non-JSON message: %s", raw[:200])
        return

    logger.debug("Raw: %s", raw[:2000])

    envelope = msg.get("envelope", msg)
    source = envelope.get("source", envelope.get("sourceNumber", "unknown"))
    timestamp = envelope.get("timestamp", "")

    # Deduplicate (WebSocket reconnect can replay messages)
    dedup_key = (source, str(timestamp))
    if dedup_key in _seen:
        logger.debug("Duplicate message %s_%s, skipping", source, timestamp)
        return
    _seen[dedup_key] = None
    if len(_seen) > _SEEN_MAX:
        _seen.popitem(last=False)

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
            job = _VoiceJob(
                attachment=attachment,
                config=_config,
                recipient=recipient,
                quote_timestamp=int(timestamp) if timestamp else 0,
                quote_author=source,
            )
            if recipient not in _queues:
                _queues[recipient] = asyncio.Queue()
                _workers[recipient] = asyncio.create_task(
                    _recipient_worker(recipient)
                )
            _queues[recipient].put_nowait(job)

    elif data_message.get("message"):
        logger.info("Text message from %s", source)
    else:
        logger.info("Message from %s (no text, no voice)", source)


async def _recipient_worker(recipient: str) -> None:
    """Process voice messages for a single recipient in order."""
    queue = _queues[recipient]
    try:
        while True:
            try:
                job = await asyncio.wait_for(queue.get(), timeout=300)
            except asyncio.TimeoutError:
                # wait_for cancels queue.get() on timeout; a put_nowait()
                # at the boundary can leave an item in the queue with no
                # consumer (CPython issue #92824).  Re-check before exiting.
                if queue.empty():
                    break
                continue
            if job is None:  # Sentinel for shutdown
                break
            try:
                await _process_voice_message(
                    attachment=job.attachment,
                    config=job.config,
                    recipient=job.recipient,
                    quote_timestamp=job.quote_timestamp,
                    quote_author=job.quote_author,
                )
            finally:
                queue.task_done()
    finally:
        _queues.pop(recipient, None)
        _workers.pop(recipient, None)
        logger.debug("Worker for %s exited", recipient)


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

        assert _backend is not None
        result = await _backend.transcribe(audio_path)
        formatted = await format_transcript(result, config)

        reply_text = f"Transcription:\n\n{formatted}"
        chunks = split_message(reply_text)
        await send_reply(config, recipient, chunks[0], quote_timestamp, quote_author)
        for chunk in chunks[1:]:
            await send_reply(config, recipient, chunk, 0, quote_author)

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
