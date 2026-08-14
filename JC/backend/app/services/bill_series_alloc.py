from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.bill_series import BillSeries
from app.models.customer_bill import CustomerBill


def bill_series_preview(db: Session, series_id: int) -> dict:
    row = db.get(BillSeries, series_id)
    if not row or not row.is_active:
        raise HTTPException(404, "bill series not found")
    next_num = row.current_num + 1 if row.current_num >= row.start_num else row.start_num
    remaining = max(0, row.end_num - next_num + 1)
    if next_num > row.end_num:
        return {
            "series_id": row.id,
            "name": row.name,
            "next_bill_number": None,
            "remaining": 0,
            "exhausted": True,
        }
    return {
        "series_id": row.id,
        "name": row.name,
        "next_bill_number": f"{row.prefix}{next_num}",
        "remaining": remaining,
        "exhausted": False,
    }


def allocate_bill_number(db: Session, series_id: int) -> str:
    """Always advance the series cursor. Cancelled bills keep their numbers (no reuse)."""
    row = (
        db.query(BillSeries)
        .filter(BillSeries.id == series_id)
        .with_for_update()
        .first()
    )
    if not row or not row.is_active:
        raise HTTPException(404, "bill series not found")
    next_num = row.current_num + 1 if row.current_num >= row.start_num else row.start_num
    if next_num > row.end_num:
        raise HTTPException(400, "bill series exhausted — select a new series")
    row.current_num = next_num
    db.flush()
    return f"{row.prefix}{next_num}"


def _assert_bill_number_free(db: Session, bill_number: str, *, exclude_bill_id: int | None = None) -> None:
    q = db.query(CustomerBill).filter(
        CustomerBill.bill_number == bill_number,
        CustomerBill.cancelled_at.is_(None),
    )
    if exclude_bill_id is not None:
        q = q.filter(CustomerBill.id != exclude_bill_id)
    clash = q.first()
    if clash:
        raise HTTPException(400, f"bill number {bill_number} already used on another open bill")


def resolve_bill_number(db: Session, series_id: int, override: str | None = None) -> str:
    """TEMP: custom number allowed. Series cursor advances only if using next series number."""
    custom = (override or "").strip()
    preview = bill_series_preview(db, series_id)
    next_num = preview.get("next_bill_number")
    if custom:
        _assert_bill_number_free(db, custom)
        if next_num and custom == next_num:
            return allocate_bill_number(db, series_id)
        return custom
    return allocate_bill_number(db, series_id)
