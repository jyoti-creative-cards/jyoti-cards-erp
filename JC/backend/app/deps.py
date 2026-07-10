from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, Set

from fastapi import Depends, Header, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_db
from app.models.customer import Customer
from app.models.staff import Staff
from app.services.permissions import parse_permissions
from app.services.tokens import decode_access_token, token_customer_id, token_staff_id

security = HTTPBearer(auto_error=False)


@dataclass
class AuthContext:
    actor_type: str  # admin | staff
    actor_id: Optional[int]
    actor_name: str
    permissions: Set[str] = field(default_factory=set)

    @property
    def is_admin(self) -> bool:
        return self.actor_type == "admin"

    def has(self, perm: str) -> bool:
        if self.is_admin:
            return True
        return perm in self.permissions

    def require(self, perm: str) -> None:
        if not self.has(perm):
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail=f"permission denied: {perm}")


def _is_valid_admin_key(x_admin_key: Optional[str]) -> bool:
    expected = (get_settings().admin_api_key or "").strip()
    return bool(expected and x_admin_key and x_admin_key.strip() == expected)


def get_auth_context(
    x_admin_key_header: Optional[str] = Header(None, alias="X-Admin-Key"),
    x_admin_key_query: Optional[str] = Query(None, alias="x_admin_key"),
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> AuthContext:
    x_admin_key = x_admin_key_header or x_admin_key_query
    if _is_valid_admin_key(x_admin_key):
        return AuthContext(actor_type="admin", actor_id=None, actor_name="Admin")

    if creds and creds.credentials:
        try:
            payload = decode_access_token(creds.credentials)
            if payload.get("type") == "staff":
                sid = token_staff_id(payload)
                row = db.get(Staff, sid)
                if row and row.is_active:
                    return AuthContext(
                        actor_type="staff",
                        actor_id=row.id,
                        actor_name=row.name,
                        permissions=parse_permissions(row.permissions_json),
                    )
        except Exception:
            pass

    expected = (get_settings().admin_api_key or "").strip()
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="ADMIN_API_KEY not configured")
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="unauthorized")


def require_permission(permission: str) -> Callable:
    def _dep(auth: AuthContext = Depends(get_auth_context)) -> AuthContext:
        auth.require(permission)
        return auth
    return _dep


def require_admin(auth: AuthContext = Depends(get_auth_context)) -> AuthContext:
    if not auth.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="admin only")
    return auth


# Legacy customer portal auth
def get_current_customer(
    creds: HTTPAuthorizationCredentials = Depends(HTTPBearer()),
    db: Session = Depends(get_db),
) -> Customer:
    try:
        payload = decode_access_token(creds.credentials)
        cid = token_customer_id(payload)
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid or expired token") from None
    row = db.get(Customer, cid)
    if row is None or not row.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="customer not found")
    return row
