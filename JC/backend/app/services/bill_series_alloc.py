from __future__ import annotations

from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.bill_series import BillSeries


def bill_series_preview(db: Session, series_id: int) -> dict:
    row = db.get(BillSeries, series_id)
    if not row or not row.is_active:
        raise HTTPException(404, "bill series not found")
    next_num = row.current_num + 1 if row.current_num >= row.start_num else row.start_num
    remaining = max(0, row.end_num - row.current_num + (1 if row.current_num < row.start_num else 0))
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
    row = db.get(BillSeries, series_id)
    if not row or not row.is_active:
        raise HTTPException(404, "bill series not found")
    next_num = row.current_num + 1 if row.current_num >= row.start_num else row.start_num
    if next_num > row.end_num:
        raise HTTPException(400, "bill series exhausted — select a new series")
    row.current_num = next_num
    return f"{row.prefix}{next_num}"
