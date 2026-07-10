#!/usr/bin/env bash
# Start JC backend (:8003) and admin UI (:3011) if not already up.
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND_PORT=8003
ADMIN_PORT=3011
mkdir -p "$ROOT/.logs" "$ROOT/.pids"

ping_api() { curl -sf --max-time 2 "http://127.0.0.1:${BACKEND_PORT}/api/v1/ping" >/dev/null 2>&1; }
ping_admin() { curl -sf --max-time 2 "http://127.0.0.1:${ADMIN_PORT}/" >/dev/null 2>&1; }

if ! ping_api; then
  cd "$ROOT/backend"
  if [ ! -d .venv ]; then
    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt -q
  fi
  nohup .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$BACKEND_PORT" \
    >> "$ROOT/.logs/backend.log" 2>&1 &
  echo $! > "$ROOT/.pids/backend.pid"
  for i in $(seq 1 30); do ping_api && break; sleep 0.5; done
  ping_api || { echo "Backend failed — see $ROOT/.logs/backend.log"; tail -15 "$ROOT/.logs/backend.log"; exit 1; }
  echo "Backend started on :${BACKEND_PORT}"
else
  echo "Backend already on :${BACKEND_PORT}"
fi

if ! ping_admin; then
  cd "$ROOT/web/admin"
  nohup python3 -m http.server "$ADMIN_PORT" >> "$ROOT/.logs/admin.log" 2>&1 &
  echo $! > "$ROOT/.pids/admin.pid"
  echo "Admin UI started on :${ADMIN_PORT}"
else
  echo "Admin UI already on :${ADMIN_PORT}"
fi

echo ""
echo "  API:   http://127.0.0.1:${BACKEND_PORT}/api/v1"
echo "  Admin: http://127.0.0.1:${ADMIN_PORT}"
