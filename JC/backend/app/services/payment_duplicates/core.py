"""Warn when the same party, amount, and date is paid twice."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.services.biz_date import as_biz_date


def _money(value) -> Decimal:
    return abs(Decimal(str(value or 0))).quantize(Decimal("0.01"))


def same_payment_clashes(
    db: Session,
    model,
    *,
    party_field: str,
    party_id: int,
    amount: Decimal,
    pay_day: date,
    payment_mode: str | None,
) -> list[dict]:
    wanted = _money(amount)
    rows = (
        db.query(model)
        .filter(
            getattr(model, party_field) == party_id,
            model.entry_type == "payment",
            model.deleted_at.is_(None),
            model.reverses_entry_id.is_(None),
        )
        .all()
    )
    reversed_ids = {
        row.reverses_entry_id
        for row in db.query(model.reverses_entry_id).filter(model.reverses_entry_id.isnot(None)).all()
        if row.reverses_entry_id
    }
    clashes = []
    for row in rows:
        if row.id in reversed_ids:
            continue
        row_day = row.value_date or as_biz_date(row.created_at)
        if row_day != pay_day:
            continue
        if _money(row.amount) != wanted:
            continue
        clashes.append({
            "id": row.id,
            "total": format(wanted, "f"),
            "mode": row.payment_mode or "",
            "date": pay_day.isoformat(),
            "ref": row.payment_ref or "",
        })
    return clashes


def reject_duplicate_payment(db: Session, confirm: bool, **kwargs) -> None:
    if confirm:
        return
    clashes = same_payment_clashes(db, **kwargs)
    if clashes:
        raise HTTPException(409, {"message": "This could be a duplicate payment.", "matches": clashes})
