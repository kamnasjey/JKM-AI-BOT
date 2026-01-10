#!/bin/bash
# JKM-AI-BOT Engine Auto-Start Script
# Waits for backend /health to be ok, then POSTs /api/engine/start
# Never prints secrets.

set -euo pipefail

ENV_FILE="/opt/JKM-AI-BOT/.env"
HEALTH_URL="http://127.0.0.1:8000/health"
START_URL="http://127.0.0.1:8000/api/engine/start"
TIMEOUT=180
POLL_INTERVAL=5

log() {
    echo "[$(date -Iseconds)] $1"
}

# Load INTERNAL_API_KEY from .env without printing
if [[ ! -f "$ENV_FILE" ]]; then
    log "ERROR: $ENV_FILE not found"
    exit 1
fi

INTERNAL_API_KEY=$(grep -E '^INTERNAL_API_KEY=' "$ENV_FILE" | cut -d= -f2- | tr -d '"'"'" | tr -d '\r')

if [[ -z "$INTERNAL_API_KEY" ]]; then
    log "ERROR: INTERNAL_API_KEY not found in $ENV_FILE"
    exit 1
fi

log "Waiting for backend health (timeout=${TIMEOUT}s)..."

elapsed=0
while [[ $elapsed -lt $TIMEOUT ]]; do
    health=$(curl -sf "$HEALTH_URL" 2>/dev/null || echo '{"ok":false}')
    ok=$(echo "$health" | grep -o '"ok":true' || true)
    
    if [[ -n "$ok" ]]; then
        log "Health OK"
        break
    fi
    
    sleep $POLL_INTERVAL
    elapsed=$((elapsed + POLL_INTERVAL))
done

if [[ $elapsed -ge $TIMEOUT ]]; then
    log "ERROR: Timeout waiting for health"
    exit 1
fi

# Start engine
log "Starting engine..."
response=$(curl -sf -X POST "$START_URL" \
    -H "x-internal-api-key: $INTERNAL_API_KEY" \
    -H "Content-Type: application/json" \
    2>/dev/null || echo '{"ok":false}')

ok=$(echo "$response" | grep -o '"ok":true' || true)
if [[ -n "$ok" ]]; then
    log "Engine start: OK"
    exit 0
else
    log "Engine start: FAILED (response may contain details)"
    exit 1
fi
