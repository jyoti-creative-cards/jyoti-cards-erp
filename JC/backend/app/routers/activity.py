from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import require_admin
from app.models.activity_log import ActivityLog
from app.schemas.staff import ActivityListResponse, ActivityPublic

router = APIRouter(prefix="/activity", tags=["activity"])


@router.get("", response_model=ActivityListResponse, dependencies=[Depends(require_admin)])
def list_activity(
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    action: Optional[str] = Query(None),
    entity_type: Optional[str] = Query(None),
    actor_name: Optional[str] = Query(None),
    actor_id: Optional[int] = Query(None),
) -> ActivityListResponse:
    q = db.query(ActivityLog)
    if action:
        q = q.filter(ActivityLog.action == action)
    if entity_type:
        q = q.filter(ActivityLog.entity_type == entity_type)
    if actor_name:
        q = q.filter(ActivityLog.actor_name.ilike(f"%{actor_name}%"))
    if actor_id is not None:
        q = q.filter(ActivityLog.actor_id == actor_id)
    total = q.with_entities(func.count(ActivityLog.id)).scalar() or 0
    rows = q.order_by(ActivityLog.created_at.desc()).offset(offset).limit(limit).all()
    items = [
        ActivityPublic(
            id=r.id,
            actor_type=r.actor_type,
            actor_id=r.actor_id,
            actor_name=r.actor_name,
            action=r.action,
            entity_type=r.entity_type,
            entity_id=r.entity_id,
            entity_label=r.entity_label,
            detail=r.detail,
            created_at=r.created_at,
        )
        for r in rows
    ]
    return ActivityListResponse(items=items, total=total, limit=limit, offset=offset)
