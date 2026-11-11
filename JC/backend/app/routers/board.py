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
    rows = db.query(TileNote).filter(TileNote.tile_key.in_(wanted)).all()
    return {row.tile_key: row.body for row in rows}


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
        db.commit()
        return {"tile_key": key, "body": ""}
    if row is None:
        row = TileNote(tile_key=key, body=text, updated_by_name=_who(auth))
        db.add(row)
    else:
        row.body = text
        row.updated_by_name = _who(auth)
    db.commit()
    return {"tile_key": key, "body": text}


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
