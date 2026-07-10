from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.models.activity_log import ActivityLog


def log_activity(
    db: Session,
    *,
    actor_type: str,
    actor_id: Optional[int],
    actor_name: str,
    action: str,
    entity_type: str,
    entity_id: Optional[int] = None,
    entity_label: Optional[str] = None,
    detail: Optional[str] = None,
) -> None:
    row = ActivityLog(
        actor_type=actor_type,
        actor_id=actor_id,
        actor_name=actor_name,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_label=entity_label,
        detail=detail,
    )
    db.add(row)


def log_from_auth(db: Session, auth, **kwargs) -> None:
    log_activity(
        db,
        actor_type=auth.actor_type,
        actor_id=auth.actor_id,
        actor_name=auth.actor_name,
        **kwargs,
    )
