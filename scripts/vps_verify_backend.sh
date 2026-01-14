#!/usr/bin/env bash
set -euo pipefail

# Run this on the VPS from the repo root.
# Verifies health + a couple of dashboard-critical endpoints.

BASE_URL_DEFAULT="http://127.0.0.1:8000"
BASE_URL="${BASE_URL:-$BASE_URL_DEFAULT}"

if [[ ! -f "docker-compose.yml" ]]; then
  echo "ERROR: docker-compose.yml not found. Run from repo root." >&2
  exit 1
fi

INTERNAL_API_KEY_VALUE="${INTERNAL_API_KEY:-}"
if [[ -z "${INTERNAL_API_KEY_VALUE}" && -f .env ]]; then
  INTERNAL_API_KEY_VALUE="$(grep -E '^INTERNAL_API_KEY=' .env | tail -n 1 | cut -d '=' -f 2- | tr -d '\r')"
fi

echo "==> BASE_URL=${BASE_URL}"

echo "==> /health"
curl -fsS "${BASE_URL}/health" | head -c 2000
printf "\n\n"

echo "==> /api/symbols"
curl -fsS "${BASE_URL}/api/symbols" | head -c 2000
printf "\n\n"

echo "==> /api/metrics"
curl -fsS "${BASE_URL}/api/metrics" | head -c 2000
printf "\n\n"

if [[ -n "${INTERNAL_API_KEY_VALUE}" ]]; then
  echo "==> internal: /api/admin/resolve-user (requires x-internal-api-key)"
  curl -fsS -H "x-internal-api-key: ${INTERNAL_API_KEY_VALUE}" "${BASE_URL}/api/admin/resolve-user?email=Kamnasjey@gmail.com" | head -c 2000
  printf "\n\n"
else
  echo "SKIP: INTERNAL_API_KEY not found (set INTERNAL_API_KEY or put it in .env)"
fi
