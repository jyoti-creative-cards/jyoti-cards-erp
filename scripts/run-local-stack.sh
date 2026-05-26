#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Override any of these when starting the stack:
#   LOCAL_STACK_API_HOST LOCAL_STACK_API_PORT LOCAL_STACK_CUSTOMER_PORT LOCAL_STACK_ADMIN_PORT
# Supabase / cloud Postgres from backend/.env (no sqlite override):
#   LOCAL_STACK_SKIP_SQLITE=1 ./scripts/run-local-stack.sh
# Smoke that DB: ./scripts/verify-cloud-db.sh
API_HOST="${LOCAL_STACK_API_HOST:-127.0.0.1}"
API_PORT="${LOCAL_STACK_API_PORT:-8002}"
CUSTOMER_PORT="${LOCAL_STACK_CUSTOMER_PORT:-3000}"
ADMIN_PORT="${LOCAL_STACK_ADMIN_PORT:-3010}"
BACKEND_ORIGIN="http://${API_HOST}:${API_PORT}"

echo "Stopping anything on ports ${API_PORT}, ${CUSTOMER_PORT}, ${ADMIN_PORT} ..."
for p in "${API_PORT}" "${CUSTOMER_PORT}" "${ADMIN_PORT}"; do
  lsof -ti tcp:"$p" 2>/dev/null | xargs kill -9 2>/dev/null || true
done
sleep 1

echo "Starting backend ${BACKEND_ORIGIN} ..."
(
  cd "$ROOT/backend"
  . .venv/bin/activate
  # Env overrides backend/.env — one sqlite file for admin + customer portal on this machine.
  if [[ "${LOCAL_STACK_SKIP_SQLITE:-}" != "1" ]]; then
    export DATABASE_URL="sqlite:////${ROOT}/backend/dev.db"
  fi
  exec uvicorn app.main:app --host "${API_HOST}" --port "${API_PORT}"
) &
sleep 1

command -v npm >/dev/null || { echo "npm not found — install Node.js, then: cd web/customer-app && npm i && npm run dev"; wait; exit 1; }

# Next rewrites read BACKEND_URL at dev server start; shell export overrides stale .env.local.
export BACKEND_URL="${BACKEND_ORIGIN}"
export NEXT_PUBLIC_API_URL="${BACKEND_ORIGIN}"

echo "Starting customer UI http://${API_HOST}:${CUSTOMER_PORT} ..."
(
  cd "$ROOT/web/customer-app"
  test -f .env.local || cp .env.local.example .env.local
  npm run dev
) &

echo "Starting admin UI http://${API_HOST}:${ADMIN_PORT} ..."
(
  cd "$ROOT/web/admin-app"
  test -f .env.local || cp .env.local.example .env.local
  npm run dev
) &

echo ""
echo "API:        ${BACKEND_ORIGIN}/docs"
echo "Customer:   http://${API_HOST}:${CUSTOMER_PORT}"
echo "Admin:      http://${API_HOST}:${ADMIN_PORT}"
if [[ "${LOCAL_STACK_SKIP_SQLITE:-}" == "1" ]]; then
  echo "Database:   from backend/.env (not forcing sqlite)"
else
  echo "Database:   sqlite ${ROOT}/backend/dev.db (admin + portal share this file)"
fi
echo "Ctrl+C stops this shell (children may keep running — kill ports if needed)."
wait
