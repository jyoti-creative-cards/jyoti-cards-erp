"""Each person who cancels or voids an entry types their own key."""

from __future__ import annotations

import contextvars
import hmac
from typing import Optional

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_db
from app.deps import _is_valid_admin_key
from app.models.staff import Staff
from app.services.passwords import hash_password, verify_password

cancel_actor: contextvars.ContextVar[Staff | None] = contextvars.ContextVar("cancel_actor", default=None)


def _same_secret(got: str, expected: str) -> bool:
    if not expected or not got or len(got) != len(expected):
        return False
    return hmac.compare_digest(got, expected)


def set_cancel_key(db: Session, staff: Staff, plain: str) -> None:
    key = (plain or "").strip()
    if len(key) < 2:
        raise HTTPException(400, "Cancel key is too short")
    admin_cancel = (get_settings().admin_cancel_key or "").strip()
    if _same_secret(key, admin_cancel):
        raise HTTPException(409, "That cancel key is already used by someone else")
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
    x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key"),
    db: Session = Depends(get_db),
) -> Optional[Staff]:
    if _is_valid_admin_key(x_admin_key):
        cancel_actor.set(None)
        return None
    return staff_for_key(db, x_cancel_key)
