> **Note:** This is a Claude Code prompt spec for adding local transcription support
> to signal-voice-transcriber. It was generated using a Claude.ai research session.
> It adds faster-whisper as the default transcription backend (free, private, no 
> third-party API calls), with OpenAI Whisper API as an opt-in fallback. GPT formatting 
> becomes conditional on API key presence; a pause-based paragraph formatter provides 
> free-tier formatting.
>
> **Key divergences from this spec:**
> - `transcriber.py` was deleted entirely instead of kept and refactored — `_convert_to_m4a()` inlined into `backends.py`; `get_openai_client()` moved to `formatter.py`
> - `create_backend()` validates local model names against a whitelist, raising `ValueError` for unrecognized names (not in spec)
> - `whisper_model_dir` typed as `str | None` — allows `None` to use faster-whisper's default cache dir (`~/.cache/huggingface`); spec specified `str` only
> - E2E `bot` fixture uses real local faster-whisper instead of mocking it; `mock_bot` uses a fully mocked `TranscriptionBackend` protocol (not a mocked `WhisperModel`)
> - `ENABLE_GPT_FORMATTING` default changed from `"true"` to `"false"` — spec describes the intent but doesn't list the default change in the config table

# Local Transcription Support — Development Spec

## Goal

Make the Signal Voice Transcriber fully free, private, and self-contained by default.
No OpenAI API key should be required. Audio should never leave the user's machine
unless they explicitly opt in to a cloud backend.

### What changes

1. **Default backend:** faster-whisper (local, in-process) replaces OpenAI Whisper API
2. **OpenAI API key:** no longer required; becomes opt-in for cloud transcription and GPT formatting
3. **Formatting:** pause-based paragraph insertion (free) by default; GPT formatting when API key is set
4. **Config:** new env vars for backend selection and model size; existing vars remain compatible

### What stays the same

- Signal integration (listener, signal_client, WebSocket reconnection, per-recipient queues)
- Message splitting, dedup, privacy modes, error handling
- All existing tests continue to pass
- Docker Compose structure (signal-api + transcriber)
- Project conventions (async, type hints, small modules)

## Background

Read and understand these files before starting:

- `signal_transcriber/transcriber.py` — current OpenAI Whisper integration
- `signal_transcriber/formatter.py` — current GPT formatting
- `signal_transcriber/config.py` — Config dataclass
- `signal_transcriber/__main__.py` — startup validation
- `signal_transcriber/listener.py` — message processing pipeline (calls transcribe + format)
- `docker-compose.yml` and `Dockerfile` — container setup
- `tests/` — existing unit and e2e tests

## Architecture

### Transcription backend abstraction

Create a `signal_transcriber/backends.py` module with a simple protocol and two
implementations:

```python
from typing import Protocol

class TranscriptionResult:
    """Result from a transcription backend."""
    text: str
    segments: list[Segment] | None  # None for cloud backends
    language: str | None

class Segment:
    """A transcription segment with timing info."""
    text: str
    start: float  # seconds
    end: float    # seconds

class TranscriptionBackend(Protocol):
    async def transcribe(self, audio_path: Path) -> TranscriptionResult: ...
    async def close(self) -> None: ...
```

#### `LocalWhisperBackend`

- Uses `faster-whisper` (the `WhisperModel` class) for in-process transcription
- Runs transcription in a dedicated `ThreadPoolExecutor(max_workers=1)` via
  `loop.run_in_executor()` — CTranslate2 releases the GIL during C++ inference
- Loads model once at startup, reuses for all subsequent transcriptions
- Returns `TranscriptionResult` with segment timing data (used for pause-based formatting)
- Configuration:
  - `WHISPER_MODEL`: model size (default `"small"`) — accepts `"tiny"`, `"base"`,
    `"small"`, `"medium"`, `"large-v3"`, or a HuggingFace model ID
  - `WHISPER_COMPUTE_TYPE`: quantization (default `"int8"`) — `"int8"`, `"float16"`, `"float32"`
  - `WHISPER_LANGUAGE`: language code or `"auto"` (default `"auto"`)
  - `WHISPER_DEVICE`: `"cpu"` or `"auto"` (default `"cpu"`)
  - `WHISPER_CPU_THREADS`: number of threads (default `4`)
- Model is downloaded automatically on first run from HuggingFace Hub and cached
  in a Docker volume at `/models`

