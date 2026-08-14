from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import AuthContext, require_admin
from app.models.payment_mode import PaymentMode
from app.services.activity import log_from_auth

router = APIRouter(prefix="/payment-modes", tags=["payment-modes"])


class PaymentModeIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    is_active: bool = True
    sort_order: int = 0


class PaymentModePublic(BaseModel):
    id: int
    name: str
    is_active: bool
    sort_order: int
    created_at: datetime


def _out(row: PaymentMode) -> PaymentModePublic:
    return PaymentModePublic(
        id=row.id,
        name=row.name,
        is_active=bool(row.is_active),
        sort_order=int(row.sort_order or 0),
        created_at=row.created_at,
    )


@router.get("", response_model=List[PaymentModePublic])
def list_payment_modes(
    active_only: bool = False,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    q = db.query(PaymentMode).order_by(PaymentMode.sort_order.asc(), PaymentMode.name.asc())
    if active_only:
        q = q.filter(PaymentMode.is_active.is_(True))
    return [_out(r) for r in q.all()]


@router.post("", response_model=PaymentModePublic, status_code=status.HTTP_201_CREATED)
def create_payment_mode(
    body: PaymentModeIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "name required")
    exists = db.query(PaymentMode).filter(PaymentMode.name.ilike(name)).first()
    if exists:
        raise HTTPException(400, "mode already exists")
    row = PaymentMode(name=name, is_active=body.is_active, sort_order=body.sort_order)
    db.add(row)
    db.flush()
    log_from_auth(db, auth, action="create", entity_type="payment_mode", entity_id=row.id, entity_label=name, detail="created")
    db.commit()
    db.refresh(row)
    return _out(row)


@router.patch("/{mode_id}", response_model=PaymentModePublic)
def update_payment_mode(
    mode_id: int,
    body: PaymentModeIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    row = db.get(PaymentMode, mode_id)
    if not row:
        raise HTTPException(404, "mode not found")
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "name required")
    clash = (
        db.query(PaymentMode)
        .filter(PaymentMode.name.ilike(name), PaymentMode.id != mode_id)
        .first()
    )
    if clash:
        raise HTTPException(400, "mode already exists")
    row.name = name
    row.is_active = body.is_active
    row.sort_order = body.sort_order
    log_from_auth(db, auth, action="edit", entity_type="payment_mode", entity_id=row.id, entity_label=name, detail="updated")
    db.commit()
    db.refresh(row)
    return _out(row)


@router.delete("/{mode_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_payment_mode(
    mode_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    row = db.get(PaymentMode, mode_id)
    if not row:
        raise HTTPException(404, "mode not found")
    name = row.name
    db.delete(row)
    log_from_auth(db, auth, action="delete", entity_type="payment_mode", entity_id=mode_id, entity_label=name, detail="deleted")
    db.commit()
    return None
