# Signal Voice Message Transcriber Bot — Development Spec

## Project overview
Build a Signal messenger bot that monitors all conversations (individual and group) for
voice messages, transcribes them using OpenAI's Whisper API, optionally formats the
transcript with GPT, and replies to the original voice message with the transcription text.

This is an adaptation of an existing Telegram voice transcriber that uses Telethon + Whisper + GPT.
The Signal version replaces only the messenger I/O layer; the AI pipeline is identical.

## Technology stack
- **Python 3.11+** with asyncio
- **signal-cli-rest-api** (Docker, bbernhard/signal-cli-rest-api:latest, json-rpc mode)
- **signalbot** Python framework (pip install signalbot) — OR direct WebSocket + REST calls 
  with aiohttp if signalbot's Command model is too constraining for this use case
- **OpenAI Python SDK** (pip install openai) for Whisper API and GPT API
- **Docker Compose** for the full stack

## Registration mode
- **Linked device (recommended for personal use):** Link the bot as a secondary device 
  on your own Signal account via QR code. No new user appears in any chat. Transcription 
  replies come from you. Your friend sees a normal text reply, not a bot. This mirrors 
  how the original Telegram transcriber works. Uses one of your 3 linked device slots.
- **Dedicated number (for multi-user or group scenarios):** Register the bot with its own 
  phone number. Appears as a separate user. Requires being added to group chats or 
  receiving forwarded messages. More complex but avoids sharing your identity.
- Default to linked device. The registration scripts support both paths.

## Architecture decision: signalbot vs raw WebSocket
Evaluate both approaches during implementation:

### Option A: signalbot framework
- Pro: Built-in WebSocket management, async command handling, testing utilities
- Con: Command model is keyword-triggered; voice messages have no text to trigger on.
  You may need to subclass Command and override the matching logic to trigger on 
  attachment presence rather than text content. Check if signalbot v0.25.0 supports
  a catch-all handler or raw message access.

### Option B: Direct aiohttp WebSocket + REST
- Pro: Full control over message filtering and flow
- Con: Must manage WebSocket reconnection, heartbeat, error handling yourself
- Implementation: Connect to ws://signal-api:8080/v1/receive/{number}, parse JSON 
  envelopes, filter for audio attachments, call Whisper, POST reply to /v2/send

Choose whichever results in cleaner, more maintainable code. Option B may be simpler
for this specific use case since we need raw message access, not keyword commands.

## Core message flow
1. Receive message envelope via WebSocket from signal-cli-rest-api
2. Check if envelope contains attachments with audio content type
3. Identify voice messages specifically:
   - Primary: Check for `voiceNote: true` flag in attachment metadata
   - Fallback: contentType starts with "audio/" AND filename is null
   - Handle edge cases: "audio/*" (known Signal bug), "audio/aac", "audio/mpeg"
4. Download the attachment file:
   - Option A: Read directly from shared Docker volume at 
     /home/.local/share/signal-cli/attachments/{attachment_id}
   - Option B: GET /v1/attachments/{attachment_id} from REST API
5. Save with .m4a extension (Signal voice messages are AAC codec)
6. Submit to OpenAI Whisper API:
   ```python
   from openai import OpenAI
   client = OpenAI()
   with open(audio_path, "rb") as f:
       transcript = client.audio.transcriptions.create(
           model="whisper-1",
           file=f,
           response_format="text"
       )
   ```
7. Optionally format with GPT (clean up punctuation, paragraphs, etc.):
   ```python
   formatted = client.chat.completions.create(
       model="gpt-4o-mini",
       messages=[
           {"role": "system", "content": "Clean up this voice transcription. Fix punctuation, "
            "add paragraph breaks where appropriate. Do not change the meaning or words. "
            "If the transcription is in a non-English language, keep it in that language."},
           {"role": "user", "content": transcript}
       ]
   )
   ```
8. Send quote-reply with transcription:
   ```python
   import aiohttp
   async with aiohttp.ClientSession() as session:
       await session.post(f"{SIGNAL_API_URL}/v2/send", json={
           "message": formatted_text,
           "number": BOT_NUMBER,
           "recipients": [sender_number],  # or group ID for group messages
           "quote_timestamp": original_message_timestamp,
           "quote_author": original_sender_number,
           "quote_message": "🎤 Voice message"
       })
   ```

