#!/usr/bin/env bash
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "Starting JC backend on :8003..."
cd "$ROOT/backend"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt -q
fi
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8003 --reload &
BACK_PID=$!

echo "Starting admin UI on :3011..."
cd "$ROOT/web/admin"
python3 -m http.server 3011 &
ADMIN_PID=$!

echo "Starting customer portal on :3012..."
cd "$ROOT/web/portal"
python3 -m http.server 3012 &
PORTAL_PID=$!

echo ""
echo "JC is running:"
echo "  API:    http://127.0.0.1:8003/health"
echo "  Admin:  http://127.0.0.1:3011  (API key login — NOT customer login)"
echo "  Portal: http://127.0.0.1:3012  (customer mobile + password)"
echo "  Admin key: see JC/backend/.env"
echo ""
echo "Tip: run ./ensure-running.sh anytime to (re)start backend + admin in background."
echo "Press Ctrl+C to stop."

trap "kill $BACK_PID $ADMIN_PID $PORTAL_PID 2>/dev/null" EXIT
wait
