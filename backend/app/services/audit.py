"""Shared audit logging helper — call write_audit() from any router."""
from __future__ import annotations

from typing import Optional

from fastapi import Request
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


def write_audit(
    db: Session,
    action: str,
    entity_type: str,
    entity_id: Optional[int],
    description: str,
    request: Optional[Request] = None,
    performed_by: Optional[str] = None,
) -> None:
    """Insert an audit log row. Silently ignores errors so it never breaks the main flow."""
    try:
        ip: Optional[str] = None
        if request is not None:
            fwd = request.headers.get("x-forwarded-for")
            ip = fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else None)
        db.add(AuditLog(
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            description=description,
            performed_by=performed_by,
            ip_address=ip,
        ))
        db.flush()
    except Exception:
        pass
