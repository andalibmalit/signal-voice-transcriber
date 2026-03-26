# Signal Voice Transcriber

Python 3.11+ async project. Uses signal-cli-rest-api (Docker) + OpenAI Whisper/GPT.

## Background
Inspired by a [Telegram voice transcriber](https://github.com/jacksenechal/voicemail-transcriber) (Telethon + Whisper + GPT). This is a Signal adaptation.
Also see [FriedrichVoelker/signal-transcriber](https://github.com/FriedrichVoelker/signal-transcriber) — similar concept using local Whisper + Node.js orchestrator.

## Commands
- `docker compose up` to run
- `pytest` for tests
- `python -m signal_transcriber` entry point

## Conventions
- Type hints on all functions
- Async throughout (aiohttp, not requests)
- Keep modules small and focused
- Use python-dotenv for config