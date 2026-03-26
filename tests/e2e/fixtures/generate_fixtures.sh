#!/bin/bash
# Generate OGG Opus audio fixtures for e2e tests.
# Requires: pip install edge-tts, and ffmpeg on PATH.
# Fallback: uses ffmpeg sine wave if edge-tts is unavailable.
set -euo pipefail
cd "$(dirname "$0")"

generate_tts() {
    local name="$1" text="$2" voice="${3:-en-US-GuyNeural}"
    if command -v edge-tts &>/dev/null; then
        edge-tts --voice "$voice" --text "$text" --write-media "${name}.mp3"
        ffmpeg -y -i "${name}.mp3" -c:a libopus -b:a 24k -ar 48000 "${name}.ogg"
        rm "${name}.mp3"
    else
        echo "edge-tts not found, generating sine wave for ${name}.ogg"
        local duration
        case "$name" in
            short_2s)   duration=2 ;;
            hello_10s)  duration=10 ;;
            long_60s)   duration=60 ;;
            *)          duration=5 ;;
        esac
        ffmpeg -y -f lavfi -i "sine=frequency=440:duration=${duration}" \
            -c:a libopus -b:a 24k -ar 48000 "${name}.ogg"
    fi
    echo "Generated ${name}.ogg ($(wc -c < "${name}.ogg") bytes)"
}

generate_tts "hello_10s" "Hello, this is a test message for the voice transcription bot. It should transcribe this correctly."
generate_tts "short_2s" "Quick test."
generate_tts "long_60s" "$(python3 -c "print(' '.join(['This is sentence number ' + str(i) + '.' for i in range(1, 80)]))")"

echo "Done. Commit the .ogg files to the repo."
