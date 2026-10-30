from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.bill_series import BillSeries
from app.models.customer_bill import CustomerBill


def _letter_series(row: BillSeries) -> str | None:
    prefix = (row.prefix or "").strip().upper()
    if len(prefix) == 1 and prefix.isalpha() and row.start_num == 1 and row.end_num == 1000:
        return prefix
    return None


def _series_exhausted(row: BillSeries) -> bool:
    next_num = row.current_num + 1 if row.current_num >= row.start_num else row.start_num
    return next_num > row.end_num


def ensure_next_letter_series(db: Session) -> BillSeries | None:
    """When B1-1000 is finished, open C1-1000, then D, and so on.

    Leaves any other series alone. Returns the letter series that still has numbers,
    creating the next letter only when the latest one is used up.
    """
    rows = db.query(BillSeries).filter(BillSeries.is_active.is_(True)).all()
    by_letter: dict[str, BillSeries] = {}
    for row in rows:
        letter = _letter_series(row)
        if letter and letter not in by_letter:
            by_letter[letter] = row
    if not by_letter:
        return None
    letter = max(by_letter)
    while True:
        row = by_letter[letter]
        if not _series_exhausted(row):
            return row
        nxt = chr(ord(letter) + 1)
        if nxt > "Z":
            return None
        if nxt not in by_letter:
            created = BillSeries(
                name=f"{nxt}1-1000",
                prefix=nxt,
                start_num=1,
                end_num=1000,
                current_num=0,
                is_active=True,
            )
            db.add(created)
            db.flush()
            return created
        letter = nxt


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
    """Always advance the series cursor. Cancelled bills keep their numbers (no reuse).

    with_for_update() makes advancing *this* series' cursor race-safe, but can't
    stop two different (overlapping) active series from minting the same string —
    create_bill_series() blocks that at creation time; this is the last-resort
    check in case an overlapping pair already existed before that guard shipped.
    """
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
    bill_number = f"{row.prefix}{next_num}"
    _assert_bill_number_free(db, bill_number)
    row.current_num = next_num
    db.flush()
    return bill_number


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
    """Bill number always comes from the series — no custom override."""
    return allocate_bill_number(db, series_id)
