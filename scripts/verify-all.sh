#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DB="${DATABASE_URL:-sqlite:////${ROOT}/backend/dev.db}"

echo "=== API smoke (TestClient) DATABASE_URL=$DB ==="
(
  cd "$ROOT/backend"
  export DATABASE_URL="$DB"
  ./.venv/bin/python scripts/verify_api.py
)

echo "=== API E2E (vendor → catalog → stock → orders → PO → GRN) ==="
(
  cd "$ROOT/backend"
  export DATABASE_URL="$DB"
  ./.venv/bin/python scripts/e2e_api.py
)

echo "=== customer-app build ==="
(cd "$ROOT/web/customer-app" && npm run build)

echo "=== admin-app build ==="
(cd "$ROOT/web/admin-app" && npm run build)

if [[ "${VERIFY_UI:-}" == "1" ]]; then
  echo "=== Playwright UI (VERIFY_UI=1) ==="
  "$ROOT/scripts/e2e-ui.sh"
fi

echo "=== done ==="
