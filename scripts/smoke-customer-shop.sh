#!/usr/bin/env bash
# Hit backend shop search (needs valid customer login). Usage:
#   BACKEND=http://127.0.0.1:8002 PHONE=919754656565 PASS='secret' ./scripts/smoke-customer-shop.sh
set -euo pipefail
BACKEND="${BACKEND:-http://127.0.0.1:8002}"
PHONE="${PHONE:-}"
PASS="${PASS:-}"
Q="${Q:-5050}"

echo "Backend: $BACKEND"
curl -sfS "$BACKEND/api/health" | head -c 200 || {
  echo "health failed"
  exit 1
}
echo ""

if [[ -z "$PHONE" || -z "$PASS" ]]; then
  echo "Set PHONE and PASS env vars for login test (customer credentials)."
  exit 0
fi

TOKEN="$(curl -sfS -X POST "$BACKEND/api/v1/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"phone\":\"$PHONE\",\"password\":\"$PASS\"}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))")"

if [[ -z "$TOKEN" ]]; then
  echo "login failed"
  exit 1
fi

ENC_Q="$(Q="$Q" python3 -c "import os, urllib.parse; print(urllib.parse.quote(os.environ['Q']))")"
echo "Shop search q=$Q:"
curl -sfS "$BACKEND/api/v1/shop/products/search?q=$ENC_Q" \
  -H "Authorization: Bearer $TOKEN"
echo ""
