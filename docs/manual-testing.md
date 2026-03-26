# Manual E2E Testing Checklist

Run `docker compose up` and test the following scenarios.

## Message ordering

- [ ] DM: Send 3 voice messages in rapid succession (long, short, medium). Verify transcriptions arrive in the same order.
- [ ] Group chat: Send multiple voice messages quickly in a group. Verify order is preserved and replies go to the group.
- [ ] Mixed senders: In a group, have two people send voice messages at roughly the same time. Verify each person's messages are ordered, but they can interleave between senders.

## Graceful shutdown

- [ ] Send a voice message, then immediately `docker compose stop`. Check logs -- the in-flight transcription should complete (or timeout after 30s) before the container exits.

## General voice message handling

- [ ] DM: Send a single short voice message. Verify transcription reply arrives as a quote-reply to the original.
- [ ] DM: Send a very long voice message (> 1800 chars when transcribed). Verify it splits into multiple messages.
- [ ] Note to Self / Sync message: Send a voice message from a linked device. Verify it transcribes correctly and replies to the right conversation.

## Resilience

- [ ] WebSocket reconnection: `docker compose stop signal-api`, wait a few seconds, `docker compose start signal-api`. Send a voice message and verify the bot reconnects and transcribes it.
- [ ] GPT formatting fallback: Set `GPT_MODEL=nonexistent-model` with `ENABLE_GPT_FORMATTING=true`. Send a voice message and verify the raw transcript still arrives.

## Privacy modes

- [ ] `TRANSCRIBE_MODE=own_only`: Send a voice message from the bot's own number -- should transcribe. Send from another number -- should be ignored.
- [ ] `TRANSCRIBE_MODE=allowlist` with `ALLOWED_NUMBERS=+1234...`: Send from an allowed number -- transcribes. Send from a non-allowed number -- ignored.

## Error handling

- [ ] Send a voice message while OpenAI API is unreachable (e.g., invalid API key). Verify "Could not transcribe" error reply is sent.
- [ ] Send a non-voice audio attachment (e.g., an MP3 file with a filename). Verify it is NOT transcribed.
- [ ] Send a voice message larger than `MAX_AUDIO_SIZE_MB`. Verify it is silently skipped (check logs).

## Startup validation

- [ ] Remove `OPENAI_API_KEY` from `.env`. Verify container exits immediately with a clear error.
- [ ] Set `TRANSCRIBE_MODE=invalid`. Verify container exits with a clear error.

## Docker

- [ ] `docker compose up` -- verify transcriber waits for signal-api to be healthy before connecting.
- [ ] `docker exec signal-transcriber whoami` -- should return `transcriber`, not `root`.
