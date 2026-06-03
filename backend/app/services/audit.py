from __future__ import annotations

from app.models.audit_log import AuditLog
from sqlalchemy.orm import Session


def log_action(
    db: Session,
    action: str,
    entity_type: str,
    entity_id: int | None,
    description: str,
    performed_by: str = "admin",
    ip_address: str | None = None,
) -> None:
    entry = AuditLog(
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        description=description,
        performed_by=performed_by,
        ip_address=ip_address,
    )
    db.add(entry)
