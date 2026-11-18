"""History of markings and tile notes. A new save keeps the older rows."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.board import TextEvent


def remember(db: Session, *, kind: str, subject: str, body: str | None, actor: str | None) -> None:
    text = " ".join((body or "").split())[:800]
    key = (subject or "").strip()[:160]
    if not key:
        return
    last = (
        db.query(TextEvent)
        .filter(TextEvent.kind == kind, TextEvent.subject == key)
        .order_by(TextEvent.id.desc())
        .first()
    )
    if last is not None and (last.body or "") == text:
        return
    db.add(TextEvent(
        kind=kind[:20],
        subject=key,
        body=text,
        actor_name=((actor or "").strip() or "Staff")[:200],
    ))


def latest_map(db: Session, pairs: list[tuple[str, str]]) -> dict[str, dict]:
    """Latest saved text for each kind and subject. The key is ``kind:subject``."""
    grouped: dict[str, set[str]] = {}
    for kind, subject in pairs:
        kind = (kind or "").strip()
        subject = (subject or "").strip()[:160]
        if kind not in {"order", "bill", "note"} or not subject:
            continue
        grouped.setdefault(kind, set()).add(subject)
    out: dict[str, dict] = {}
    for kind, subjects in grouped.items():
        rows = (
            db.query(TextEvent)
            .filter(TextEvent.kind == kind, TextEvent.subject.in_(subjects))
            .order_by(TextEvent.id.desc())
            .all()
        )
        for row in rows:
            key = f"{kind}:{row.subject}"
            if key in out:
                continue
            out[key] = {
                "actor_name": (row.actor_name or "").strip(),
                "body": row.body or "",
            }
    return out


def history(db: Session, *, kind: str, subject: str) -> list[dict]:
    rows = (
        db.query(TextEvent)
        .filter(TextEvent.kind == kind, TextEvent.subject == (subject or "").strip())
        .order_by(TextEvent.id.desc())
        .limit(30)
        .all()
    )
    return [
        {
            "body": row.body,
            "actor_name": row.actor_name,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]
