#!/usr/bin/env bash
ROOT="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$ROOT/.logs" "$ROOT/.pids"
cd "$ROOT/web/admin"
exec /usr/bin/python3 -u -m http.server 3011 --bind 127.0.0.1
