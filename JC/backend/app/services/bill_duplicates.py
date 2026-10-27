"""Same party, same day: warn when a bill repeats an item or the bill total."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.customer_bill import CustomerBill, CustomerBillLine
from app.services.biz_date import ist_day_bounds_utc, today_ist


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def same_day_bill_clashes(
    db: Session,
    *,
    customer_id: int,
    lines: list[dict],
    grand_total: Decimal,
    billed_on: date | None,
) -> list[dict]:
    incoming_ids = set()
    incoming_names: dict[int, str] = {}
    for ln in lines:
        qty = int(ln.get("quantity") or ln.get("quantity_to_ship") or 0)
        if qty <= 0:
            continue
        cid = int(ln["catalog_product_id"])
        incoming_ids.add(cid)
        if ln.get("our_product_id"):
            incoming_names[cid] = str(ln["our_product_id"])
    if not incoming_ids and grand_total <= 0:
        return []
    start, end = ist_day_bounds_utc(billed_on or today_ist())
    bills = (
        db.query(CustomerBill)
        .filter(
            CustomerBill.customer_id == customer_id,
            CustomerBill.deleted_at.is_(None),
            CustomerBill.cancelled_at.is_(None),
            CustomerBill.created_at >= start,
            CustomerBill.created_at <= end,
        )
        .all()
    )
    wanted = _money(grand_total)
    clashes = []
    for bill in bills:
        existing = db.query(CustomerBillLine).filter(CustomerBillLine.bill_id == bill.id).all()
        shared = []
        for ln in existing:
            if ln.catalog_product_id in incoming_ids:
                shared.append(ln.our_product_id or incoming_names.get(ln.catalog_product_id) or str(ln.catalog_product_id))
        same_amount = _money(bill.grand_total) == wanted and wanted > 0
        if not shared and not same_amount:
            continue
        clashes.append({
            "bill_id": bill.id,
            "bill_number": bill.bill_number,
            "same_items": shared,
            "same_amount": same_amount,
            "total": format(_money(bill.grand_total), "f"),
        })
    return clashes
