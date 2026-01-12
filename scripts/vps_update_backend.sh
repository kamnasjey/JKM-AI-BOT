#!/usr/bin/env bash
set -euo pipefail

# Run this on the VPS from the repo root.
# It updates code to the latest backend branch, then rebuilds + restarts containers.

BRANCH_DEFAULT="feature/billing-plans"
BRANCH="${1:-$BRANCH_DEFAULT}"

if [[ ! -f "docker-compose.yml" ]]; then
  echo "ERROR: docker-compose.yml not found. Run from repo root." >&2
  exit 1
fi

echo "==> Updating git branch: ${BRANCH}" 

git fetch origin "${BRANCH}" --prune

git rev-parse --verify "${BRANCH}" >/dev/null 2>&1 || true

git checkout "${BRANCH}"

git pull --ff-only origin "${BRANCH}"

echo "==> Checking .env owner/admin settings (optional)"
if [[ -f ".env" ]]; then
  grep -q '^OWNER_ADMIN_USER_ID=' .env && echo "OK: OWNER_ADMIN_USER_ID is set in .env" || echo "WARN: OWNER_ADMIN_USER_ID not found in .env"
  grep -q '^INTERNAL_API_KEY=' .env && echo "OK: INTERNAL_API_KEY is set in .env" || echo "WARN: INTERNAL_API_KEY not found in .env (internal endpoints will fail)"
else
  echo "WARN: .env file not found. docker-compose uses env_file: .env" 
fi

echo "==> Rebuilding + restarting backend"
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  docker compose up -d --build backend
  docker compose ps
else
  echo "ERROR: docker compose v2 not found. Install Docker Compose plugin." >&2
  exit 2
fi

echo "==> Tail logs (Ctrl+C to stop)"
docker compose logs -n 120 -f backend
