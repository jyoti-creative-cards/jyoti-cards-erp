#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ -x "$ROOT/.tools/node/bin/npm" ]; then
  export PATH="$ROOT/.tools/node/bin:$PATH"
fi
command -v npm >/dev/null || {
  echo "Run: bash $ROOT/scripts/install-node.sh  (or install Node from nodejs.org)"
  exit 1
}

echo "Installing deps..."
(cd "$ROOT/web/customer-app" && npm install)
(cd "$ROOT/web/admin-app" && npm install)

for app in customer-app admin-app; do
  test -f "$ROOT/web/$app/.env.local" || cp "$ROOT/web/$app/.env.local.example" "$ROOT/web/$app/.env.local"
done

export BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:8002}"
export NEXT_PUBLIC_API_URL="${NEXT_PUBLIC_API_URL:-$BACKEND_URL}"

echo "Starting customer UI http://127.0.0.1:3000 (BACKEND_URL=${BACKEND_URL}) ..."
(cd "$ROOT/web/customer-app" && npm run dev) &
PID3000=$!

echo "Starting admin UI http://127.0.0.1:3010 ..."
(cd "$ROOT/web/admin-app" && npm run dev) &
PID3010=$!

echo "PIDs: customer=$PID3000 admin=$PID3010"
echo "Open http://127.0.0.1:3000 and http://127.0.0.1:3010 — Ctrl+C stops both."
trap 'kill $PID3000 $PID3010 2>/dev/null; exit 0' INT TERM
wait
