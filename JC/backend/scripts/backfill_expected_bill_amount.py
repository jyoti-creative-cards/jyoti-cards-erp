"""One-time backfill: compute expected_bill_amount/expected_extra_cash for
pending_bill StockReceipts created before the vendor-billing redesign shipped.

Safe: only fills two nullable columns using the current vendor billing terms.
Does not touch stock, AP ledger, debit notes, or already-billed receipts.

Usage:
    python3 scripts/backfill_expected_bill_amount.py            # dry run
    python3 scripts/backfill_expected_bill_amount.py --execute  # write
"""
from __future__ import annotations

import sys
from decimal import Decimal

sys.path.insert(0, ".")

from app.db.session import SessionLocal
from app.models.stock import StockReceipt, StockReceiptLine
from app.models.vendor import Vendor
from app.services.vendor_billing_math import compute_bill_totals


def main() -> None:
    execute = "--execute" in sys.argv
    db = SessionLocal()
    try:
        receipts = (
            db.query(StockReceipt)
            .filter(StockReceipt.bill_status == "pending_bill", StockReceipt.expected_bill_amount.is_(None))
            .order_by(StockReceipt.id.asc())
            .all()
        )
        print(f"{len(receipts)} pending receipt(s) missing expected_bill_amount")
        updated = 0
        for r in receipts:
            vendor = db.get(Vendor, r.vendor_id)
            if not vendor:
                print(f"  receipt {r.id}: vendor {r.vendor_id} missing, skip")
                continue
            lines = db.query(StockReceiptLine).filter(StockReceiptLine.receipt_id == r.id).all()
            total_actual_value = sum((ln.buying_price * ln.quantity_received for ln in lines), Decimal("0"))
            bill_total, extra_cash = compute_bill_totals(
                total_actual_value=total_actual_value,
                billing_pct=vendor.billing_pct,
                additional_charge=vendor.additional_charge,
                discount_pct=vendor.discount_pct,
                gst_included=vendor.gst_included,
                gst_rate_pct=vendor.gst_rate_pct,
            )
            print(f"  receipt {r.id} (vendor {vendor.business_name}): expected ₹{bill_total}"
                  + (f" + ₹{extra_cash} extra cash" if vendor.billing_pct < 100 else ""))
            if execute:
                r.expected_bill_amount = bill_total
                r.expected_extra_cash = extra_cash if vendor.billing_pct < 100 else None
            updated += 1
        if execute:
            db.commit()
            print(f"Updated {updated} receipt(s).")
        else:
            print(f"[dry run] would update {updated} receipt(s). Re-run with --execute to write.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
