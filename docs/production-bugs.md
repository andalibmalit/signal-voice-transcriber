# Production Bugs

Bugs discovered by e2e tests that exist in production code.

## 1. `listen()` does not exit WebSocket receive loop on shutdown when idle

**Test**: `test_in_flight_transcription_completes_on_shutdown`

**File**: `signal_transcriber/listener.py`, lines 54-69

**Description**: When the shutdown event is set (via SIGTERM/SIGINT), `listen()` does not break out of the `async for msg in ws:` loop at line 62. It only checks `shutdown.is_set()` at line 63 *after* receiving a new WebSocket message. If the bot is idle (no incoming messages), it hangs indefinitely until the WebSocket heartbeat or connection drops.

**Impact**: `docker compose down` or `kill -TERM` may leave the bot hanging for up to 30s (heartbeat timeout) instead of shutting down promptly. In-flight transcriptions may not complete because the graceful shutdown code (lines 82-92) is never reached.

**Suggested fix**: Use `asyncio.wait()` or `asyncio.create_task(shutdown.wait())` to race the shutdown event against WebSocket message receipt, so the loop exits promptly when shutdown is signalled.
