> **Note:** This is the original prompt spec used to guide implementation. The final codebase diverges in several ways — see the README and code for current behavior.

# Automated E2E Test Suite — Development Spec

## Project context

This spec adds an automated end-to-end test suite to the Signal Voice Transcriber bot.
The bot connects to signal-cli-rest-api via WebSocket, detects voice messages, transcribes
them with OpenAI Whisper, optionally formats with GPT-4o-mini, and replies with the
transcript as a quote-reply.

The existing manual test checklist lives in `docs/manual-testing.md`. The goal is to
automate every scenario in that checklist — without requiring real Signal accounts,
real phone numbers, or real OpenAI API calls for the default test path.

Read and understand the following files before starting implementation:
- `signal_transcriber/listener.py` — WebSocket listener, message parsing, per-recipient queues
- `signal_transcriber/signal_client.py` — REST calls to signal-cli-rest-api (`/v2/send`, `/v1/attachments`)
- `signal_transcriber/transcriber.py` — Whisper API integration, ffmpeg conversion
- `signal_transcriber/formatter.py` — GPT formatting
- `signal_transcriber/utils.py` — `is_voice_message()`, `split_message()`
- `signal_transcriber/config.py` — Config dataclass
- `signal_transcriber/__main__.py` — Startup validation (env vars, ffmpeg check)
- `docker-compose.yml` and `Dockerfile` — Container setup
- `docs/manual-testing.md` — Full manual checklist to automate
- `tests/` — Existing unit tests (conftest.py, test_listener.py, etc.)

## Architecture overview

The test suite uses a **mock signal-cli-rest-api server** built with `aiohttp`. This mock
replaces the real signal-cli-rest-api container during tests — no Docker, no Signal accounts,
no network calls to Signal servers. OpenAI API calls are also mocked by default.

```
┌─────────────┐    WebSocket     ┌──────────────────┐
│  Transcriber │◄───────────────►│  Mock Signal API  │
│    (SUT)     │    REST calls   │  (aiohttp server) │
│              │────────────────►│                    │
└──────┬───────┘                 └──────────┬─────────┘
       │                                    │
       │  Whisper/GPT calls                 │  Records all sent
       ▼  (mocked)                          │  messages for assertion
┌─────────────┐                  ┌──────────▼─────────┐
│  Mock OpenAI │                 │  Test assertions    │
│  (unittest)  │                 │  (pytest)           │
└─────────────┘                  └────────────────────┘
```

### Why a mock server (not real Signal)

1. **signal-cli-rest-api cannot send voice messages with the `voiceNote` flag.** The
   `/v2/send` endpoint supports audio attachments but has no parameter to set the
   protobuf `VOICE_MESSAGE` flag. A mock server can inject envelopes with `voiceNote: true`.
2. **Signal rate-limits aggressively** (~10 messages before throttling on new accounts).
3. **Registration requires manual captcha** — no automated CI account creation.
4. **Tests must be fast and deterministic.** Real Signal has 2-5s delivery latency per message.

## Technology stack

- **pytest** + **pytest-asyncio** for test orchestration
- **aiohttp** for the mock signal-cli-rest-api server (same library the bot uses)
- **unittest.mock** for OpenAI client mocking
- Pre-recorded `.ogg` audio fixtures for voice message content

### New dependencies

Add to `requirements.txt`:
```
pytest-asyncio>=0.23,<1
```

No other new dependencies. The mock server uses `aiohttp` (already a project dependency).

## File structure

