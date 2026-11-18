"""Notes stuck on a tile, and the shared sticky board."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import AuthContext, get_auth_context
from app.models.board import StickyNote, TileNote

router = APIRouter(tags=["notes"])


class NoteBody(BaseModel):
    body: str = ""


def _who(auth: AuthContext) -> str:
    return (auth.actor_name or "").strip() or "Staff"


def _clean_key(tile_key: str) -> str:
    key = (tile_key or "").strip()
    if not key or len(key) > 160 or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:._-" for ch in key):
        raise HTTPException(400, "bad note")
    return key


@router.get("/tile-notes")
def list_tile_notes(
    keys: str = "",
    detail: bool = False,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    wanted = []
    for part in (keys or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            wanted.append(_clean_key(part))
        except HTTPException:
            continue
        if len(wanted) >= 300:
            break
    if not wanted:
        return {}
    return tile_note_payload(db, wanted, detail=detail)


def tile_note_payload(db: Session, wanted: list[str], *, detail: bool) -> dict:
    rows = db.query(TileNote).filter(TileNote.tile_key.in_(wanted)).all()
    bodies = {row.tile_key: row.body for row in rows}
    if not detail:
        return bodies
    by_name = {}
    missing = []
    for row in rows:
        name = (row.updated_by_name or "").strip()
        if name:
            by_name[row.tile_key] = name
        else:
            missing.append(row.tile_key)
    if missing:
        from app.models.board import TextEvent
        events = (
            db.query(TextEvent)
            .filter(TextEvent.kind == "note", TextEvent.subject.in_(missing))
            .order_by(TextEvent.id.desc())
            .all()
        )
        for event in events:
            if event.subject in by_name:
                continue
            name = (event.actor_name or "").strip()
            if name and (event.body or "").strip():
                by_name[event.subject] = name
    return {
        key: {"body": bodies[key], "by": by_name.get(key, "")}
        for key in bodies
    }


@router.put("/tile-notes/{tile_key}")
def save_tile_note(
    tile_key: str,
    body: NoteBody,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    key = _clean_key(tile_key)
    text = (body.body or "").strip()[:800]
    row = db.query(TileNote).filter(TileNote.tile_key == key).one_or_none()
    if not text:
        if row is not None:
            db.delete(row)
        from app.services.text_events import remember
        remember(db, kind="note", subject=key, body="", actor=_who(auth))
        db.commit()
        return {"tile_key": key, "body": "", "by": ""}
    if row is None:
        row = TileNote(tile_key=key, body=text, updated_by_name=_who(auth))
        db.add(row)
    else:
        row.body = text
        row.updated_by_name = _who(auth)
    from app.services.text_events import remember
    remember(db, kind="note", subject=key, body=text, actor=_who(auth))
    db.commit()
    return {"tile_key": key, "body": text, "by": _who(auth) if text else ""}


@router.get("/text-events/latest")
def latest_text_events(
    items: str = "",
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    pairs = []
    for part in (items or "").split(","):
        part = part.strip()
        if ":" not in part:
            continue
        kind, subject = part.split(":", 1)
        pairs.append((kind, subject))
        if len(pairs) >= 300:
            break
    from app.services.text_events import latest_map
    return latest_map(db, pairs)


@router.get("/text-events")
def list_text_events(
    kind: str = "",
    subject: str = "",
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    if kind not in {"order", "bill", "note"} or not subject.strip():
        return []
    from app.services.text_events import history

    return history(db, kind=kind, subject=subject.strip())


@router.get("/sticky-notes")
def list_sticky_notes(
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    rows = db.query(StickyNote).order_by(StickyNote.id.asc()).all()
    return [
        {"id": row.id, "body": row.body, "author_name": row.author_name}
        for row in rows
    ]


@router.post("/sticky-notes", status_code=201)
def add_sticky_note(
    body: NoteBody,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    text = (body.body or "").strip()[:2000]
    if not text:
        raise HTTPException(400, "Write a note")
    row = StickyNote(body=text, author_name=_who(auth))
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "body": row.body, "author_name": row.author_name}


@router.patch("/sticky-notes/{note_id}")
def edit_sticky_note(
    note_id: int,
    body: NoteBody,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    row = db.get(StickyNote, note_id)
    if row is None:
        raise HTTPException(404, "note not found")
    text = (body.body or "").strip()[:2000]
    if not text:
        db.delete(row)
        db.commit()
        return {"id": note_id, "body": ""}
    row.body = text
    row.author_name = _who(auth)
    db.commit()
    return {"id": row.id, "body": row.body, "author_name": row.author_name}


@router.delete("/sticky-notes/{note_id}")
def delete_sticky_note(
    note_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    row = db.get(StickyNote, note_id)
    if row is not None:
        db.delete(row)
        db.commit()
    return {"ok": True}
