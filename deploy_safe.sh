#!/usr/bin/env bash
set -euo pipefail

cd /opt/JKM-AI-BOT

echo "== Load .env into shell (no printing) =="
if [ ! -f ./.env ]; then
  echo "ERROR: .env not found at /opt/JKM-AI-BOT/.env"
  exit 1
fi
set -a
source ./.env
set +a

echo "== Host env presence (safe check) =="
if [ -n "${MASSIVE_API_KEY-}" ]; then
  echo "HOST KEY: PRESENT"
else
  echo "HOST KEY: MISSING"
fi

echo "== Ensure bind-mount dirs exist =="
mkdir -p state logs

echo "== Recreate containers =="
docker compose down --remove-orphans
docker compose up -d --build

echo "== Status =="
docker compose ps

echo "== Container env presence (safe check) =="
docker compose exec -T backend sh -lc 'if [ -n "${MASSIVE_API_KEY:-}" ]; then echo "CONTAINER KEY: PRESENT"; else echo "CONTAINER KEY: MISSING"; fi'

echo "== Health (retry up to 30s) =="
health_json=""
for i in $(seq 1 30); do
  if health_json=$(curl -s http://localhost:8000/health); then
    if echo "$health_json" | grep -q '"ok"'; then
      break
    fi
  fi
  sleep 1
done

echo "$health_json" | python3 -m json.tool || echo "$health_json"

HEALTH_JSON="$health_json" python3 - <<'PY'
import json, os, sys

raw = os.environ.get("HEALTH_JSON")
if not raw:
    sys.exit("ERROR: missing HEALTH_JSON")

try:
    data = json.loads(raw)
except Exception as e:
    sys.exit(f"ERROR: /health not valid JSON: {e}")

if data.get("ok") is not True:
    sys.exit("ERROR: /health ok is not true")
if data.get("provider_configured") is not True:
    sys.exit("ERROR: /health provider_configured is not true (check MASSIVE_API_KEY)")

print("HEALTH CHECK: OK")
PY

echo "== Signals =="
signals_json=$(curl -s "http://localhost:8000/api/signals?limit=3")
echo "$signals_json" | python3 -m json.tool || echo "$signals_json"

SIGNALS_JSON="$signals_json" python3 - <<'PY'
import json, os, sys

raw = os.environ.get("SIGNALS_JSON")
if raw is None:
  sys.exit("ERROR: missing SIGNALS_JSON")

try:
  data = json.loads(raw)
except Exception as e:
  sys.exit(f"ERROR: /api/signals not valid JSON: {e}")

if not isinstance(data, list):
  sys.exit("ERROR: /api/signals did not return a JSON list")
if len(data) != 0:
  sys.exit("ERROR: /api/signals is not empty (expected [])")

print("SIGNALS CHECK: OK")
PY

echo "== State write + mount verification =="
host_ts="ok $(date)"
echo "$host_ts" > state/host_write_test.txt

docker compose exec -T backend sh -lc '
  set -e
  echo "ok $(date)" > /app/state/container_write_test.txt
  if [ -f /app/state/host_write_test.txt ]; then
    echo "CONTAINER SEES HOST FILE: OK"
  else
    echo "CONTAINER SEES HOST FILE: FAIL"; exit 1
  fi
  ls -la /app/state | tail -n 10
'

if [ -f state/container_write_test.txt ]; then
  echo "HOST SEES CONTAINER FILE: OK"
else
  echo "HOST SEES CONTAINER FILE: FAIL"; exit 1
fi

echo "DONE"
