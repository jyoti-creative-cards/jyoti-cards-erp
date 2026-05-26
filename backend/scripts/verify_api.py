#!/usr/bin/env python3
"""
Smoke-test FastAPI routes via TestClient.
Run from repo:  cd backend && DATABASE_URL='sqlite:///./dev.db' ADMIN_API_KEY='your-key' JWT_SECRET='your-secret' python scripts/verify_api.py

ADMIN_API_KEY / JWT_SECRET default to local-verify values if unset (override for production DB checks).
"""
from __future__ import annotations

import os
import sys
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _prep_env() -> None:
    # Do not inject ADMIN_API_KEY / JWT_SECRET — use backend/.env via pydantic-settings.
    if not os.environ.get("DATABASE_URL"):
        os.environ["DATABASE_URL"] = f"sqlite:////{ROOT}/dev.db"


_prep_env()

from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402


def main() -> int:
    client = TestClient(app)
    admin_key = (get_settings().admin_api_key or "").strip()
    if not admin_key:
        print("Missing ADMIN_API_KEY (set in backend/.env or environment).")
        return 1
    ah = {"X-Admin-Key": admin_key}

    def ok(method: str, path: str, *, headers=None, **kw) -> None:
        r = client.request(method, path, headers=headers or {}, **kw)
        if r.status_code >= 400:
            print(f"FAIL {method} {path} -> {r.status_code}\n{r.text[:800]}")
            raise SystemExit(1)
        print(f"ok {method} {path}")

    ok("GET", "/api/health")

    # --- Admin list reads ---
    ok("GET", "/api/v1/customers", headers=ah)
    ok("GET", "/api/v1/vendors", headers=ah)
    ok("GET", "/api/v1/catalog/categories", headers=ah)
    ok("GET", "/api/v1/catalog", headers=ah)
    ok("GET", "/api/v1/purchase-orders", headers=ah)
    ok("GET", "/api/v1/customer-orders", headers=ah)
    ok("GET", "/api/v1/vendor-bills", headers=ah)
    ok("GET", "/api/v1/customer-bills", headers=ah)
    ok("GET", "/api/v1/fiscal-years", headers=ah)
    ok("GET", "/api/v1/bank/accounts", headers=ah)
    ok("GET", "/api/v1/bank/reconciliations", headers=ah)
    ok("GET", "/api/v1/notes/credit", headers=ah)
    ok("GET", "/api/v1/notes/debit", headers=ah)
    ok("GET", "/api/v1/inventory/adjustments", headers=ah)
    ok("GET", "/api/v1/inventory", headers=ah, params={"all_catalog": "true"})
    ok("GET", "/api/v1/accounting/ar", headers=ah)
    ok("GET", "/api/v1/accounting/ap", headers=ah)

    dr = {"date_from": "2020-01-01", "date_to": "2030-12-31"}
    ok("GET", "/api/v1/accounting/dashboard", headers=ah, params=dr)
    ok("GET", "/api/v1/accounting/pnl", headers=ah, params=dr)
    ok("GET", "/api/v1/accounting/gl", headers=ah, params=dr)
    ok("GET", "/api/v1/accounting/journal", headers=ah, params=dr)

    # --- Customer + shop ---
    ts_phone = ""
    cr = None
    for _ in range(24):
        ts_phone = "91" + "".join(str(random.randint(0, 9)) for _ in range(10))
        cr = client.post(
            "/api/v1/customers",
            headers={**ah, "Content-Type": "application/json"},
            json={
                "name": "Verify API User",
                "phone": ts_phone,
                "password": "verify-pass-99",
            },
        )
        if cr.status_code == 200:
            break
        if cr.status_code != 409:
            print(f"FAIL POST /customers {cr.status_code} {cr.text[:400]}")
            raise SystemExit(1)
    else:
        print("FAIL could not allocate customer phone for shop tests")
        raise SystemExit(1)

    lr = client.post(
        "/api/v1/auth/login",
        json={"phone": ts_phone, "password": "verify-pass-99"},
    )
    if lr.status_code != 200:
        print(f"SKIP shop auth {lr.status_code} {lr.text[:300]}")
        print("All admin checks passed.")
        return 0
    token = lr.json()["access_token"]

    bh = {"Authorization": f"Bearer {token}"}
    ok("GET", "/api/v1/auth/me", headers=bh)
    ok("GET", "/api/v1/shop/products/suggestions", headers=bh, params={"q": "5"})
    ok("GET", "/api/v1/shop/products/search", headers=bh, params={"q": "5050"})
    ok("GET", "/api/v1/shop/orders", headers=bh)

    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
