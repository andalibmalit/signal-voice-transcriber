#!/bin/bash
# Generate M4A (AAC) audio fixtures for e2e tests.
# Matches real Signal voice messages (AAC in M4A container).
# Requires: pip install edge-tts, and ffmpeg on PATH.
# Fallback: uses ffmpeg sine wave if edge-tts is unavailable.
set -euo pipefail
cd "$(dirname "$0")"

generate_tts() {
    local name="$1" text="$2" voice="${3:-en-US-GuyNeural}"
    if command -v edge-tts &>/dev/null; then
        edge-tts --voice "$voice" --text "$text" --write-media "${name}.mp3"
        ffmpeg -y -i "${name}.mp3" -c:a aac -b:a 64k "${name}.m4a"
        rm "${name}.mp3"
    else
        echo "edge-tts not found, generating sine wave for ${name}.m4a"
        local duration
        case "$name" in
            short_2s)   duration=2 ;;
            hello_10s)  duration=10 ;;
            long_60s)   duration=60 ;;
            *)          duration=5 ;;
        esac
        ffmpeg -y -f lavfi -i "sine=frequency=440:duration=${duration}" \
            -c:a aac -b:a 64k "${name}.m4a"
    fi
    echo "Generated ${name}.m4a ($(wc -c < "${name}.m4a") bytes)"
}

generate_tts "hello_10s" "Hello, this is a test message for the voice transcription bot. It should transcribe this correctly."
generate_tts "short_2s" "Quick test."
generate_tts "long_60s" "$(python3 -c "print(' '.join(['This is sentence number ' + str(i) + '.' for i in range(1, 80)]))")"

echo "Done. Commit the .m4a files to the repo."
