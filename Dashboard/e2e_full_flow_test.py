"""Full ERP simulation: vendor → product → PO → 2 receipts → stock up → portal-visible →
customer order (stock down) → shipped → both bills → AR/AP cash → GL + P&L balanced.

Requires ``DATABASE_URL`` (Postgres). Use a disposable database; re-runs append data.

Run:  cd Dashboard && DATABASE_URL=... python3 e2e_full_flow_test.py
"""
from __future__ import annotations

import os
import sys
from datetime import date

_D = os.path.dirname(os.path.abspath(__file__))
if not os.environ.get("DATABASE_URL", "").strip():
    print("Set DATABASE_URL (PostgreSQL).", file=sys.stderr)
    raise SystemExit(2)

import db  # noqa: E402
from bill_pdf import build_billing_pdfs_for_co_record, build_billing_pdfs_for_record
from gl import (
    AC_CASH,
    AC_EQUITY,
    list_gl_accounts,
    pnl_to_date,
    post_journal,
    trial_balance,
)


def _seed_cash() -> None:
    post_journal(
        date.today().isoformat(),
        "Opening: cash and equity (E2E full flow)",
        "opening",
        None,
        [
            (AC_CASH, 2_000_000.0, 0.0),
            (AC_EQUITY, 0.0, 2_000_000.0),
        ],
    )


def _assert_gl_balanced() -> None:
    c = db._connect()
    try:
        tdr = float(
            c.execute(
                "SELECT COALESCE(SUM(debit),0) AS s FROM gl_journal_lines"
            ).fetchone()["s"]
        )
        tcr = float(
            c.execute(
                "SELECT COALESCE(SUM(credit),0) AS s FROM gl_journal_lines"
            ).fetchone()["s"]
        )
    finally:
        c.close()
    assert abs(tdr - tcr) < 0.1, f"Unbalanced: Dr={tdr} Cr={tcr}"


def main() -> int:
    db.init_db()
    _seed_cash()
    assert len(list_gl_accounts()) >= 7

    # --- Master data ---
    vid = db.insert_vendor(
        "Sim Vendor",
        "Sim Co",
        "9100000001",
        None,
        30,
        100,
        "E2E vendor",
        "Our Legal Name",
        "1 Trade St",
        "Mumbai 400001",
        "ID-OUR-1",
        "22",
        "erp@example.com",
    )
    pid = db.insert_vendor_product(
        vid, "V-SKU-99", "E2E-PORTAL-SKU", "Portal Widget", "Demo", 50.0, None, None
    )
    cid = db.insert_customer("Sim Customer", "BuyCo", "9200000002", None, "Pune", "c@x.com")

    # No receipts yet → not browsable, no stock
    assert db.product_receipts_total(pid) == 0.0
    assert db.product_on_hand(pid) == 0.0
    assert not db.search_instock_products_prefix("E2E", 10), "no product in portal before receipt"

    # --- PO + two shipments (inventory up) ---
    poid = db.insert_purchase_order(
        vid,
        pid,
        10.0,
        100.0,  # unit cost
        30,
        100,  # bill 100% of line
        None,
        None,
        "PO for E2E",
        "BlueDart",
        "TRK-1",
    )
    db.insert_stock_receipt(
        int(pid), int(poid), 4.0, "SHIP-01", "GRN-01", 200.0, "first lot"
    )
    assert abs(db.product_receipts_total(pid) - 4.0) < 0.001
    assert abs(db.product_on_hand(pid) - 4.0) < 0.001

    db.insert_stock_receipt(
        int(pid), int(poid), 6.0, "SHIP-02", "GRN-02", 200.0, "second lot"
    )
    assert abs(db.product_receipts_total(pid) - 10.0) < 0.001
    assert abs(db.product_on_hand(pid) - 10.0) < 0.001

    hits = db.search_instock_products_prefix("E2E", 20)
    assert any(h["our_product_id"] == "E2E-PORTAL-SKU" for h in hits), "customer can browse SKU"

    ag0 = {r["our_product_id"]: r for r in db.list_inventory_aggregated()}
    assert "E2E-PORTAL-SKU" in ag0
    assert abs(ag0["E2E-PORTAL-SKU"]["receipts_qty"] - 10.0) < 0.01
    assert ag0["E2E-PORTAL-SKU"]["committed_qty"] == 0.0
    assert abs(ag0["E2E-PORTAL-SKU"]["on_hand"] - 10.0) < 0.01

    # --- Customer order (reserves stock: available down) ---
    coid = db.insert_customer_order(cid, pid, 3.0)
    assert abs(db.product_on_hand(pid) - 7.0) < 0.001, "3 units reserved"
    ords = [o for o in db.list_customer_orders() if o.id == coid]
    assert len(ords) == 1
    det = [x for x in db.list_portal_order_lines_detail() if x.get("order_id") == coid]
    assert len(det) == 1 and det[0]["status"] == "placed"

    db.update_customer_order(
        coid, status="in_progress", shipment_id="PACK-1", transport_name="Road", transport_number="V-9"
    )
    # App uses "shipped" (no separate "delivered" status)
    db.update_customer_order(
        coid, status="shipped", shipment_id="OUT-1", transport_name="Road", transport_number="V-9"
    )
    o = db.get_customer_order(coid)
    assert o and (o.status or "").lower() == "shipped", "set to shipped (delivered)"

    # --- Purchase billing (vendor) + sales billing (after shipped) ---
    bid = db.insert_po_billing_for_po(poid)
    pob = db.get_po_billing(bid)
    assert pob and getattr(pob, "gl_journal_id", None), "PO bill posts to GL"
    e_po = float(pob.raw_line_total)
    exp_po = db.line_total(float(pob.quantity), float(pob.unit_cost), pob.billing_pct)
    assert abs(e_po - exp_po) < 0.02, f"PO bill {e_po} vs {exp_po}"

    po_pdf, _ = build_billing_pdfs_for_record(pob)
    assert len(po_pdf) > 100, "vendor bill PDF"

    cob_id = db.insert_customer_order_billing(coid)
    cob = db.get_customer_order_billing(cob_id)
    assert cob and getattr(cob, "gl_journal_id", None), "sales posts to GL"
    e_co = float(cob.raw_line_total)
    exp_co = db.line_total(float(cob.quantity), float(cob.unit_cost), cob.billing_pct)
    assert abs(e_co - exp_co) < 0.02, f"CO bill {e_co} vs {exp_co}"

    co_pdf, _ = build_billing_pdfs_for_co_record(cob)
    assert len(co_pdf) > 100, "customer bill PDF"

    _assert_gl_balanced()

    # --- Payments: record mode + note (e.g. cash, txn id) ---
    ap_id = db.insert_ap_payment(bid, e_po, "CASH", "TID-V-998877")
    ar_id = db.insert_ar_payment(cob_id, e_co, "CASH", "TID-AR-112233")
    assert ap_id and ar_id

    assert abs(db.get_ap_open_balance(bid)) < 0.02, "AP cleared"
    assert abs(db.get_ar_open_balance(cob_id)) < 0.02, "AR cleared"

    _assert_gl_balanced()
    p = pnl_to_date("2099-12-31")
    assert p["revenue"] > 0 and p.get("net_income") is not None
    print("P&L:", p)
    print("Trial balance (Dr−Cr):")
    for r in trial_balance():
        b = float(r.get("balance_debit") or 0)
        print(" ", r["code"], r["name"], f"{b:,.2f}")

    print("DB:", db.get_db_path())
    print("E2E full flow OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