```python
class LocalWhisperBackend:
    def __init__(self, config: Config) -> None:
        self._model: WhisperModel | None = None
        self._config = config
        self._executor = ThreadPoolExecutor(max_workers=1)

    def _ensure_model(self) -> WhisperModel:
        if self._model is None:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(
                self._config.whisper_model,
                device=self._config.whisper_device,
                compute_type=self._config.whisper_compute_type,
                cpu_threads=self._config.whisper_cpu_threads,
                download_root=self._config.whisper_model_dir,
            )
        return self._model

    async def transcribe(self, audio_path: Path) -> TranscriptionResult:
        loop = asyncio.get_running_loop()

        def _run() -> TranscriptionResult:
            model = self._ensure_model()
            language = None if self._config.whisper_language == "auto" else self._config.whisper_language
            segments_gen, info = model.transcribe(
                str(audio_path),
                beam_size=5,
                language=language,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=1500),
            )
            segments = []
            text_parts = []
            for seg in segments_gen:
                segments.append(Segment(text=seg.text.strip(), start=seg.start, end=seg.end))
                text_parts.append(seg.text.strip())
            return TranscriptionResult(
                text=" ".join(text_parts),
                segments=segments,
                language=info.language,
            )

        return await loop.run_in_executor(self._executor, _run)

    async def close(self) -> None:
        self._executor.shutdown(wait=False)
```

**Key design decisions:**
- `vad_filter=True` enables Silero VAD to skip silence, improving speed and reducing hallucination
- `vad_parameters=dict(min_silence_duration_ms=1500)` sets the silence threshold at 1.5s — pauses shorter than this are kept within a segment; longer pauses create segment boundaries used for paragraph breaks
- `beam_size=5` matches faster-whisper's default for best accuracy
- No ffmpeg system dependency needed — faster-whisper bundles PyAV for audio decoding

#### `OpenAIWhisperBackend`