```
tests/
├── conftest.py                    # (existing) Config fixture
├── e2e/
│   ├── __init__.py
│   ├── conftest.py                # e2e fixtures: mock server, bot lifecycle, OpenAI mock
│   ├── mock_signal_server.py      # Mock signal-cli-rest-api (WebSocket + REST)
│   ├── fixtures/                  # Pre-recorded audio files
│   │   ├── hello_10s.ogg          # ~10s voice clip, known transcript: "Hello, this is a test."
│   │   ├── short_2s.ogg           # ~2s clip
│   │   ├── long_60s.ogg           # ~60s clip (produces >1800 char transcript)
│   │   └── generate_fixtures.sh   # Script to regenerate fixtures via edge-tts + ffmpeg
│   ├── test_dm_transcription.py   # DM voice message → transcription reply
│   ├── test_group_transcription.py# Group voice messages
│   ├── test_message_ordering.py   # Rapid-fire messages, ordering guarantees
│   ├── test_long_message_split.py # Transcript >1800 chars splits into multiple replies
│   ├── test_sync_message.py       # Note to Self / linked device sync messages
│   ├── test_privacy_modes.py      # own_only, allowlist, all
│   ├── test_reconnection.py       # WebSocket drop → reconnect → transcribe
│   ├── test_graceful_shutdown.py  # SIGTERM mid-transcription → completes or times out
│   ├── test_gpt_fallback.py       # GPT formatting failure → raw transcript still sent
│   ├── test_error_handling.py     # Whisper failure, non-voice audio, oversized files
│   └── test_startup_validation.py # Missing env vars, invalid config
├── test_config.py                 # (existing)
├── test_formatter.py              # (existing)
├── test_listener.py               # (existing)
├── test_transcriber.py            # (existing)
└── test_utils.py                  # (existing)
```

## Mock signal-cli-rest-api server (`mock_signal_server.py`)

### Overview

A lightweight `aiohttp` web application that mimics the three signal-cli-rest-api
endpoints the bot uses. It runs in-process on a random available port during each
test session.

### Endpoints to implement

#### 1. WebSocket: `GET /v1/receive/{number}`

- Accept WebSocket upgrade.
- Hold the connection open, sending periodic pings (heartbeat).
- Expose a method `inject_envelope(envelope: dict)` that serializes the envelope to
  JSON and sends it over the WebSocket to the connected bot.
- Support multiple concurrent connections (the bot reconnects, so old connections
  may linger briefly).
- Support a `drop_connection()` method that forcibly closes the WebSocket (for
  reconnection tests).

#### 2. REST: `POST /v2/send`

- Accept JSON body.
- Validate expected fields: `message`, `number`, `recipients`.
- Store the full request body in an ordered list: `server.sent_messages`.
- Return `200 OK` with empty JSON body.
- Optionally simulate errors: `server.next_send_status = 500` for error-handling tests.

#### 3. REST: `GET /v1/attachments/{attachment_id}`

- Serve audio file bytes from `tests/e2e/fixtures/` directory.
- The `attachment_id` in the URL maps to a fixture filename via a dict the test
  populates: `server.attachment_map = {"abc123": "hello_10s.ogg"}`.
- Return `200 OK` with `Content-Type: application/octet-stream`.
- Return `404` if attachment_id is not in the map.

#### 4. REST: `GET /v1/about` (optional, for health checks)

- Return `{"versions": {"signal-cli": "0.0.0-mock"}, "mode": "json-rpc"}`.

### Class interface

```python
class MockSignalServer:
    """Mock signal-cli-rest-api for e2e testing."""

    def __init__(self) -> None:
        self.sent_messages: list[dict] = []      # All POST /v2/send payloads
        self.attachment_map: dict[str, str] = {}  # attachment_id -> fixture filename
        self.next_send_status: int = 200          # Override for error tests
        self._ws_connections: list[web.WebSocketResponse] = []

    async def start(self, host: str = "127.0.0.1", port: int = 0) -> str:
        """Start server, return base URL like 'http://127.0.0.1:54321'."""
        ...

    async def stop(self) -> None:
        """Gracefully shut down the server."""
        ...

    async def inject_envelope(self, envelope: dict) -> None:
        """Send a JSON envelope to all connected WebSocket clients."""
        ...

    async def drop_websocket(self) -> None:
        """Forcibly close all WebSocket connections (for reconnection tests)."""
        ...

    def clear(self) -> None:
        """Reset sent_messages and other state between tests."""
        ...

    async def wait_for_messages(self, count: int, timeout: float = 10.0) -> list[dict]:
        """Block until `count` messages have been sent, or timeout. Return the messages."""
        ...
```

