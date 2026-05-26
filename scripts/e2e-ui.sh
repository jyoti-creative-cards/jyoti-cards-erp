#!/usr/bin/env bash
# Full-stack UI + API smoke: backend + customer-app + admin-app, then Playwright.
# Usage from repo root:  ./scripts/e2e-ui.sh
# Requires: backend/.venv, Node, backend/.env with ADMIN_API_KEY (or export ADMIN_API_KEY).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
API_PORT="${E2E_API_PORT:-8002}"
CU_PORT="${E2E_CUSTOMER_PORT:-3000}"
AD_PORT="${E2E_ADMIN_PORT:-3010}"
API_HOST="${E2E_API_HOST:-127.0.0.1}"
API_ORIGIN="http://${API_HOST}:${API_PORT}"

export E2E_API_URL="${E2E_API_URL:-$API_ORIGIN}"
export E2E_CUSTOMER_BASE_URL="${E2E_CUSTOMER_BASE_URL:-http://${API_HOST}:${CU_PORT}}"
export E2E_ADMIN_BASE_URL="${E2E_ADMIN_BASE_URL:-http://${API_HOST}:${AD_PORT}}"

if [[ ! -f "$ROOT/backend/.venv/bin/uvicorn" ]]; then
  echo "Missing backend/.venv — create venv and pip install -r requirements.txt"
  exit 1
fi

# Optional: load ADMIN_API_KEY / JWT from backend/.env (do not print)
set -a
if [[ -f "$ROOT/backend/.env" ]]; then
  # shellcheck disable=SC1090
  source "$ROOT/backend/.env" 2>/dev/null || true
fi
set +a

# .env often points at cloud Postgres — this harness uses local sqlite unless you override.
export DATABASE_URL="${E2E_UI_DATABASE_URL:-sqlite:////${ROOT}/backend/dev.db}"
export WHATSAPP_DISABLE="${WHATSAPP_DISABLE:-1}"

cleanup() {
  for p in "${API_PORT}" "${CU_PORT}" "${AD_PORT}"; do
    lsof -ti tcp:"$p" 2>/dev/null | xargs kill -9 2>/dev/null || true
  done
}
trap cleanup EXIT

cleanup
sleep 1

echo "Starting API ${API_ORIGIN} ..."
(
  cd "$ROOT/backend"
  exec ./.venv/bin/uvicorn app.main:app --host "${API_HOST}" --port "${API_PORT}"
) &
sleep 2

for i in $(seq 1 90); do
  if curl -sf "${API_ORIGIN}/api/health" >/dev/null; then
    break
  fi
  sleep 1
  if [[ "$i" == "90" ]]; then
    echo "API did not become healthy"
    exit 1
  fi
done

export BACKEND_URL="${API_ORIGIN}"
export NEXT_PUBLIC_API_URL="${API_ORIGIN}"

echo "Starting customer-app :${CU_PORT} ..."
(
  cd "$ROOT/web/customer-app"
  test -f .env.local || cp .env.local.example .env.local
  exec npm run dev
) &

echo "Starting admin-app :${AD_PORT} ..."
(
  cd "$ROOT/web/admin-app"
  test -f .env.local || cp .env.local.example .env.local
  exec npm run dev
) &

for i in $(seq 1 120); do
  if curl -sfI "http://${API_HOST}:${CU_PORT}" >/dev/null 2>&1 && curl -sfI "http://${API_HOST}:${AD_PORT}" >/dev/null 2>&1; then
    break
  fi
  sleep 1
  if [[ "$i" == "120" ]]; then
    echo "Next dev servers not responding on ${CU_PORT}/${AD_PORT}"
    exit 1
  fi
done

echo "Installing Playwright deps (e2e/) ..."
cd "$ROOT/e2e"
if [[ ! -d node_modules ]]; then
  npm install
fi
npx playwright install chromium

echo "Running Playwright ..."
npx playwright test

echo "E2E UI passed."
