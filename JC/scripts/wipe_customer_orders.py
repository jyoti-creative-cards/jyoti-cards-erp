#!/usr/bin/env python3
"""Wipe all customer orders/bills (play data) and reset bill series to start.

Restores stock reserved/sold against those orders/bills.
Keeps customers, catalog, vendor data, opening balances.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

# Load .env
env_path = ROOT / "backend" / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

from sqlalchemy import text
from app.db.session import SessionLocal
from app.models.bill_series import BillSeries
from app.models.catalog_product import CatalogProduct
from app.models.stock import StockLedger
from app.services.stock_receipt import add_stock


def _sku(db, catalog_product_id: int) -> str:
    p = db.get(CatalogProduct, catalog_product_id)
    return p.our_product_id if p else str(catalog_product_id)


def main() -> None:
    db = SessionLocal()
    try:
        # Counts before
        counts = {}
        for label, sql in [
            ("orders", "SELECT COUNT(*) FROM jc_customer_orders"),
            ("placements", "SELECT COUNT(*) FROM jc_customer_order_placements"),
            ("order_lines", "SELECT COUNT(*) FROM jc_customer_order_lines"),
            ("open_lines", "SELECT COUNT(*) FROM jc_customer_open_lines"),
            ("bills", "SELECT COUNT(*) FROM jc_customer_bills"),
            ("bill_lines", "SELECT COUNT(*) FROM jc_customer_bill_lines"),
            ("returns", "SELECT COUNT(*) FROM jc_customer_returns"),
        ]:
            counts[label] = db.execute(text(sql)).scalar() or 0
        print("Before:", counts)

        # 1) Restore stock from reserved (placements) and sold (bills)
        # Net by product: reserved deltas are negative; sold too — restore abs sum of net not yet unreserved
        reserved = (
            db.query(StockLedger)
            .filter(
                StockLedger.reference_type == "customer_placement",
                StockLedger.entry_type.in_(["reserved", "unreserved"]),
            )
            .all()
        )
        sold = (
            db.query(StockLedger)
            .filter(
                StockLedger.reference_type == "customer_bill",
                StockLedger.entry_type.in_(["sold", "restore"]),
            )
            .all()
        )
        # Net outstanding reservation / sold qty per product (negative means still out)
        net: dict[int, int] = {}
        for e in reserved + sold:
            net[e.catalog_product_id] = net.get(e.catalog_product_id, 0) + int(e.quantity_delta or 0)

        restore_n = 0
        for cid, delta in net.items():
            # delta < 0 means stock still removed — put it back
            if delta >= 0:
                continue
            qty = -delta
            add_stock(
                db,
                catalog_product_id=cid,
                our_product_id=_sku(db, cid),
                quantity=qty,
                entry_type="restore",
                reference_type="wipe",
                reference_id=0,
                party="wipe",
                notes="Wipe customer orders — restore stock",
            )
            restore_n += qty
        print(f"Stock restored units: {restore_n}")

        # 2) Clear AR that points at returns/bills (keep opening_balance)
        db.execute(text("""
            DELETE FROM jc_ar_ledger_entries
            WHERE entry_type IN ('bill', 'credit_note')
               OR bill_id IS NOT NULL
               OR return_id IS NOT NULL
        """))
        # Optional play payments: leave opening_balance; drop payment rows tied to wipe era? keep payments.

        # 3) Freight ledger tied to customer bills
        db.execute(text("""
            DELETE FROM jc_freight_ledger_entries
            WHERE customer_bill_id IS NOT NULL
        """))

        # 4) Returns (block bill delete via RESTRICT)
        db.execute(text("DELETE FROM jc_customer_return_lines"))
        db.execute(text("DELETE FROM jc_customer_returns"))

        # 5) Bills
        db.execute(text("UPDATE jc_ar_ledger_entries SET bill_id = NULL WHERE bill_id IS NOT NULL"))
        db.execute(text("UPDATE jc_freight_ledger_entries SET customer_bill_id = NULL WHERE customer_bill_id IS NOT NULL"))
        db.execute(text("DELETE FROM jc_customer_bill_lines"))
        db.execute(text("DELETE FROM jc_customer_bills"))

        # 6) Orders
        db.execute(text("DELETE FROM jc_customer_order_lines"))
        db.execute(text("DELETE FROM jc_customer_order_placements"))
        db.execute(text("DELETE FROM jc_customer_open_lines"))
        db.execute(text("DELETE FROM jc_customer_orders"))

        # 7) Reset bill series cursor so next = start_num
        series = db.query(BillSeries).all()
        for s in series:
            s.current_num = s.start_num - 1 if s.start_num > 0 else 0
            print(f"Series {s.name}: next will be {s.prefix}{s.start_num}")

        db.commit()

        after = {}
        for label, sql in [
            ("orders", "SELECT COUNT(*) FROM jc_customer_orders"),
            ("placements", "SELECT COUNT(*) FROM jc_customer_order_placements"),
            ("bills", "SELECT COUNT(*) FROM jc_customer_bills"),
            ("open_lines", "SELECT COUNT(*) FROM jc_customer_open_lines"),
            ("returns", "SELECT COUNT(*) FROM jc_customer_returns"),
        ]:
            after[label] = db.execute(text(sql)).scalar() or 0
        print("After:", after)
        print("Done.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