The `wait_for_messages` method is critical for test reliability. It should use an
`asyncio.Event` or `asyncio.Condition` that fires each time a message is appended
to `sent_messages`, rather than polling with `asyncio.sleep`.

## Envelope factories

Create helper functions that produce realistic signal-cli-rest-api JSON envelopes.
These are used by tests to inject messages into the mock server.

```python
def make_voice_envelope(
    source: str,
    timestamp: int,
    attachment_id: str = "att_001",
    size: int = 5000,
    content_type: str = "audio/aac",
    voice_note: bool = True,
    group_id: str | None = None,
) -> dict:
    """Build a JSON envelope containing a voice message attachment."""
    attachment = {
        "contentType": content_type,
        "id": attachment_id,
        "size": size,
        "voiceNote": voice_note,
    }
    data_message: dict = {"attachments": [attachment], "timestamp": timestamp}
    if group_id:
        data_message["groupInfo"] = {"groupId": group_id, "type": "DELIVER"}

    return {
        "envelope": {
            "source": source,
            "sourceNumber": source,
            "timestamp": timestamp,
            "dataMessage": data_message,
        }
    }


def make_sync_envelope(
    source: str,
    destination: str,
    timestamp: int,
    attachment_id: str = "att_001",
    size: int = 5000,
) -> dict:
    """Build a syncMessage.sentMessage envelope (Note to Self / linked device)."""
    return {
        "envelope": {
            "source": source,
            "timestamp": timestamp,
            "syncMessage": {
                "sentMessage": {
                    "destination": destination,
                    "timestamp": timestamp,
                    "attachments": [
                        {
                            "contentType": "audio/aac",
                            "id": attachment_id,
                            "size": size,
                            "voiceNote": True,
                        }
                    ],
                }
            },
        }
    }


def make_text_envelope(source: str, timestamp: int, message: str) -> dict:
    """Build a plain text message envelope (should NOT trigger transcription)."""
    ...


def make_audio_file_envelope(
    source: str,
    timestamp: int,
    attachment_id: str = "att_002",
    filename: str = "song.mp3",
) -> dict:
    """Build an audio attachment WITH a filename (not a voice message)."""
    ...
```

Put these in `tests/e2e/conftest.py` or a separate `tests/e2e/envelope_factory.py`.

## Audio fixtures

### Generation

Use `edge-tts` (free, no API key) + `ffmpeg` to generate OGG Opus files that match
Signal's voice message format. Create a script `tests/e2e/fixtures/generate_fixtures.sh`:

```bash
#!/bin/bash
# Requires: pip install edge-tts, and ffmpeg on PATH
set -euo pipefail
cd "$(dirname "$0")"

generate() {
    local name="$1" text="$2" voice="${3:-en-US-GuyNeural}"
    edge-tts --voice "$voice" --text "$text" --write-media "${name}.mp3"
    ffmpeg -y -i "${name}.mp3" -c:a libopus -b:a 24k -ar 48000 "${name}.ogg"
    rm "${name}.mp3"
    echo "Generated ${name}.ogg"
}

generate "hello_10s" "Hello, this is a test message for the voice transcription bot. It should transcribe this correctly."
generate "short_2s" "Quick test."
generate "long_60s" "$(python3 -c "print(' '.join(['This is sentence number ' + str(i) + '.' for i in range(1, 80)]))")"

echo "Done. Commit the .ogg files to the repo."
```

Commit the generated `.ogg` files to the repo (~500KB total). Tests should never
need to run TTS at test time.

### Fixture mapping

In `tests/e2e/conftest.py`, provide a fixture that maps attachment IDs to file paths:

```python
FIXTURES_DIR = Path(__file__).parent / "fixtures"

@pytest.fixture
def audio_fixtures() -> dict[str, Path]:
    return {
        "hello_10s": FIXTURES_DIR / "hello_10s.ogg",
        "short_2s": FIXTURES_DIR / "short_2s.ogg",
        "long_60s": FIXTURES_DIR / "long_60s.ogg",
    }
```

