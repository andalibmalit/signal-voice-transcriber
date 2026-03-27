# Signal Voice Transcriber

A self-hosted bot that automatically transcribes voice messages in Signal. Uses [faster-whisper](https://github.com/SYSTRAN/faster-whisper) for free, private, local transcription by default — audio never leaves your machine. Optionally use OpenAI's Whisper API and GPT formatting as a cloud alternative.

## How it works

1. Connects to [signal-cli-rest-api](https://github.com/bbernhard/signal-cli-rest-api) via WebSocket
2. Detects incoming voice messages (voiceNote flag or audio content type heuristic)
3. Downloads the audio attachment via the signal-cli REST API
4. Transcribes the audio locally with faster-whisper (or OpenAI Whisper API if configured)
5. Formats the transcript with pause-based paragraph breaks (or GPT if enabled)
6. Replies to the original voice message with the transcription

## Setup

### Prerequisites

- Docker and Docker Compose
- A Signal account (existing or dedicated number)
- No API keys required for default local transcription

### 1. Clone and configure

```bash
git clone https://github.com/andalibmalit/signal-voice-transcriber.git
cd signal-voice-transcriber
cp .env.example .env
# Edit .env with your values (at minimum: SIGNAL_NUMBER)
```

### 2. Start the stack

```bash
docker compose up -d
```

The first startup downloads the Whisper model (~500 MB for `small`). Subsequent starts use the cached model from the `whisper-models` Docker volume.

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

### Core

| Variable | Default | Description |
|---|---|---|
| `SIGNAL_NUMBER` | *(required)* | Your Signal phone number (E.164 format) |
| `SIGNAL_API_URL` | `http://signal-api:8080` | signal-cli-rest-api URL |
| `LOG_LEVEL` | `INFO` | Python log level |

### Transcription backend

| Variable | Default | Description |
|---|---|---|
| `TRANSCRIPTION_BACKEND` | `local` | `local` for faster-whisper, `openai` for OpenAI API |
| `WHISPER_MODEL` | `small` | Model size (`tiny`, `base`, `small`, `medium`, `large-v3`) or OpenAI model name (`whisper-1`) |
| `WHISPER_COMPUTE_TYPE` | `int8` | Quantization: `int8`, `float16`, `float32` |
| `WHISPER_DEVICE` | `cpu` | Device: `cpu` or `auto` (auto uses GPU if available) |
| `WHISPER_CPU_THREADS` | `4` | CPU threads for inference |
| `WHISPER_LANGUAGE` | `auto` | Language code (`en`, `de`, etc.) or `auto` |
| `WHISPER_MODEL_DIR` | `/models` | Directory for cached model files |

### OpenAI (optional)

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | *(empty)* | OpenAI API key. Enables cloud transcription and/or GPT formatting |
| `GPT_MODEL` | `gpt-4o-mini` | GPT model for formatting |
| `ENABLE_GPT_FORMATTING` | `false` | Set to `true` + provide API key for GPT formatting |
| `OPENAI_TIMEOUT_SECONDS` | `120` | Timeout for OpenAI API calls (seconds) |
| `MAX_AUDIO_SIZE_MB` | `25` | Skip voice messages larger than this |

### Privacy

| Variable | Default | Description |
|---|---|---|
| `TRANSCRIBE_MODE` | `own_only` | Privacy mode (see below) |
| `ALLOWED_NUMBERS` | *(empty)* | Comma-separated phone numbers for allowlist mode |

## Privacy and consent

By default, all transcription happens locally — audio never leaves your machine. If you configure `TRANSCRIPTION_BACKEND=openai` or `ENABLE_GPT_FORMATTING=true`, audio/text will be sent to OpenAI's servers.

The `TRANSCRIBE_MODE` setting controls whose messages get processed:

| Mode | Behavior |
|---|---|
| `own_only` (default) | Only transcribe your own voice messages. Most private. |
| `allowlist` | Only transcribe messages from numbers in `ALLOWED_NUMBERS`. |
| `all` | Transcribe all voice messages. Only use if all contacts have consented. |

In `own_only` and `allowlist` modes, voice messages from non-matching senders are silently ignored — no download, no API call, no logging of message content.

## Cost

With the default local backend, transcription is **free** — no API costs, no usage limits.

If using OpenAI:
- **Whisper API:** ~$0.006 per minute of audio
- **GPT-4o-mini formatting:** ~$0.0001 per transcript (negligible)

## Development

```bash
# Create a virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install ffmpeg (only needed for OpenAI backend's audio conversion)
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