- Wraps the existing `transcriber.py` logic (OpenAI SDK `client.audio.transcriptions.create`)
- Returns `TranscriptionResult` with `segments=None` (OpenAI API doesn't return segment timing in text mode)
- Used when `TRANSCRIPTION_BACKEND=openai` and `OPENAI_API_KEY` is set

```python
class OpenAIWhisperBackend:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._client: OpenAI | None = None

    async def transcribe(self, audio_path: Path) -> TranscriptionResult:
        loop = asyncio.get_running_loop()

        def _run() -> TranscriptionResult:
            if self._client is None:
                self._client = OpenAI(
                    api_key=self._config.openai_api_key,
                    timeout=self._config.openai_timeout,
                )
            with open(audio_path, "rb") as f:
                text = self._client.audio.transcriptions.create(
                    model=self._config.whisper_model,
                    file=f,
                    response_format="text",
                )
            return TranscriptionResult(text=text, segments=None, language=None)

        return await loop.run_in_executor(None, _run)

    async def close(self) -> None:
        pass
```

### Backend selection

A factory function in `backends.py` creates the appropriate backend based on config:

```python
def create_backend(config: Config) -> TranscriptionBackend:
    if config.transcription_backend == "openai":
        if not config.openai_api_key:
            raise ValueError("TRANSCRIPTION_BACKEND=openai requires OPENAI_API_KEY")
        return OpenAIWhisperBackend(config)
    # Default: local
    return LocalWhisperBackend(config)
```

### Formatting changes

#### Pause-based paragraph formatter (`formatter.py`)

Add a new function `format_with_pauses()` that uses segment timing data to insert
paragraph breaks at natural pauses:

```python
PAUSE_THRESHOLD = 1.5  # seconds — gap between segments that triggers a paragraph break

def format_with_pauses(result: TranscriptionResult) -> str:
    """Insert paragraph breaks at natural speech pauses using segment timestamps."""
    if not result.segments or len(result.segments) <= 1:
        return result.text

    paragraphs: list[str] = []
    current_paragraph: list[str] = [result.segments[0].text]

    for prev_seg, seg in zip(result.segments, result.segments[1:]):
        gap = seg.start - prev_seg.end
        if gap >= PAUSE_THRESHOLD:
            paragraphs.append(" ".join(current_paragraph))
            current_paragraph = [seg.text]
        else:
            current_paragraph.append(seg.text)

    if current_paragraph:
        paragraphs.append(" ".join(current_paragraph))

    return "\n\n".join(paragraphs)
```

#### Updated formatting pipeline

The `format_transcript()` function becomes:

```python
async def format_transcript(
    result: TranscriptionResult, config: Config
) -> str:
    """Format a transcript. Uses GPT if available, else pause-based breaks."""
    # If GPT formatting is enabled AND an API key is available, use GPT
    if config.enable_formatting and config.openai_api_key:
        try:
            return await _gpt_format(result.text, config)
        except Exception:
            logger.warning("GPT formatting failed, falling back to pause-based", exc_info=True)

    # Fall back to pause-based formatting (always available)
    if result.segments:
        return format_with_pauses(result)

    # No segments (e.g., OpenAI backend without GPT formatting) — return raw text
    return result.text
```

This means:
- **No API key:** pause-based formatting (free, local, decent quality)
- **API key + `ENABLE_GPT_FORMATTING=true`:** GPT formatting (best quality)
- **API key + `ENABLE_GPT_FORMATTING=false`:** pause-based formatting
- **GPT failure:** automatic fallback to pause-based formatting

## Config changes

### New environment variables

| Variable | Default | Description |
|---|---|---|
| `TRANSCRIPTION_BACKEND` | `local` | `local` for faster-whisper, `openai` for OpenAI API |
| `WHISPER_COMPUTE_TYPE` | `int8` | Quantization: `int8`, `float16`, `float32` |
| `WHISPER_DEVICE` | `cpu` | Device: `cpu` or `auto` |
| `WHISPER_CPU_THREADS` | `4` | Number of CPU threads for inference |
| `WHISPER_LANGUAGE` | `auto` | Language code (`en`, `de`, etc.) or `auto` |
| `WHISPER_MODEL_DIR` | `/models` | Directory for cached model files |

### Changed behavior of existing variables

| Variable | Before | After |
|---|---|---|
| `OPENAI_API_KEY` | Required at startup | Optional. Only required if `TRANSCRIPTION_BACKEND=openai` or `ENABLE_GPT_FORMATTING=true` |
| `WHISPER_MODEL` | OpenAI model name (`whisper-1`) | Model size for local (`small`), or OpenAI model name when backend is `openai` |
| `ENABLE_GPT_FORMATTING` | Boolean | Still boolean, but only takes effect when `OPENAI_API_KEY` is set |

### Config dataclass additions

Add these fields to the `Config` dataclass:

```python
transcription_backend: str = field(
    default_factory=lambda: os.getenv("TRANSCRIPTION_BACKEND", "local")
)
whisper_compute_type: str = field(
    default_factory=lambda: os.getenv("WHISPER_COMPUTE_TYPE", "int8")
)
whisper_device: str = field(
    default_factory=lambda: os.getenv("WHISPER_DEVICE", "cpu")
)
whisper_cpu_threads: int = field(
    default_factory=lambda: int(os.getenv("WHISPER_CPU_THREADS", "4"))
)
whisper_language: str = field(
    default_factory=lambda: os.getenv("WHISPER_LANGUAGE", "auto")
)
whisper_model_dir: str = field(
    default_factory=lambda: os.getenv("WHISPER_MODEL_DIR", "/models")
)
```

Update `WHISPER_MODEL` default from `"whisper-1"` to `"small"`.

### Startup validation changes (`__main__.py`)

Remove the hard requirement for `OPENAI_API_KEY`. Replace with:

```python
if config.transcription_backend == "openai" and not config.openai_api_key:
    raise SystemExit("TRANSCRIPTION_BACKEND=openai requires OPENAI_API_KEY")

if config.enable_formatting and not config.openai_api_key:
    logging.getLogger(__name__).info(
        "OPENAI_API_KEY not set — GPT formatting disabled, using pause-based formatting"
    )
```

Remove the ffmpeg check — faster-whisper bundles PyAV and doesn't need system ffmpeg.
Keep the ffmpeg check only if `TRANSCRIPTION_BACKEND=openai` (the existing OpenAI
backend still uses ffmpeg for AAC remuxing).

## Listener integration changes

### `listener.py` changes

The listener needs access to the transcription backend. Pass it through config or
create it at startup:

1. In `listen()`, create the backend once before the WebSocket loop:
   ```python
   backend = create_backend(config)
   ```

2. Pass `backend` to `_process_voice_message()` (add it to `_VoiceJob` or pass separately).

3. In `_process_voice_message()`, replace:
   ```python
   transcript = await transcribe(audio_path, config)
   if config.enable_formatting:
       transcript = await format_transcript(transcript, config)
   reply_text = f"Transcription:\n\n{transcript}"
   ```
   With:
   ```python
   result = await backend.transcribe(audio_path)
   formatted = await format_transcript(result, config)
   reply_text = f"Transcription:\n\n{formatted}"
   ```

4. In the shutdown section, call `await backend.close()`.

### Module cleanup

- `transcriber.py` — Keep but refactor. Move the OpenAI-specific logic into
  `OpenAIWhisperBackend`. The `_convert_to_m4a()` function stays (used by OpenAI backend).
  The `get_openai_client()` function moves into `OpenAIWhisperBackend`.
  The module-level `_openai_client` global is eliminated.
- `formatter.py` — Add `format_with_pauses()`. Update `format_transcript()` signature
  to accept `TranscriptionResult` instead of `str`.

## Dockerfile changes

```dockerfile
FROM python:3.11-slim

# ffmpeg only needed for OpenAI backend's AAC remux; faster-whisper bundles PyAV
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

RUN groupadd -r transcriber && useradd -r -g transcriber transcriber
RUN mkdir -p /models && chown transcriber:transcriber /models
USER transcriber

CMD ["python", "-m", "signal_transcriber"]
```

## docker-compose.yml changes

```yaml
services:
  signal-api:
    image: bbernhard/signal-cli-rest-api:latest
    container_name: signal-api
    restart: unless-stopped
    environment:
      - MODE=json-rpc
      - JSON_RPC_TRUST_NEW_IDENTITIES=on-first-use
    ports:
      - "127.0.0.1:8082:8080"
    volumes:
      - signal-data:/home/.local/share/signal-cli

  transcriber:
    build: .
    container_name: signal-transcriber
    restart: unless-stopped
    depends_on:
      signal-api:
        condition: service_healthy
    environment:
      - SIGNAL_API_URL=http://signal-api:8080
      - SIGNAL_NUMBER=${SIGNAL_NUMBER}
      - TRANSCRIPTION_BACKEND=${TRANSCRIPTION_BACKEND:-local}
      - WHISPER_MODEL=${WHISPER_MODEL:-small}
      - WHISPER_COMPUTE_TYPE=${WHISPER_COMPUTE_TYPE:-int8}
      - WHISPER_CPU_THREADS=${WHISPER_CPU_THREADS:-4}
      - WHISPER_LANGUAGE=${WHISPER_LANGUAGE:-auto}
      # Optional: set these to enable cloud features
      # - OPENAI_API_KEY=${OPENAI_API_KEY}
      # - ENABLE_GPT_FORMATTING=true
      - LOG_LEVEL=INFO
    volumes:
      - signal-data:/home/.local/share/signal-cli
      - whisper-models:/models

volumes:
  signal-data:
  whisper-models:
```

Key changes:
- `OPENAI_API_KEY` is commented out by default
- New `whisper-models` volume persists downloaded models across container restarts
- Model downloads on first startup; subsequent starts use cached model

## requirements.txt changes

```
aiohttp>=3.9,<4
openai>=1.0,<2
python-dotenv>=1.0,<2
faster-whisper>=1.1,<2
pytest>=7,<9
pytest-asyncio>=0.23,<1
```

Add `faster-whisper>=1.1,<2`. This pulls in `ctranslate2` (has pre-built aarch64
wheels) and `huggingface-hub` for model downloads.

Note: the `openai` dependency stays — it's still used for the opt-in cloud backend
and GPT formatting. It's a lightweight SDK with no heavy transitive deps.

## .env.example changes

```bash
# ── Required ──────────────────────────────────────────────────
# Your Signal phone number (E.164 format)
SIGNAL_NUMBER=+1234567890

# ── Signal API ────────────────────────────────────────────────
SIGNAL_API_URL=http://signal-api:8080

# ── Transcription Backend ─────────────────────────────────────
# "local" — faster-whisper, runs on your machine, free, private (default)
# "openai" — OpenAI Whisper API, faster but requires API key and sends audio to OpenAI
TRANSCRIPTION_BACKEND=local

# ── Local Whisper Settings (when TRANSCRIPTION_BACKEND=local) ──
# Model size: tiny, base, small (default), medium, large-v3
# Larger = more accurate but slower. "small" is recommended for most use cases.
WHISPER_MODEL=small

# Quantization: int8 (fastest, default), float16, float32
WHISPER_COMPUTE_TYPE=int8

# CPU threads for inference (default: 4)
WHISPER_CPU_THREADS=4

# Language: "auto" (detect), or ISO code like "en", "de", "es"
WHISPER_LANGUAGE=auto

# ── OpenAI Settings (optional) ────────────────────────────────
# Set these to enable cloud transcription or GPT formatting.
# When unset, the bot runs fully locally with no third-party API calls.
# OPENAI_API_KEY=sk-...
# WHISPER_MODEL=whisper-1  (only when TRANSCRIPTION_BACKEND=openai)

# GPT model for optional transcript formatting (requires OPENAI_API_KEY)
# GPT_MODEL=gpt-4o-mini
# ENABLE_GPT_FORMATTING=true

# ── Privacy / Consent ─────────────────────────────────────────
TRANSCRIBE_MODE=own_only
ALLOWED_NUMBERS=+14155551234,+14155555678

# ── Limits ────────────────────────────────────────────────────
MAX_AUDIO_SIZE_MB=25
OPENAI_TIMEOUT_SECONDS=120

# ── Logging ───────────────────────────────────────────────────
LOG_LEVEL=INFO
```

## Test changes

### Unit tests

#### `tests/test_backends.py` (new)

Test the `LocalWhisperBackend` and `OpenAIWhisperBackend` in isolation:

- **`test_local_backend_transcribes`** — Mock `faster_whisper.WhisperModel` to return
  fake segments. Verify `TranscriptionResult` contains text and segments.
- **`test_local_backend_model_loaded_once`** — Call transcribe twice, verify
  `WhisperModel()` constructor called once (lazy loading + caching).
- **`test_openai_backend_transcribes`** — Mock OpenAI client. Verify it calls
  `audio.transcriptions.create` and returns `TranscriptionResult` with `segments=None`.
- **`test_create_backend_local`** — `create_backend()` with `transcription_backend="local"`.
- **`test_create_backend_openai`** — `create_backend()` with `transcription_backend="openai"` and API key.
- **`test_create_backend_openai_no_key`** — Raises `ValueError`.

#### `tests/test_formatter.py` (update)

Add tests for pause-based formatting:

- **`test_format_with_pauses_inserts_breaks`** — Two segments with 3s gap → two paragraphs.
- **`test_format_with_pauses_no_break_on_short_gap`** — Two segments with 0.5s gap → one paragraph.
- **`test_format_with_pauses_single_segment`** — One segment → returned as-is.
- **`test_format_with_pauses_no_segments`** — `segments=None` → returns raw text.
- **`test_format_transcript_uses_gpt_when_key_set`** — With API key + enable_formatting, GPT is called.
- **`test_format_transcript_uses_pauses_when_no_key`** — Without API key, uses pause-based.
- **`test_format_transcript_falls_back_to_pauses_on_gpt_failure`** — GPT raises, falls back.

Update existing formatter tests to use the new `TranscriptionResult` signature.

#### `tests/test_config.py` (update)

- **`test_default_backend_is_local`** — `Config().transcription_backend == "local"`.
- **`test_openai_api_key_not_required_for_local`** — `Config(openai_api_key="")` with
  `transcription_backend="local"` does not raise.
- **`test_default_whisper_model_is_small`** — `Config().whisper_model == "small"`.

#### `tests/test_transcriber.py` (update)

- Update tests to work with the refactored module. The `_convert_to_m4a` tests stay.
- Tests that mock `get_openai_client` → update to mock `OpenAIWhisperBackend` or
  remove if covered by `test_backends.py`.

### E2E tests

The e2e test fixtures need updating:

- **`bot` fixture** (uses real OpenAI): update to also support `transcription_backend="local"`
  with a mock faster-whisper model, OR keep using real OpenAI for the `requires_openai` tests.
- **`mock_bot` fixture** (no real API): update to use `transcription_backend="local"` with
  a mocked `faster_whisper.WhisperModel`. This eliminates the need for `OPENAI_API_KEY`
  in mock-based e2e tests entirely.
- Add a test verifying the local backend works end-to-end with the mock signal server
  (mock faster-whisper, no OpenAI calls at all).

### Existing test compatibility

All existing tests must continue to pass. Where tests mock `transcriber.get_openai_client`
or `transcriber._openai_client`, update them to mock the new backend interface.
The `conftest.py` `_reset_module_state` fixture should reset `_openai_client` in the
OpenAI backend (if it exists as module state) and any cached local model.

## Implementation order

1. **`signal_transcriber/backends.py`** — `TranscriptionResult`, `Segment`,
   `LocalWhisperBackend`, `OpenAIWhisperBackend`, `create_backend()`.
   Write `tests/test_backends.py` in parallel. All backends mocked.

2. **`signal_transcriber/formatter.py`** — Add `format_with_pauses()`. Update
   `format_transcript()` to accept `TranscriptionResult`. Update `tests/test_formatter.py`.

3. **`signal_transcriber/config.py`** — Add new config fields, change defaults.
   Update `tests/test_config.py`.

4. **`signal_transcriber/__main__.py`** — Relax `OPENAI_API_KEY` requirement. Update
   ffmpeg check logic.

5. **`signal_transcriber/listener.py`** — Integrate backend creation and new formatting
   pipeline. Pass backend through `_VoiceJob` or module-level reference.

6. **`signal_transcriber/transcriber.py`** — Refactor: move OpenAI-specific code to
   `OpenAIWhisperBackend`, keep `_convert_to_m4a` as a utility. Clean up module globals.

7. **`tests/`** — Update all unit tests. Update e2e conftest and fixtures.

8. **`Dockerfile`, `docker-compose.yml`, `.env.example`, `requirements.txt`** — Update
   dependencies, volumes, env vars.

9. **`README.md`, `CLAUDE.md`** — Update documentation to reflect local-first default.

## Validation criteria

- `pytest tests/ -v` passes with no failures
- `docker compose up` starts successfully with NO environment variables other than `SIGNAL_NUMBER`
- First voice message triggers model download (logged), subsequent messages use cache
- Transcription of a 30-second voice message completes in under 30 seconds on ARM (4 cores)
- Transcription of a 5-minute voice message completes in under 5 minutes on ARM (4 cores)
- Reply includes paragraph breaks at natural pauses (2+ second gaps in speech)
- Setting `OPENAI_API_KEY` + `TRANSCRIPTION_BACKEND=openai` restores original behavior
- Setting `OPENAI_API_KEY` + `ENABLE_GPT_FORMATTING=true` with local backend uses
  local transcription + GPT formatting (hybrid mode)
- No network calls to OpenAI or any third party when running in default configuration
  (verifiable by running with `--network=none` on the transcriber container after
  model download)

## Performance expectations on Oracle Cloud Always Free (4 ARM cores, 24GB RAM)

| Model | 30s audio | 5 min audio | RAM | Quality |
|-------|-----------|-------------|-----|---------|
| `tiny` (int8) | ~1s | ~10s | ~200MB | Decent, misses nuance |
| `base` (int8) | ~2s | ~20s | ~350MB | Good for clear audio |
| `small` (int8) | ~5s | ~50s | ~600MB | **Recommended default** |
| `medium` (int8) | ~15s | ~2.5min | ~1.3GB | Near-API quality |
| `large-v3` (int8) | ~40s | ~7min | ~2.5GB | API-equivalent, slow |

The `small` model is the default because it offers the best tradeoff between quality
and speed for typical voice messages. Users sending primarily English messages on
clear phone mics can use `base` for faster responses. Users who need maximum accuracy
can set `WHISPER_MODEL=medium` or `WHISPER_MODEL=large-v3`.

## What is NOT in scope

- **whisper.cpp sidecar architecture** — Adds Docker complexity for marginal speed gain.
  Revisit if faster-whisper proves too slow on ARM.
- **wtpsplit / SaT paragraph segmentation** — Adds ~200MB+ of dependencies (torch or
  onnxruntime) for marginal improvement over pause-based breaks. Not justified for
  personal use on free-tier hardware.
- **Deepgram, AssemblyAI, or other cloud backends** — Can be added later following the
  same `TranscriptionBackend` protocol pattern.
- **Model fine-tuning or custom models** — Out of scope. Users can point `WHISPER_MODEL`
  at any HuggingFace CTranslate2 model.
- **Streaming / real-time transcription** — Voice messages are complete audio files;
  batch processing is appropriate.
- **Speaker diarization** — Single-speaker voice messages don't need it.