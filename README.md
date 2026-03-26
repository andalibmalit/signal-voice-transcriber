# Signal Voice Transcriber

A self-hosted bot that automatically transcribes voice messages in Signal using OpenAI's Whisper API. Optionally cleans up transcripts with GPT. Replies to the original voice message with the transcription text.

## How it works

1. Connects to [signal-cli-rest-api](https://github.com/bbernhard/signal-cli-rest-api) via WebSocket
2. Detects incoming voice messages (voiceNote flag or audio content type heuristic)
3. Downloads the audio attachment via the signal-cli REST API
4. Sends the audio to OpenAI Whisper for transcription
5. Optionally formats the transcript with GPT-4o-mini (punctuation, paragraph breaks)
6. Replies to the original voice message with the transcription

## Setup

### Prerequisites

- Docker and Docker Compose
- An OpenAI API key
- A Signal account (existing or dedicated number)

### 1. Clone and configure

```bash
git clone https://github.com/andalibmalit/signal-voice-transcriber.git
cd signal-voice-transcriber
cp .env.example .env
# Edit .env with your values (at minimum: SIGNAL_NUMBER, OPENAI_API_KEY)
```

### 2. Start the stack

```bash
docker compose up -d
```

### 3. Register your Signal account

#### Option A: Linked device (recommended)

Link the bot as a secondary device on your existing Signal account. No new phone number needed. Transcription replies come from you — your contacts see normal text replies, not a bot.

```bash
# Open this URL in a browser and scan the QR code with Signal > Settings > Linked Devices
echo "http://localhost:8080/v1/qrcodelink?device_name=voice-transcriber"
```

Or use the helper script:

```bash
./scripts/link-device.sh
```

#### Option B: Dedicated number

Register with a separate phone number. The bot appears as its own user.

```bash
./scripts/register.sh +1234567890 "captcha-token"
```

> **Note:** Registration only works when signal-cli-rest-api is in `MODE=normal`. After registration, switch to `MODE=json-rpc` in `docker-compose.yml` for production use.

### 4. Verify

Send yourself a voice message. The bot should reply with a transcription within a few seconds.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `SIGNAL_NUMBER` | *(required)* | Your Signal phone number (E.164 format) |
| `OPENAI_API_KEY` | *(required)* | OpenAI API key |
| `SIGNAL_API_URL` | `http://signal-api:8080` | signal-cli-rest-api URL |
| `WHISPER_MODEL` | `whisper-1` | OpenAI Whisper model |
| `GPT_MODEL` | `gpt-4o-mini` | GPT model for formatting |
| `ENABLE_GPT_FORMATTING` | `true` | Set to `false` to skip GPT formatting |
| `TRANSCRIBE_MODE` | `own_only` | Privacy mode (see below) |
| `ALLOWED_NUMBERS` | *(empty)* | Comma-separated phone numbers for allowlist mode |
| `MAX_AUDIO_SIZE_MB` | `25` | Skip voice messages larger than this |
| `OPENAI_TIMEOUT_SECONDS` | `120` | Timeout for OpenAI API calls (seconds) |
| `LOG_LEVEL` | `INFO` | Python log level |

## Privacy and consent

Voice messages are sent to OpenAI's servers for transcription. The `TRANSCRIBE_MODE` setting controls whose messages get processed:

| Mode | Behavior |
|---|---|
| `own_only` (default) | Only transcribe your own voice messages. Most private. |
| `allowlist` | Only transcribe messages from numbers in `ALLOWED_NUMBERS`. |
| `all` | Transcribe all voice messages. Only use if all contacts have consented. |

In `own_only` and `allowlist` modes, voice messages from non-matching senders are silently ignored — no download, no API call, no logging of message content.

## Cost estimate

- **Whisper:** ~$0.006 per minute of audio
- **GPT-4o-mini formatting:** ~$0.0001 per transcript (negligible)

A typical voice message (30 seconds) costs under $0.01 to transcribe and format.

## Development

```bash
# Create a virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install ffmpeg (required for audio conversion)
# macOS: brew install ffmpeg
# Ubuntu: sudo apt-get install ffmpeg

# Run tests
pytest

# Run locally (outside Docker)
python -m signal_transcriber
```

## Acknowledgments

Inspired by: 
- [voicemail-transcriber](https://github.com/jacksenechal/voicemail-transcriber) — a Telegram voice message transcriber using Telethon + Whisper + GPT. This project adapts the same AI pipeline for Signal.
- [signal-transcriber](https://github.com/FriedrichVoelker/signal-transcriber) by Friedrich Voelker — a Signal voice transcriber using local Whisper in a multi-container setup
