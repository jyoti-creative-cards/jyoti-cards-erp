"""Each person who cancels or voids an entry types their own key."""

from __future__ import annotations

import contextvars

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.staff import Staff
from app.services.passwords import hash_password, verify_password

cancel_actor: contextvars.ContextVar[Staff | None] = contextvars.ContextVar("cancel_actor", default=None)


def set_cancel_key(db: Session, staff: Staff, plain: str) -> None:
    key = (plain or "").strip()
    if len(key) < 2:
        raise HTTPException(400, "Cancel key is too short")
    others = (
        db.query(Staff)
        .filter(Staff.id != staff.id, Staff.deleted_at.is_(None), Staff.cancel_key_hash.isnot(None))
        .all()
    )
    for other in others:
        if verify_password(key, other.cancel_key_hash or ""):
            raise HTTPException(409, "That cancel key is already used by someone else")
    staff.cancel_key_hash = hash_password(key)


def staff_for_key(db: Session, raw: str) -> Staff:
    key = (raw or "").strip()
    if not key:
        raise HTTPException(400, "Enter your cancel key")
    staff_rows = (
        db.query(Staff)
        .filter(Staff.deleted_at.is_(None), Staff.is_active.is_(True), Staff.cancel_key_hash.isnot(None))
        .all()
    )
    for staff in staff_rows:
        if verify_password(key, staff.cancel_key_hash or ""):
            cancel_actor.set(staff)
            return staff
    raise HTTPException(403, "Cancel key does not match")


def require_cancel_key(
    x_cancel_key: str = Header(default=""),
    db: Session = Depends(get_db),
) -> Staff:
    return staff_for_key(db, x_cancel_key)
