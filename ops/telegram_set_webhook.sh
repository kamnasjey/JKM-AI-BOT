#!/bin/bash
# Set Telegram webhook to point to our backend
# Usage: ./ops/telegram_set_webhook.sh
#
# Reads from .env:
#   TELEGRAM_BOT_TOKEN
#   TELEGRAM_WEBHOOK_SECRET
#   PUBLIC_BASE_URL
#
# NEVER prints secrets, only success/fail status.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Load .env
if [[ -f "$PROJECT_DIR/.env" ]]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
fi

# Check required vars (without printing values)
if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
    echo "❌ ERROR: TELEGRAM_BOT_TOKEN not set in .env"
    exit 1
fi

if [[ -z "${TELEGRAM_WEBHOOK_SECRET:-}" ]]; then
    echo "❌ ERROR: TELEGRAM_WEBHOOK_SECRET not set in .env"
    exit 1
fi

if [[ -z "${PUBLIC_BASE_URL:-}" ]]; then
    echo "❌ ERROR: PUBLIC_BASE_URL not set in .env (e.g. https://api.jkmcopilot.com)"
    exit 1
fi

WEBHOOK_URL="${PUBLIC_BASE_URL}/api/telegram/webhook?secret=${TELEGRAM_WEBHOOK_SECRET}"

echo "Setting Telegram webhook..."
echo "Target: ${PUBLIC_BASE_URL}/api/telegram/webhook?secret=***MASKED***"

# Call Telegram API
RESPONSE=$(curl -sS -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
    --data-urlencode "url=${WEBHOOK_URL}" \
    --data-urlencode "allowed_updates=[\"message\"]" \
    2>&1)

# Parse response (don't show full response which might have token in errors)
if echo "$RESPONSE" | grep -q '"ok":true'; then
    echo "✅ Webhook set successfully"
    # Show description if present
    DESC=$(echo "$RESPONSE" | grep -o '"description":"[^"]*"' | head -1 || true)
    if [[ -n "$DESC" ]]; then
        echo "   $DESC"
    fi
    exit 0
else
    echo "❌ Failed to set webhook"
    # Show error description only (safe)
    DESC=$(echo "$RESPONSE" | grep -o '"description":"[^"]*"' | head -1 || true)
    if [[ -n "$DESC" ]]; then
        echo "   $DESC"
    fi
    exit 1
fi
