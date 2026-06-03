from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import require_admin
from app.models.audit_log import AuditLog

router = APIRouter(prefix="/audit-log", tags=["audit"])


class AuditLogPublic(BaseModel):
    id: int
    action: str
    entity_type: str
    entity_id: Optional[int] = None
    description: str
    performed_by: Optional[str] = None
    ip_address: Optional[str] = None
    created_at: datetime


@router.get("", response_model=List[AuditLogPublic], dependencies=[Depends(require_admin)])
def list_audit_log(
    db: Session = Depends(get_db),
    entity_type: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
) -> List[AuditLogPublic]:
    q = db.query(AuditLog).order_by(AuditLog.id.desc())
    if entity_type:
        q = q.filter(AuditLog.entity_type == entity_type)
    if action:
        q = q.filter(AuditLog.action == action)
    if date_from:
        q = q.filter(AuditLog.created_at >= date_from)
    if date_to:
        q = q.filter(AuditLog.created_at <= date_to)
    rows = q.limit(1000).all()
    return [
        AuditLogPublic(
            id=r.id,
            action=r.action,
            entity_type=r.entity_type,
            entity_id=r.entity_id,
            description=r.description,
            performed_by=r.performed_by,
            ip_address=r.ip_address,
            created_at=r.created_at,
        )
        for r in rows
    ]
