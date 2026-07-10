from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import AuthContext, require_admin
from app.models.manual_loss import ManualLoss
from app.services.finance_overview import finance_overview

router = APIRouter(prefix="/finance", tags=["finance"])


class ManualLossIn(BaseModel):
    loss_date: date
    amount: Decimal = Field(..., gt=0)
    description: Optional[str] = None


class ManualLossOut(BaseModel):
    id: int
    loss_date: date
    amount: str
    description: Optional[str] = None
    created_by_name: str
    created_at: object


@router.get("/overview")
def get_finance_overview(db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)):
    return finance_overview(db)


@router.get("/losses", response_model=List[ManualLossOut])
def list_losses(db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)):
    rows = db.query(ManualLoss).order_by(ManualLoss.loss_date.desc(), ManualLoss.id.desc()).limit(200).all()
    return [
        ManualLossOut(
            id=r.id,
            loss_date=r.loss_date,
            amount=format(r.amount, "f"),
            description=r.description,
            created_by_name=r.created_by_name,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.post("/losses", response_model=ManualLossOut, status_code=status.HTTP_201_CREATED)
def create_loss(body: ManualLossIn, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)):
    row = ManualLoss(
        loss_date=body.loss_date,
        amount=body.amount.quantize(Decimal("0.01")),
        description=body.description,
        created_by_name=auth.actor_name,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return ManualLossOut(
        id=row.id,
        loss_date=row.loss_date,
        amount=format(row.amount, "f"),
        description=row.description,
        created_by_name=row.created_by_name,
        created_at=row.created_at,
    )


@router.delete("/losses/{loss_id}", status_code=204)
def delete_loss(loss_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)):
    row = db.get(ManualLoss, loss_id)
    if not row:
        raise HTTPException(404, "loss not found")
    db.delete(row)
    db.commit()