## OpenAI mocking strategy

Mock both the Whisper transcription and GPT formatting at the `openai.OpenAI` client
level. The mock should return deterministic, predictable text so tests can assert on
exact reply content.

```python
@pytest.fixture
def mock_openai(monkeypatch):
    """Mock OpenAI client returning predictable transcriptions."""
    mock_client = MagicMock()

    # Whisper: return the filename stem as the "transcript"
    def fake_transcribe(**kwargs):
        filename = kwargs["file"].name
        transcripts = {
            "hello_10s.ogg": "Hello, this is a test message for the voice transcription bot.",
            "short_2s.ogg": "Quick test.",
            "long_60s.ogg": "x " * 1000,  # >1800 chars to trigger splitting
        }
        # Default: return a generic transcript
        for key, val in transcripts.items():
            if key in filename:
                return val
        return "Transcribed audio."

    mock_client.audio.transcriptions.create.side_effect = fake_transcribe

    # GPT: prefix with "[Formatted] " so tests can detect formatting was applied
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=None))]  # set per-test
    )

    def format_side_effect(**kwargs):
        raw = kwargs["messages"][1]["content"]
        result = MagicMock()
        result.choices = [MagicMock(message=MagicMock(content=f"[Formatted] {raw}"))]
        return result

    mock_client.chat.completions.create.side_effect = format_side_effect

    monkeypatch.setattr(
        "signal_transcriber.transcriber._openai_client", mock_client
    )
    return mock_client
```

### GPT failure simulation

For `test_gpt_fallback.py`, make the GPT mock raise an exception:

```python
mock_client.chat.completions.create.side_effect = RuntimeError("Model not found")
```

The bot should fall back to the raw Whisper transcript. Assert the reply does NOT
contain `"[Formatted]"` but DOES contain the raw transcript text.

### Whisper failure simulation

For `test_error_handling.py`, make the Whisper mock raise:

```python
mock_client.audio.transcriptions.create.side_effect = openai.APIError("Invalid API key")
```

The bot should reply with `"Could not transcribe this voice message."`.

## Bot lifecycle fixture

The bot needs to be started as an async task pointing at the mock server, then
stopped after each test. The critical detail: `listener.listen()` runs forever,
so it must be wrapped in an `asyncio.Task` that gets cancelled on teardown.

```python
@pytest.fixture
async def bot(mock_signal_server, mock_openai):
    """Start the transcriber bot connected to the mock server."""
    config = Config(
        signal_api_url=mock_signal_server.url,  # e.g. "http://127.0.0.1:54321"
        signal_number="+10000000000",
        openai_api_key="test-key",
        whisper_model="whisper-1",
        gpt_model="gpt-4o-mini",
        enable_formatting=True,
        log_level="DEBUG",
        max_audio_size_mb=25,
        transcribe_mode="all",
        allowed_numbers=[],
        openai_timeout=10,
    )

    # Reset module-level state from listener.py between tests
    import signal_transcriber.listener as lmod
    lmod._config = None
    lmod._seen.clear()
    lmod._queues.clear()
    lmod._workers.clear()

    task = asyncio.create_task(listen(config))

    # Wait for WebSocket connection to establish
    await mock_signal_server.wait_for_connection(timeout=5.0)

    yield config

    # Shutdown: send SIGTERM-equivalent by setting shutdown event,
    # or just cancel the task
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
```

**Important:** The `listen()` function installs signal handlers via
`loop.add_signal_handler()`. In test context, either:
- Patch out the signal handler installation (simplest), or
- Use a wrapper that sets the shutdown event instead of relying on OS signals.

Recommend patching: `monkeypatch.setattr("signal_transcriber.listener.signal.SIGTERM", ...)` 
or mocking `loop.add_signal_handler` to capture the shutdown callback for later use.

## Test specifications

Each test below maps to one or more items in `docs/manual-testing.md`.

### test_dm_transcription.py