## Docker Compose configuration
```yaml
version: "3.8"
services:
  signal-api:
    image: bbernhard/signal-cli-rest-api:latest
    container_name: signal-api
    restart: unless-stopped
    environment:
      - MODE=json-rpc
      - JSON_RPC_TRUST_NEW_IDENTITIES=on-first-use
    ports:
      - "127.0.0.1:8080:8080"
    volumes:
      - signal-data:/home/.local/share/signal-cli

  transcriber:
    build: .
    container_name: signal-transcriber
    restart: unless-stopped
    depends_on:
      signal-api:
        condition: service_started
    environment:
      - SIGNAL_API_URL=http://signal-api:8080
      - SIGNAL_NUMBER=${SIGNAL_NUMBER}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - GPT_MODEL=gpt-4o-mini
      - WHISPER_MODEL=whisper-1
      - ENABLE_GPT_FORMATTING=true
      - LOG_LEVEL=INFO
    volumes:
      - signal-data:/home/.local/share/signal-cli:ro

volumes:
  signal-data:
```

## Dockerfile for the transcriber service
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "-m", "signal_transcriber"]
```

## Project structure
```
signal-voice-transcriber/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt          # aiohttp, openai, python-dotenv
├── .env.example              # SIGNAL_NUMBER, OPENAI_API_KEY
├── signal_transcriber/
│   ├── __init__.py
│   ├── __main__.py           # Entry point: start WebSocket listener
│   ├── config.py             # Environment variable loading with defaults
│   ├── listener.py           # WebSocket connection to signal-cli-rest-api
│   ├── transcriber.py        # Whisper API integration
│   ├── formatter.py          # GPT formatting (optional)
│   ├── signal_client.py      # REST API calls (send message, get attachment)
│   └── utils.py              # Audio format detection, attachment cleanup
├── scripts/
│   ├── register.sh           # Helper script for initial registration
│   └── link-device.sh        # Helper script for QR code linking
└── README.md
```

## Key implementation details

### Privacy / consent filtering
- TRANSCRIBE_MODE env var controls whose voice messages get sent to OpenAI:
  - "own_only" (default) — only transcribe voice messages sent by SIGNAL_NUMBER
  - "allowlist" — transcribe voice messages from numbers listed in ALLOWED_NUMBERS
  - "all" — transcribe all voice messages (use only if all contacts are informed)
- ALLOWED_NUMBERS: comma-separated list of phone numbers (e.g., "+14155551234,+14155555678")
- In "own_only" and "allowlist" modes, voice messages from non-matching senders 
  are silently ignored — no download, no API call, no logging of message content.
- Log a short INFO line when a voice message is skipped ("Skipped voice message (sender not in allowlist)") without logging the sender's number.

### WebSocket listener (listener.py)
- Connect to ws://signal-api:8080/v1/receive/{number}
- Implement automatic reconnection with exponential backoff (start 1s, max 60s)
- Handle WebSocket ping/pong for keepalive
- Parse each message as JSON envelope
- Extract from envelope: source (sender), timestamp, groupInfo (if group), 
  dataMessage.attachments array
- For each audio attachment, spawn an async task for transcription
- Graceful shutdown on SIGTERM/SIGINT

### Attachment handling (signal_client.py)
- Try reading from shared volume first: /home/.local/share/signal-cli/attachments/{id}
- Fall back to REST API: GET /v1/attachments/{id}
- Save to temp file with .m4a extension
- Delete temp file after transcription completes
- Implement periodic cleanup of old attachments from the signal-cli directory

### Voice message detection (utils.py)
```python
def is_voice_message(attachment: dict) -> bool:
    """Detect if an attachment is a voice message."""
    # Primary check: voiceNote flag
    if attachment.get("voiceNote", False):
        return True
    # Fallback heuristic: audio type with no filename
    content_type = attachment.get("contentType", "")
    filename = attachment.get("filename")
    if content_type.startswith("audio/") and filename is None:
        return True
    return False
