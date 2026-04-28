"""End-to-end: PO → receive → vendor bill (GL) → customer order → sale (GL) → pay vendor + collect.

Requires ``DATABASE_URL`` (PostgreSQL). Use a disposable database.

Run:  cd Dashboard && DATABASE_URL=... python3 e2e_gl_test.py
"""
from __future__ import annotations

import os
import sys

_D = os.path.dirname(os.path.abspath(__file__))
if not os.environ.get("DATABASE_URL", "").strip():
    print("Set DATABASE_URL (PostgreSQL).", file=sys.stderr)
    raise SystemExit(2)

import db
from gl import (
    AC_CASH,
    AC_EQUITY,
    list_gl_accounts,
    pnl_to_date,
    post_journal,
    trial_balance,
)


def _seed_cash() -> None:
    from datetime import date

    post_journal(
        date.today().isoformat(),
        "Opening: cash and equity (for AP/AR payments test)",
        "opening",
        None,
        [
            (AC_CASH, 5_000_000.0, 0.0),
            (AC_EQUITY, 0.0, 5_000_000.0),
        ],
    )


def main() -> int:
    db.init_db()
    _seed_cash()
    assert len(list_gl_accounts()) >= 7

    vid = db.insert_vendor(
        "E2E Vendor",
        "E2E Co",
        "9000000001",
        None,
        7,
        100,
        "",
        "Our Legal",
        "Addr",
        "City 400001",
        "GST-OUR",
        "9",
        "a@a.com",
    )
    pid = db.insert_vendor_product(
        vid, "VP-1", "SKU-E2E", "E2E Widget", "Cat", 50.0, None, None
    )
    cid = db.insert_customer("E2E Customer", "Co", "8000000002", None, "Mumbai", "p")
    poid = db.insert_purchase_order(
        vid,
        pid,
        10.0,
        100.0,
        7,
        100,
        None,
        None,
        "",
        None,
        None,
    )
    db.insert_stock_receipt(
        int(pid), int(poid), 10.0, "S1", "GRN-1", 200.0, "e2e"
    )
    # Vendor bill: Dr Inventory / Cr AP
    bid = db.insert_po_billing_for_po(poid)
    b = db.get_po_billing(bid)
    assert b is not None and b.gl_journal_id, "P.O. bill should post to GL"
    # Customer order (requires stock and selling price on last receipt)
    coid = db.insert_customer_order(cid, pid, 4.0)
    db.update_customer_order(
        coid,
        status="shipped",
        shipment_id="S2",
        transport_name=None,
        transport_number=None,
        notes="",
    )
    cob = db.insert_customer_order_billing(coid)
    bc = db.get_customer_order_billing(cob)
    assert bc and bc.gl_journal_id, "Sale should post to GL"

    # Pay vendor in full, collect from customer in full
    db.insert_ap_payment(bid, float(b.raw_line_total), "NEFT", "E2E AP")
    db.insert_ar_payment(cob, float(bc.raw_line_total), "UPI", "E2E AR")

    d = db.line_total(4, bc.unit_cost, bc.billing_pct)
    assert abs(d - float(bc.raw_line_total)) < 0.01

    tb = trial_balance()
    print("Trial (balance = Dr−Cr, asset convention):")
    for r in tb:
        bal = float(r.get("balance_debit") or 0)
        print(" ", r["code"], r["name"], f"{bal:,.2f}")

    p = pnl_to_date("2099-12-31")
    print("P&L to date:", p)

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
    assert abs(tdr - tcr) < 0.1, f"Unbalanced book Dr={tdr} Cr={tcr}"
    print("E2E OK: debits = credits, flows completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