**`test_single_voice_message_transcribed`**
- Inject a voice envelope from `+11111111111` with attachment `hello_10s`.
- Wait for 1 sent message.
- Assert: `sent_messages[0]["recipients"] == ["+11111111111"]`.
- Assert: `sent_messages[0]["message"]` contains `"Hello, this is a test"`.
- Assert: `sent_messages[0]["quote_timestamp"]` equals the injected timestamp.
- Assert: `sent_messages[0]["quote_author"] == "+11111111111"`.
- Assert: `sent_messages[0]["quote_message"] == "🎤 Voice message"`.

**`test_voice_note_flag_detected`**
- Inject envelope with `voiceNote: True`, `contentType: "audio/aac"`.
- Verify transcription reply is sent.

**`test_audio_wildcard_content_type`**
- Inject envelope with `contentType: "audio/*"`, `filename: None`, `voiceNote: False`.
- Verify transcription reply is sent (fallback heuristic in `is_voice_message`).

### test_group_transcription.py

**`test_group_voice_message_replies_to_group`**
- Inject voice envelope with `group_id = "dGVzdGdyb3Vw"`.
- Wait for 1 sent message.
- Assert: `sent_messages[0]["recipients"] == ["group.dGVzdGdyb3Vw"]`.

### test_message_ordering.py

**`test_three_messages_same_sender_arrive_in_order`**
- Inject 3 voice envelopes from the same sender in rapid succession (timestamps
  1000, 2000, 3000) with distinct attachment IDs mapping to distinct fixture files.
- Wait for 3 sent messages.
- Assert: replies arrive in timestamp order (check by matching transcript content
  to the known fixture transcript for each attachment ID).
- This validates the per-recipient queue and single-worker-per-recipient design.

**`test_two_senders_interleave`**
- Inject: sender A message 1, sender B message 1, sender A message 2.
- Wait for 3 sent messages.
- Assert: sender A's replies are ordered relative to each other.
- Assert: sender B's reply is ordered relative to itself.
- Interleaving between senders is acceptable.

### test_long_message_split.py

**`test_long_transcript_splits_into_multiple_replies`**
- Inject voice envelope with attachment `long_60s` (mock Whisper returns >1800 chars).
- Wait for ≥2 sent messages to the same recipient.
- Assert: first message has `quote_timestamp` set (quote-reply).
- Assert: subsequent messages have `quote_timestamp == 0` (continuation, no quote).
- Assert: concatenated message text equals the full transcript with prefix.

### test_sync_message.py

**`test_sync_message_transcribed_and_replies_to_destination`**
- Inject a `syncMessage.sentMessage` envelope (source = bot's own number,
  destination = `+11111111111`).
- Wait for 1 sent message.
- Assert: `sent_messages[0]["recipients"] == ["+11111111111"]` (replies to the
  conversation partner, not to self).

### test_privacy_modes.py

**`test_own_only_transcribes_own_messages`**
- Set `config.transcribe_mode = "own_only"`, `config.signal_number = "+10000000000"`.
- Inject voice envelope from `+10000000000` → transcription reply sent.
- Inject voice envelope from `+19999999999` → no reply sent.

**`test_own_only_ignores_others`**
- Same as above, but explicitly verify `sent_messages` stays empty after the
  second injection (wait a short timeout, e.g. 2s, and assert length is still 1).

**`test_allowlist_mode`**
- Set `transcribe_mode = "allowlist"`, `allowed_numbers = ["+11111111111"]`.
- Inject from `+11111111111` → reply sent.
- Inject from `+19999999999` → no reply.

**`test_all_mode_transcribes_everyone`**
- Set `transcribe_mode = "all"`.
- Inject from `+19999999999` → reply sent.

### test_reconnection.py