```

### Reply handling for groups vs direct messages
- For direct (1:1) messages: recipients = [sender_number]
- For group messages: recipients = ["group.{base64_group_id}"]
- Group ID is in envelope.dataMessage.groupInfo.groupId
- Always include quote_timestamp and quote_author for proper reply threading

### Error handling requirements
- Whisper API timeout/failure: Reply with error emoji reaction, log error, don't crash
- Signal API unavailable: Queue messages, retry with backoff
- Malformed audio: Catch transcription errors, reply with "Could not transcribe"
- WebSocket disconnect: Auto-reconnect with backoff
- Large voice messages (>25MB, unlikely): Skip with notification

### Configuration (config.py)
```python
from dataclasses import dataclass, field
import os

@dataclass
class Config:
    signal_api_url: str = field(default_factory=lambda: os.getenv("SIGNAL_API_URL", "http://signal-api:8080"))
    signal_number: str = field(default_factory=lambda: os.getenv("SIGNAL_NUMBER", ""))
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    whisper_model: str = field(default_factory=lambda: os.getenv("WHISPER_MODEL", "whisper-1"))
    gpt_model: str = field(default_factory=lambda: os.getenv("GPT_MODEL", "gpt-4o-mini"))
    enable_formatting: bool = field(default_factory=lambda: os.getenv("ENABLE_GPT_FORMATTING", "true").lower() == "true")
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    attachment_dir: str = field(default_factory=lambda: os.getenv("ATTACHMENT_DIR", "/home/.local/share/signal-cli/attachments"))
    cleanup_interval_hours: int = field(default_factory=lambda: int(os.getenv("CLEANUP_INTERVAL_HOURS", "24")))
    max_audio_size_mb: int = field(default_factory=lambda: int(os.getenv("MAX_AUDIO_SIZE_MB", "25")))
```

## Registration helper scripts

### scripts/register.sh
```bash
#!/bin/bash
# Register a new phone number with signal-cli-rest-api
# Usage: ./register.sh +1234567890 "captcha-token"
SIGNAL_API=${SIGNAL_API_URL:-http://localhost:8080}
NUMBER=$1
CAPTCHA=$2

echo "Registering $NUMBER..."
curl -s -X POST -H "Content-Type: application/json" \
  -d "{\"captcha\": \"$CAPTCHA\", \"use_voice\": false}" \
  "$SIGNAL_API/v1/register/$NUMBER"

echo ""
echo "Enter verification code received via SMS:"
read CODE
curl -s -X POST "$SIGNAL_API/v1/register/$NUMBER/verify/$CODE"
echo ""
echo "Registration complete. Test with:"
echo "curl $SIGNAL_API/v1/accounts"
```

### scripts/link-device.sh
```bash
#!/bin/bash
# Link as secondary device (no extra phone number needed)
# Usage: ./link-device.sh
SIGNAL_API=${SIGNAL_API_URL:-http://localhost:8080}
echo "Open this URL in a browser, then scan the QR code with Signal app:"
echo "$SIGNAL_API/v1/qrcodelink?device_name=voice-transcriber"
echo ""
echo "In Signal app: Settings > Linked Devices > Link New Device"
```

## Testing approach
- Unit test voice message detection with sample attachment metadata dicts
- Unit test audio format handling (.m4a, .aac edge cases)
- Integration test with signal-cli-rest-api running in Docker (send yourself a voice message)
- Mock OpenAI API calls for fast test iteration
- signalbot provides ChatTestCase if using that framework

## Known gotchas to handle in code
1. signal-cli versions expire after ~3 months — log a warning if Docker image is old
2. Safety number changes — JSON_RPC_TRUST_NEW_IDENTITIES=on-first-use handles this
3. Forwarded voice messages may have contentType "audio/*" instead of "audio/aac"
4. Group messages need group.{id} as recipient, not individual phone numbers
5. quote_timestamp must be an integer (milliseconds since epoch), not a string
6. WebSocket connection drops silently — implement ping monitoring and reconnection
7. signal-cli-rest-api WebSocket only works in json-rpc mode, not normal/native mode
8. Registration only works in MODE=normal or MODE=native — json-rpc mode does not support it. Register first with MODE=normal, then switch to MODE=json-rpc for production use.