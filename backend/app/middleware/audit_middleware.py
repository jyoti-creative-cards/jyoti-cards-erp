"""Audit middleware — logs every mutating API request automatically."""
from __future__ import annotations

import time
from typing import Optional

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


def _extract_actor(request: Request) -> str:
    """Best-effort: admin key header wins, then Bearer token subject, else IP."""
    from app.config import get_settings
    from app.deps import _is_valid_admin_key
    x_key = request.headers.get("x-admin-key") or request.headers.get("X-Admin-Key")
    if x_key and _is_valid_admin_key(x_key):
        return "admin"
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        try:
            from app.services.tokens import decode_staff_token, staff_id_from_payload
            payload = decode_staff_token(auth[7:])
            uid = staff_id_from_payload(payload)
            name = payload.get("name") or payload.get("email") or f"staff:{uid}"
            return str(name)
        except Exception:
            pass
    fwd = request.headers.get("x-forwarded-for")
    ip = fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")
    return f"ip:{ip}"


def _path_to_entity(path: str, method: str) -> tuple[str, str]:
    """Map /api/v1/customers/123 → ('customer', 'update')."""
    parts = [p for p in path.strip("/").split("/") if p]
    action_map = {"POST": "create", "PATCH": "update", "PUT": "update", "DELETE": "delete"}
    action = action_map.get(method, method.lower())
    # Override based on trailing path segment
    if parts and parts[-1] in ("restore", "reactivate"):
        action = "restore"
    elif parts and parts[-1] == "permanent":
        action = "permanent_delete"
    entity = "unknown"
    for i, p in enumerate(parts):
        if p in ("api", "v1"):
            continue
        if p.isdigit():
            continue
        entity = p.rstrip("s")  # plurals → singular (customers → customer)
        break
    return entity, action


SKIP_PATHS = {"/api/health", "/api/v1/auth/login", "/api/v1/auth/refresh"}
MUTATING_METHODS = {"POST", "PATCH", "PUT", "DELETE"}


class AuditMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        response = await call_next(request)

        if request.method not in MUTATING_METHODS:
            return response
        if request.url.path in SKIP_PATHS:
            return response
        if response.status_code >= 500:
            return response  # skip on server errors — they get logged by uvicorn

        try:
            actor = _extract_actor(request)
            entity, action = _path_to_entity(request.url.path, request.method)
            # Extract entity_id from path if present
            parts = request.url.path.strip("/").split("/")
            entity_id: Optional[int] = None
            for p in parts:
                if p.isdigit():
                    entity_id = int(p)
                    break
            desc = f"{request.method} {request.url.path} → {response.status_code}"

            from app.db.session import SessionLocal
            from app.models.audit_log import AuditLog
            fwd = request.headers.get("x-forwarded-for")
            ip = fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else None)
            db = SessionLocal()
            try:
                db.add(AuditLog(
                    action=action,
                    entity_type=entity,
                    entity_id=entity_id,
                    description=desc,
                    performed_by=actor,
                    ip_address=ip,
                ))
                db.commit()
            finally:
                db.close()
        except Exception:
            pass

        return response
