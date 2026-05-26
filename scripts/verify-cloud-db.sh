#!/usr/bin/env bash
# Run API smoke + E2E using DATABASE_URL from backend/.env (e.g. Supabase Postgres).
# From repo root:  ./scripts/verify-cloud-db.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [[ ! -f "$ROOT/backend/.env" ]]; then
  echo "Missing backend/.env — copy backend/.env.example and set DATABASE_URL."
  exit 1
fi

(
  cd "$ROOT/backend"
  set -a
  # shellcheck disable=SC1091
  source ./.env
  set +a
  export WHATSAPP_DISABLE="${WHATSAPP_DISABLE:-1}"
  echo "=== verify_api (cloud DB) ==="
  ./.venv/bin/python scripts/verify_api.py
  echo "=== e2e_api (cloud DB) ==="
  ./.venv/bin/python scripts/e2e_api.py
)

echo "=== cloud DB checks passed ==="