**`test_reconnect_after_websocket_drop`**
- Wait for bot to connect to mock server.
- Call `mock_signal_server.drop_websocket()`.
- Wait for bot to reconnect (mock server's `wait_for_connection` with timeout).
- Inject a voice envelope.
- Wait for 1 sent message.
- Assert: transcription reply was sent successfully after reconnection.

**`test_reconnect_backoff_resets_on_success`**
- Drop connection twice in succession.
- Verify the bot reconnects each time (may take longer on second attempt due to
  backoff, but should still reconnect within the test timeout).

### test_graceful_shutdown.py

**`test_inflight_transcription_completes_on_shutdown`**
- Inject a voice envelope.
- Immediately after injection (before reply is sent), cancel the bot task or
  send the shutdown signal.
- Assert: the reply was still sent (the bot waits up to 30s for in-flight work).

  Implementation note: to make this testable, add a small delay to the mock
  Whisper transcription (e.g. `asyncio.sleep(0.5)` in the mock) so there's a
  window to trigger shutdown while transcription is "in progress".

### test_gpt_fallback.py

**`test_gpt_failure_returns_raw_transcript`**
- Configure `enable_formatting = True`.
- Make GPT mock raise `RuntimeError`.
- Inject voice envelope.
- Wait for 1 sent message.
- Assert: reply contains the raw Whisper transcript (no `"[Formatted]"` prefix).

**`test_gpt_disabled_skips_formatting`**
- Configure `enable_formatting = False`.
- Inject voice envelope.
- Wait for 1 sent message.
- Assert: GPT mock was never called.
- Assert: reply contains raw transcript.

### test_error_handling.py

**`test_whisper_failure_sends_error_reply`**
- Make Whisper mock raise `openai.APIError`.
- Inject voice envelope.
- Wait for 1 sent message.
- Assert: `sent_messages[0]["message"] == "Could not transcribe this voice message."`.

**`test_non_voice_audio_ignored`**
- Inject envelope with `contentType: "audio/mpeg"`, `filename: "song.mp3"`.
- Wait briefly (2s).
- Assert: `sent_messages` is empty.

**`test_oversized_attachment_skipped`**
- Inject voice envelope with `size: 30_000_000` (30 MB, exceeds `max_audio_size_mb=25`).
- Wait briefly (2s).
- Assert: `sent_messages` is empty (silently skipped).
- Assert: no download was attempted (check mock server's attachment request log).

**`test_non_voice_attachment_ignored`**
- Inject envelope with `contentType: "image/jpeg"`.
- Assert: no transcription attempted.

### test_startup_validation.py

These tests do NOT use the mock server. They test the `__main__.main()` function
directly with invalid config.

**`test_missing_openai_key_exits`** (already exists in `test_config.py` — skip or move)

**`test_missing_signal_number_exits`** (already exists — skip or move)

**`test_invalid_transcribe_mode_exits`**
- Set `TRANSCRIBE_MODE=invalid`.
- Assert `Config()` raises `ValueError`.

**`test_missing_ffmpeg_exits`** (already exists — skip or move)

**`test_dockerfile_uses_non_root_user`**
- Read `Dockerfile`, assert it contains a `USER` directive that is not `root`.
- This is a static check, not a runtime test.

## Implementation order

Implement in this sequence. Each step should be a separate commit that passes all
existing tests plus the new ones added in that step.

1. **`mock_signal_server.py`** — The mock server with WebSocket, `/v2/send`, and
   `/v1/attachments` endpoints. Include the `wait_for_messages` and
   `wait_for_connection` helpers. Write a small standalone test that verifies the
   mock server starts, accepts WebSocket connections, injects envelopes, records
   sent messages, and serves attachment files.

2. **`conftest.py` fixtures** — `mock_signal_server`, `mock_openai`, `bot`,
   envelope factories, audio fixtures dict.

3. **Audio fixtures** — Run `generate_fixtures.sh` and commit the `.ogg` files.
   If `edge-tts` is unavailable, generate minimal valid OGG files with ffmpeg:
   `ffmpeg -f lavfi -i "sine=frequency=440:duration=2" -c:a libopus out.ogg`.

4. **`test_dm_transcription.py`** — The most basic happy-path test. Getting this
   green proves the full mock → bot → mock pipeline works.

5. **`test_group_transcription.py`** and **`test_sync_message.py`**.

6. **`test_message_ordering.py`** — Validates the per-recipient queue design.

7. **`test_long_message_split.py`**.

8. **`test_privacy_modes.py`**.

9. **`test_reconnection.py`**.

10. **`test_graceful_shutdown.py`** — May require refactoring `listen()` to make
    the shutdown event injectable rather than relying on OS signals. See notes below.

11. **`test_gpt_fallback.py`** and **`test_error_handling.py`**.

12. **`test_startup_validation.py`** — Move existing tests from `test_config.py`
    if appropriate, add the Dockerfile static check.

## Key implementation details

### Signal handler patching

`listener.listen()` calls `loop.add_signal_handler(signal.SIGTERM, shutdown.set)`.
In pytest's event loop, this may conflict with pytest-asyncio's own signal handling.
Two options:

**Option A (preferred): Refactor `listen()` to accept an optional shutdown event.**
```python
async def listen(config: Config, _shutdown: asyncio.Event | None = None) -> None:
    shutdown = _shutdown or asyncio.Event()
    if _shutdown is None:
        # Only install signal handlers when not in test mode
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, shutdown.set)
    ...
```
Tests pass their own `asyncio.Event` and set it to trigger shutdown.

**Option B: Monkeypatch `loop.add_signal_handler` to be a no-op in tests.**

Option A is cleaner and makes the code more testable. It's a minimal, backwards-
compatible change (the parameter is optional with a default of `None`).

### Module-level state cleanup

`listener.py` uses module-level state: `_config`, `_seen`, `_queues`, `_workers`.
The `bot` fixture MUST reset all of these before each test. The existing unit tests
in `test_listener.py` already do this with `autouse` fixtures — follow the same
pattern in the e2e conftest.

Also reset `transcriber._openai_client = None` between tests to ensure the mock
client is picked up fresh.

### Async test configuration

All e2e tests should use `@pytest.mark.asyncio` and run in a single event loop
per test. Configure pytest-asyncio in `pyproject.toml` or `pytest.ini`:

```ini
[tool:pytest]
asyncio_mode = auto
```

Or use explicit markers on each test. Either approach is fine — be consistent.

### Timeout discipline

Every `wait_for_messages` call should have an explicit timeout (default 10s).
If a test times out, it should fail with a clear message like:
`"Expected 3 messages but only received 1 after 10s"`.

Do NOT use `asyncio.sleep()` for synchronization. Always use event-based waiting
(`asyncio.Event`, `asyncio.Condition`, or the mock server's `wait_for_messages`).

### pytest markers

Tag e2e tests so they can be run separately:

```python
# tests/e2e/conftest.py
import pytest
pytestmark = pytest.mark.e2e
```

```ini
# pyproject.toml or pytest.ini
[tool:pytest]
markers =
    e2e: End-to-end tests using mock signal server
```

This allows `pytest -m e2e` to run only e2e tests, or `pytest -m "not e2e"` to
skip them for fast unit-test-only runs.

## Validation criteria

A test is considered correct if:
1. It passes reliably 50 consecutive times with no flakes (`pytest --count=50`
   with `pytest-repeat`, or a simple shell loop).
2. It completes in under 15 seconds (individual test, not suite).
3. It does not depend on test execution order.
4. It does not leave any state (temp files, module globals, running tasks) after
   teardown.

The full e2e suite should complete in under 60 seconds total.

## What is NOT in scope

- **Real Signal infrastructure tests.** No Docker-in-Docker, no real signal-cli-rest-api
  containers, no real phone numbers. These remain manual per `docs/manual-testing.md`.
- **Real OpenAI API calls.** All Whisper and GPT calls are mocked. A future enhancement
  could add an optional `--live-openai` flag for nightly runs.
- **TTS generation at test time.** Audio fixtures are pre-generated and committed.
- **CI/CD pipeline configuration.** The spec covers the test code only. Setting up
  GitHub Actions or similar is a separate task.
- **Load testing or performance benchmarking.**