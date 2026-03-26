# Manual E2E Testing Checklist

Run `docker compose up` and test the following scenarios.
Items marked ✅ are covered by automated e2e tests (`pytest tests/e2e/`).
Items marked 🔧 still require manual verification.

## Message ordering

- ✅ DM: Send 3 voice messages in rapid succession (long, short, medium). Verify transcriptions arrive in the same order.
  `test_message_ordering::test_three_messages_same_sender_in_order`
- ✅ Group chat: Send multiple voice messages quickly in a group. Verify order is preserved and replies go to the group.
  `test_group_transcription::test_group_voice_message_replies_to_group`
- ✅ Mixed senders: In a group, have two people send voice messages at roughly the same time. Verify each person's messages are ordered, but they can interleave between senders.
  `test_message_ordering::test_two_senders_interleave_correctly`

## Graceful shutdown

- ✅ Send a voice message, then immediately `docker compose stop`. Check logs -- the in-flight transcription should complete (or timeout after 30s) before the container exits.
  `test_graceful_shutdown::test_in_flight_transcription_completes_on_shutdown`
  **Note:** This test currently fails, exposing a production bug — see `docs/production-bugs.md`.

## General voice message handling

- ✅ DM: Send a single short voice message. Verify transcription reply arrives as a quote-reply to the original.
  `test_dm_transcription::test_single_voice_message_transcribed`
- ✅ DM: Send a very long voice message (> 1800 chars when transcribed). Verify it splits into multiple messages.
  `test_long_message_split::test_long_transcript_splits_into_multiple_replies`
- ✅ Note to Self / Sync message: Send a voice message from a linked device. Verify it transcribes correctly and replies to the right conversation.
  `test_sync_message::test_sync_message_replies_to_destination`

## Resilience

- ✅ WebSocket reconnection: `docker compose stop signal-api`, wait a few seconds, `docker compose start signal-api`. Send a voice message and verify the bot reconnects and transcribes it.
  `test_reconnection::test_reconnects_after_ws_drop`
- ✅ GPT formatting fallback: Set `GPT_MODEL=nonexistent-model` with `ENABLE_GPT_FORMATTING=true`. Send a voice message and verify the raw transcript still arrives.
  `test_gpt_fallback::test_gpt_failure_returns_raw_transcript`

## Privacy modes

- ✅ `TRANSCRIBE_MODE=own_only`: Send a voice message from the bot's own number -- should transcribe. Send from another number -- should be ignored.
  `test_privacy_modes::test_own_only_transcribes_own_number` + `test_own_only_rejects_other_number`
- ✅ `TRANSCRIBE_MODE=allowlist` with `ALLOWED_NUMBERS=+1234...`: Send from an allowed number -- transcribes. Send from a non-allowed number -- ignored.
  `test_privacy_modes::test_allowlist_accepts_listed_number` + `test_allowlist_rejects_unlisted_number`

## Error handling

- ✅ Send a voice message while OpenAI API is unreachable (e.g., invalid API key). Verify "Could not transcribe" error reply is sent.
  `test_error_handling::test_whisper_failure_sends_error_reply`
- ✅ Send a non-voice audio attachment (e.g., an MP3 file with a filename). Verify it is NOT transcribed.
  `test_error_handling::test_audio_file_with_filename_not_transcribed`
- ✅ Send a voice message larger than `MAX_AUDIO_SIZE_MB`. Verify it is silently skipped (check logs).
  `test_error_handling::test_oversized_attachment_skipped`

## Startup validation

- ✅ Remove `OPENAI_API_KEY` from `.env`. Verify container exits immediately with a clear error.
  `test_config::test_missing_openai_api_key_exits` (unit test)
- ✅ Set `TRANSCRIBE_MODE=invalid`. Verify container exits with a clear error.
  `test_config::test_invalid_transcribe_mode_raises` (unit test)

## Docker

- 🔧 `docker compose up` -- verify transcriber waits for signal-api to be healthy before connecting.
  *Requires real Docker Compose orchestration with health checks; cannot be tested in-process.*
- ✅ `docker exec signal-transcriber whoami` -- should return `transcriber`, not `root`.
  `test_startup_validation::test_dockerfile_does_not_run_as_root` (static Dockerfile check)
