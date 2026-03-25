#!/bin/bash
# Link as secondary device (no extra phone number needed)
# Usage: ./link-device.sh
SIGNAL_API=${SIGNAL_API_URL:-http://localhost:8080}
echo "Open this URL in a browser, then scan the QR code with Signal app:"
echo "$SIGNAL_API/v1/qrcodelink?device_name=voice-transcriber"
echo ""
echo "In Signal app: Settings > Linked Devices > Link New Device"
