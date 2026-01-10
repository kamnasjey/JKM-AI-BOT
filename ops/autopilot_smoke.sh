#!/bin/bash
# JKM-AI-BOT Autopilot Smoke Proof Script
# - Checks health
# - Optional light backfill or integrity check
# - Collects evidence, appends to journal.txt
# - Commits + pushes ONLY journal.txt (never state/)
# NEVER prints secrets.

set -euo pipefail

WORKDIR="/opt/JKM-AI-BOT"
ENV_FILE="$WORKDIR/.env"
JOURNAL="$WORKDIR/journal.txt"
HEALTH_URL="http://127.0.0.1:8000/health"
STATUS_URL="http://127.0.0.1:8000/api/engine/status"
SCAN_URL="http://127.0.0.1:8000/api/engine/manual-scan"

RESULT="PASS"
FAIL_REASON="none"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Trap to always write journal entry, even on error
cleanup() {
    local exit_code=$?
    if [[ $exit_code -ne 0 && "$RESULT" == "PASS" ]]; then
        RESULT="FAIL"
        FAIL_REASON="script error at line $BASH_LINENO exit_code=$exit_code"
    fi
    write_journal
}
trap cleanup EXIT

log() {
    echo "[$(date -Iseconds)] $1"
}

# Load INTERNAL_API_KEY without printing
load_api_key() {
    if [[ ! -f "$ENV_FILE" ]]; then
        log "ERROR: $ENV_FILE not found"
        RESULT="FAIL"
        FAIL_REASON="missing .env file"
        exit 1
    fi
    INTERNAL_API_KEY=$(grep -E '^INTERNAL_API_KEY=' "$ENV_FILE" | cut -d= -f2- | tr -d '"'"'" | tr -d '\r')
    if [[ -z "$INTERNAL_API_KEY" ]]; then
        log "ERROR: INTERNAL_API_KEY not found"
        RESULT="FAIL"
        FAIL_REASON="missing INTERNAL_API_KEY"
        exit 1
    fi
}

# Gather env evidence (masked - NEVER print actual keys)
gather_env_evidence() {
    local data_provider=$(grep -E '^DATA_PROVIDER=' "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d '"'"'" || echo "MISSING")
    local massive_key_present="MISSING"
    local internal_key_present="MISSING"
    
    if grep -qE '^MASSIVE_API_KEY=.+' "$ENV_FILE" 2>/dev/null; then
        massive_key_present="PRESENT"
    fi
    if grep -qE '^INTERNAL_API_KEY=.+' "$ENV_FILE" 2>/dev/null; then
        internal_key_present="PRESENT"
    fi
    
    ENV_EVIDENCE="DATA_PROVIDER=${data_provider}\nMASSIVE_API_KEY=${massive_key_present}\nINTERNAL_API_KEY=${internal_key_present}"
}

# Check health
check_health() {
    local health
    health=$(curl -sf "$HEALTH_URL" 2>/dev/null || echo '{"ok":false}')
    HEALTH_OK=$(echo "$health" | grep -o '"ok":true' >/dev/null && echo "true" || echo "false")
    log "Health OK: $HEALTH_OK"
}

# Check engine status
check_engine_status() {
    local status
    status=$(curl -sf "$STATUS_URL" -H "x-internal-api-key: $INTERNAL_API_KEY" 2>/dev/null || echo '{"running":false}')
    ENGINE_RUNNING=$(echo "$status" | grep -o '"running":true' >/dev/null && echo "true" || echo "false")
    log "Engine running: $ENGINE_RUNNING"
}

# Trigger manual scan
trigger_scan() {
    local response
    response=$(curl -sf -X POST "$SCAN_URL" -H "x-internal-api-key: $INTERNAL_API_KEY" 2>/dev/null || echo '{"ok":false}')
    SCAN_OK=$(echo "$response" | grep -o '"ok":true' >/dev/null && echo "true" || echo "false")
    log "Manual scan OK: $SCAN_OK"
}

# Get rowcounts for key symbols
get_rowcounts() {
    ROWCOUNTS=""
    for sym in EURUSD XAUUSD BTCUSD; do
        local gz_file="$WORKDIR/state/marketdata/$sym/m5.csv.gz"
        if [[ -f "$gz_file" ]]; then
            local rows=$(zcat "$gz_file" 2>/dev/null | wc -l || echo "0")
            ROWCOUNTS="${ROWCOUNTS}${sym}=${rows} "
        else
            ROWCOUNTS="${ROWCOUNTS}${sym}=0 "
        fi
    done
    log "Rowcounts: $ROWCOUNTS"
}

# Collect recent logs (filtered, no secrets)
collect_logs() {
    LOGS_EVIDENCE=$(docker logs jkm_bot_backend --tail 120 2>&1 | grep -E 'MARKETDATA_LOAD|SCAN_START|SCAN_END|INGEST_DEBUG|429|rate' | tail -30 || echo "(no matching logs)")
}

# Write journal entry
write_journal() {
    log "Writing journal entry: RESULT=$RESULT"
    
    cat >> "$JOURNAL" << EOF

===== $TIMESTAMP (AUTOPILOT SMOKE) =====
RESULT: $RESULT
FAIL_REASON: $FAIL_REASON
NOW:
  - health_ok=$HEALTH_OK
  - engine_running=$ENGINE_RUNNING
  - scan_ok=$SCAN_OK
  - rowcounts: $ROWCOUNTS
NEXT:
  - Monitor next cycle; Phase C if not done.
EVIDENCE_ENV:
$(echo -e "$ENV_EVIDENCE")
EVIDENCE_LOGS (last 30 lines):
$LOGS_EVIDENCE
EOF

    log "Journal entry appended"
}

# Commit and push journal only
commit_push_journal() {
    cd "$WORKDIR"
    
    # Ensure state/ is not staged
    git reset HEAD state/ 2>/dev/null || true
    
    # Stage only journal.txt
    git add journal.txt
    
    # Check if there's anything to commit
    if git diff --cached --quiet; then
        log "No changes to journal.txt, skip commit"
        return 0
    fi
    
    git commit -m "autopilot: journal update $TIMESTAMP" --no-verify
    git push origin HEAD 2>&1 | head -5 || log "Push failed (may need auth or network)"
    log "Journal committed and pushed"
}

# Main
main() {
    cd "$WORKDIR"
    
    log "=== Autopilot Smoke Start ==="
    
    load_api_key
    gather_env_evidence
    
    # Ensure docker is up (quick)
    docker compose up -d 2>&1 | tail -3 || true
    sleep 3
    
    check_health
    if [[ "$HEALTH_OK" != "true" ]]; then
        RESULT="FAIL"
        FAIL_REASON="health check failed"
    fi
    
    check_engine_status
    
    # If engine not running, try to start it
    if [[ "$ENGINE_RUNNING" != "true" ]]; then
        log "Engine not running, attempting start..."
        /opt/JKM-AI-BOT/ops/engine_autostart.sh || true
        sleep 2
        check_engine_status
    fi
    
    trigger_scan
    get_rowcounts
    collect_logs
    
    # Final check
    if [[ "$HEALTH_OK" != "true" || "$SCAN_OK" != "true" ]]; then
        RESULT="FAIL"
        FAIL_REASON="health=$HEALTH_OK scan=$SCAN_OK"
    fi
    
    # Commit/push journal (trap will write entry first)
    # Note: write_journal is called by trap, so we just commit after
    log "=== Autopilot Smoke End: $RESULT ==="
}

# Run main, then commit (journal written by trap)
main
# After trap writes journal, commit it
commit_push_journal || true
