#!/usr/bin/env python3
"""GET smoke checks against a running API (default http://127.0.0.1:8000)."""
from __future__ import annotations

import json
import os
import sys
import urllib.request

BASE = (os.environ.get("ERP_API_BASE") or "http://127.0.0.1:8000").rstrip("/")

PATHS = [
    "/api/health",
    "/api/v1/integrations/whatsapp/status",
    "/api/v1/integrations/pdf/info",
    "/api/v1/dashboard/stats",
    "/api/v1/customers",
    "/api/v1/vendors",
    "/api/v1/accounting/gl/accounts",
    "/api/v1/accounting/gl/trial-balance",
    "/api/v1/accounting/gl/pnl?through=2026-04-21",
    "/api/v1/accounting/ar/ledger",
    "/api/v1/accounting/ap/ledger",
]


def main() -> None:
    ok = 0
    for path in PATHS:
        url = f"{BASE}{path}"
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                body = r.read().decode()
                code = r.status
            data = json.loads(body)
            preview = json.dumps(data if not isinstance(data, list) else data[:1], default=str)
            if len(preview) > 240:
                preview = preview[:240] + "..."
            print(f"{code}  {path}")
            print(f"     {preview}")
            ok += 1
        except Exception as e:
            print(f"FAIL {path}: {e}", file=sys.stderr)
    print(f"\n{ok}/{len(PATHS)} OK — base {BASE}")


if __name__ == "__main__":
    main()
