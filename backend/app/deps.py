from __future__ import annotations

from typing import Optional

from fastapi import Depends, Header, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_db, legacy_active_value
from app.models.customer import Customer
from app.services.tokens import decode_access_token, decode_staff_token, staff_id_from_payload, token_customer_id

security = HTTPBearer()


def _is_valid_admin_key(x_admin_key: Optional[str]) -> bool:
    expected = (get_settings().admin_api_key or "").strip()
    return bool(expected and x_admin_key and x_admin_key.strip() == expected)


def _staff_from_bearer(authorization: Optional[str], db: Session):  # type: ignore[return]
    """Return StaffUser if bearer token is a valid active staff token, else None."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization[7:]
    try:
        payload = decode_staff_token(token)
        from app.models.staff_user import StaffUser
        uid = staff_id_from_payload(payload)
        user = db.get(StaffUser, uid)
        if user and user.is_active:
            return user
    except Exception:
        pass
    return None


def require_admin(
    x_admin_key_header: Optional[str] = Header(None, alias="X-Admin-Key"),
    x_admin_key_query: Optional[str] = Query(None, alias="x_admin_key"),
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> None:
    """Accept either the admin API key (header or query param) or a valid staff Bearer token."""
    x_admin_key = x_admin_key_header or x_admin_key_query
    if _is_valid_admin_key(x_admin_key):
        return
    if _staff_from_bearer(authorization, db) is not None:
        return
    expected = (get_settings().admin_api_key or "").strip()
    if not expected:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ADMIN_API_KEY not configured",
        )
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="unauthorized")


def get_actor(
    x_admin_key_header: Optional[str] = Header(None, alias="X-Admin-Key"),
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> str:
    """Return a human-readable actor string for audit logs."""
    if _is_valid_admin_key(x_admin_key_header):
        return "admin"
    staff = _staff_from_bearer(authorization, db)
    if staff:
        return f"staff:{getattr(staff, 'name', None) or getattr(staff, 'email', None) or staff.id}"
    return "unknown"


def require_admin_only(
    x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key"),
) -> None:
    """Only the admin API key — used for staff management endpoints."""
    if _is_valid_admin_key(x_admin_key):
        return
    expected = (get_settings().admin_api_key or "").strip()
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="ADMIN_API_KEY not configured")
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid admin key")


def get_current_customer(
    creds: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> Customer:
    try:
        payload = decode_access_token(creds.credentials)
        cid = token_customer_id(payload)
    except Exception:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired token",
        ) from None
    row = db.get(Customer, cid)
    if row is None or not legacy_active_value(row.is_active):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="customer not found")
    return row
