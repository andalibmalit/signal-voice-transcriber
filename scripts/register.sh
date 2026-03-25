#!/bin/bash
# Register a new phone number with signal-cli-rest-api
# Usage: ./register.sh +1234567890 "captcha-token"
SIGNAL_API=${SIGNAL_API_URL:-http://localhost:8080}
NUMBER=$1
CAPTCHA=$2

echo "Registering $NUMBER..."
curl -s -X POST -H "Content-Type: application/json" \
  -d "{\"captcha\": \"$CAPTCHA\", \"use_voice\": false}" \
  "$SIGNAL_API/v1/register/$NUMBER"

echo ""
echo "Enter verification code received via SMS:"
read CODE
curl -s -X POST "$SIGNAL_API/v1/register/$NUMBER/verify/$CODE"
echo ""
echo "Registration complete. Test with:"
echo "curl $SIGNAL_API/v1/accounts"
