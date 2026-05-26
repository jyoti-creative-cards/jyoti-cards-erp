from __future__ import annotations

from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_db, legacy_active_value
from app.models.customer import Customer
from app.services.tokens import decode_access_token, token_customer_id

security = HTTPBearer()


def require_admin(x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key")) -> None:
    expected = (get_settings().admin_api_key or "").strip()
    if not expected:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ADMIN_API_KEY not configured",
        )
    if not x_admin_key or x_admin_key.strip() != expected:
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
