#!/usr/bin/env python3
"""
End-to-end API walk: vendor → catalog → manual stock → PO → full GRN →
customer → login → shop order → admin status (confirmed → shipped) → stock adjustment.

Run from repo:
  cd backend && DATABASE_URL='sqlite:///./dev.db' python scripts/e2e_api.py

Uses ADMIN_API_KEY / JWT_SECRET from backend/.env. Sets WHATSAPP_DISABLE=1 if unset (skip Meta sends).
"""
from __future__ import annotations

import json
import os
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _prep() -> None:
    if not os.environ.get("DATABASE_URL"):
        os.environ["DATABASE_URL"] = f"sqlite:////{ROOT}/dev.db"
    os.environ.setdefault("WHATSAPP_DISABLE", "1")


_prep()

from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402


def _rand_phone() -> str:
    return "91" + "".join(str(random.randint(0, 9)) for _ in range(10))


def _suffix() -> str:
    return str(int(time.time()))[-8:]


def main() -> int:
    client = TestClient(app)
    admin_key = (get_settings().admin_api_key or "").strip()
    if not admin_key:
        print("Missing ADMIN_API_KEY in backend/.env")
        return 1
    ah = {"X-Admin-Key": admin_key}
    jh = {**ah, "Content-Type": "application/json"}
    sfx = _suffix()

    def req(method: str, path: str, *, expect: int | None = None, headers=None, **kw):
        r = client.request(method, path, headers=headers or {}, **kw)
        if expect is not None:
            if r.status_code != expect:
                print(f"FAIL {method} {path} -> {r.status_code}\n{r.text[:1200]}")
                raise SystemExit(1)
        elif r.status_code >= 400:
            print(f"FAIL {method} {path} -> {r.status_code}\n{r.text[:1200]}")
            raise SystemExit(1)
        return r

    # --- Vendor ---
    v_phone = _rand_phone()
    rv = req(
        "POST",
        "/api/v1/vendors",
        headers=jh,
        json={
            "person_name": f"E2E Vendor {sfx}",
            "phone": v_phone,
            "company_name": "E2E Co",
            "billing_percentage": 100,
        },
    )
    vendor_id = rv.json()["id"]
    print(f"ok vendor id={vendor_id}")

    # --- Catalog ---
    sku = f"E2E{sfx}"
    rc = req(
        "POST",
        "/api/v1/catalog",
        headers=jh,
        json={
            "our_product_id": sku,
            "vendor_id": vendor_id,
            "name": f"E2E Product {sfx}",
            "vendor_product_id": f"VP{sfx}",
            "category": "e2e",
            "buying_price": 10.0,
            "selling_price": 25.5,
        },
    )
    cat_id = rc.json()["id"]
    print(f"ok catalog id={cat_id} sku={sku}")

    # --- Manual stock (customer portal orders require qty > 0) ---
    req(
        "POST",
        "/api/v1/inventory/manual",
        headers=jh,
        json={"catalog_product_id": cat_id, "quantity": 50},
    )
    print("ok inventory/manual +50")

    # --- Customer + shop order ---
    c_phone = _rand_phone()
    req(
        "POST",
        "/api/v1/customers",
        headers=jh,
        json={"name": f"E2E Customer {sfx}", "phone": c_phone, "password": "e2e-pass-99"},
    )
    lr = req(
        "POST",
        "/api/v1/auth/login",
        json={"phone": c_phone, "password": "e2e-pass-99"},
    )
    token = lr.json()["access_token"]
    bh = {"Authorization": f"Bearer {token}"}

    so = req(
        "POST",
        "/api/v1/shop/orders",
        headers={**bh, "Content-Type": "application/json"},
        json={"lines": [{"catalog_product_id": cat_id, "quantity": 2}]},
    )
    order_id = so.json()["id"]
    assert so.json()["status"] == "booked"
    print(f"ok shop order id={order_id} booked")

    req("GET", f"/api/v1/shop/orders/{order_id}", headers=bh)
    print("ok shop order get")

    # --- Admin: confirm → shipped ---
    req(
        "PATCH",
        f"/api/v1/customer-orders/{order_id}",
        headers=jh,
        json={"status": "confirmed"},
    )
    print("ok admin order confirmed")

    req(
        "PATCH",
        f"/api/v1/customer-orders/{order_id}",
        headers=jh,
        json={
            "status": "shipped",
            "shipment_receipt": f"GRN-E2E-{sfx}",
            "shipment_contact": "919888888888",
            "shipment_notes": "e2e ship",
        },
    )
    print("ok admin order shipped")

    ro = req("GET", f"/api/v1/customer-orders/{order_id}", headers=ah)
    assert ro.json()["status"] == "shipped"
    print("ok admin order get shipped")

    # --- Purchase order ---
    rp = req(
        "POST",
        "/api/v1/purchase-orders",
        headers=jh,
        json={"vendor_id": vendor_id, "items": [{"catalog_product_id": cat_id, "quantity": 5}]},
    )
    po_id = rp.json()["id"]
    print(f"ok PO id={po_id}")

    # --- GRN from PO (full receive — avoids partial+S3 file requirement) ---
    req(
        "POST",
        "/api/v1/inventory/receipts/from-po",
        headers=ah,
        data={
            "purchase_order_id": str(po_id),
            "is_partial": "false",
            "receipt_number": f"RCPT-{sfx}",
            "contact_number": "919777777777",
            "lines": json.dumps([{"catalog_product_id": cat_id, "quantity": 5}]),
        },
    )
    print("ok inventory/receipts/from-po full receive")

    # --- Stock adjustment ---
    ra = req(
        "POST",
        "/api/v1/inventory/adjustments",
        headers=jh,
        json={"catalog_product_id": cat_id, "quantity_delta": -1, "note": "e2e adj"},
    )
    adj_id = ra.json()["id"]
    print(f"ok adjustment id={adj_id}")

    # --- List reads (sanity) ---
    req("GET", "/api/v1/purchase-orders", headers=ah)
    req("GET", "/api/v1/inventory/adjustments", headers=ah, params={"catalog_product_id": str(cat_id)})
    inv = req("GET", "/api/v1/inventory", headers=ah, params={"all_catalog": "true", "q": sku})
    rows = inv.json()
    assert isinstance(rows, list) and any(r.get("catalog_product_id") == cat_id for r in rows)
    print("ok inventory list contains sku")

    print("E2E API flow passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
