"""Customer credit limit — used / left / enforce on bill."""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.services.ar_ledger import customer_ar_totals


def credit_status(db: Session, customer_id: int, *, pending_bill: Decimal | float | int | str | None = None, totals: dict | None = None) -> dict:
    c = db.get(Customer, customer_id)
    if not c or c.deleted_at:
        raise HTTPException(404, "customer not found")
    totals = totals if totals is not None else customer_ar_totals(db, customer_id)
    outstanding = totals["outstanding"]
    limit = Decimal(str(c.credit_limit)) if c.credit_limit is not None else None
    # credit_limit=0 means "track outstanding only, no enforcement"
    track_only = limit is not None and limit == Decimal("0")
    pending = Decimal(str(pending_bill or 0)).quantize(Decimal("0.01"))
    used_after = (outstanding + pending).quantize(Decimal("0.01"))
    left = None if (limit is None or track_only) else (limit - outstanding).quantize(Decimal("0.01"))
    left_after = None if (limit is None or track_only) else (limit - used_after).quantize(Decimal("0.01"))
    # Only flag would_exceed when a real (>0) credit limit is set
    over = bool(not track_only and limit is not None and used_after > limit)
    return {
        "customer_id": customer_id,
        "credit_limit": format(limit, "f") if limit is not None else None,
        "credit_override": bool(c.credit_override),
        "outstanding": format(outstanding, "f"),
        "used": format(outstanding, "f"),
        "left": format(left, "f") if left is not None else None,
        "pending_bill": format(pending, "f"),
        "used_after_bill": format(used_after, "f"),
        "left_after_bill": format(left_after, "f") if left_after is not None else None,
        "would_exceed": over,
        "unlimited": limit is None or track_only,
        "track_only": track_only,
    }


def assert_credit_allows_bill(
    db: Session,
    customer_id: int,
    bill_amount: Decimal,
    *,
    force: bool = False,
) -> dict:
    """Always allows billing — credit limits are informational warnings only, never blockers."""
    status = credit_status(db, customer_id, pending_bill=bill_amount)
    status["overridden"] = False
    status["can_override"] = bool(status["credit_override"])
    return status
