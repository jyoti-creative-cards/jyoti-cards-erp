from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import require_admin
from app.models.bill_series import BillSeries

router = APIRouter(prefix="/bill-series", tags=["bill-series"])


class BillSeriesCreate(BaseModel):
    name: str
    prefix: str
    start_num: int = 1
    end_num: int


class BillSeriesPublic(BaseModel):
    id: int
    name: str
    prefix: str
    start_num: int
    end_num: int
    current_num: int
    is_active: bool
    created_at: datetime


def _to_public(row: BillSeries) -> BillSeriesPublic:
    return BillSeriesPublic(
        id=row.id,
        name=row.name,
        prefix=row.prefix,
        start_num=row.start_num,
        end_num=row.end_num,
        current_num=row.current_num,
        is_active=row.is_active,
        created_at=row.created_at,
    )


def _next_bill_id(row: BillSeries) -> str:
    num = row.current_num + 1 if row.current_num >= row.start_num else row.start_num
    return f"{row.prefix}{num}"


@router.get("", response_model=List[BillSeriesPublic], dependencies=[Depends(require_admin)])
def list_bill_series(db: Session = Depends(get_db)) -> List[BillSeriesPublic]:
    rows = db.query(BillSeries).filter(BillSeries.is_active.is_(True)).order_by(BillSeries.id.asc()).all()
    return [_to_public(r) for r in rows]


@router.post("", response_model=BillSeriesPublic, status_code=201, dependencies=[Depends(require_admin)])
def create_bill_series(body: BillSeriesCreate, db: Session = Depends(get_db)) -> BillSeriesPublic:
    if body.end_num <= body.start_num:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="end_num must be greater than start_num")
    row = BillSeries(
        name=body.name.strip(),
        prefix=body.prefix.strip(),
        start_num=body.start_num,
        end_num=body.end_num,
        current_num=0,
        is_active=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_public(row)


@router.delete("/{series_id}", dependencies=[Depends(require_admin)])
def delete_bill_series(series_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(BillSeries, series_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="series not found")
    row.is_active = False
    db.add(row)
    db.commit()
    return {"ok": True, "id": series_id}


@router.get("/{series_id}/next", dependencies=[Depends(require_admin)])
def peek_next_bill_id(series_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(BillSeries, series_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="series not found")
    if row.current_num >= row.end_num:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="series exhausted")
    next_num = row.current_num + 1 if row.current_num >= row.start_num else row.start_num
    return {"id": f"{row.prefix}{next_num}", "series_id": series_id}


@router.post("/{series_id}/advance", dependencies=[Depends(require_admin)])
def advance_bill_series(series_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(BillSeries, series_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="series not found")
    if row.current_num >= row.end_num:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="series exhausted")
    next_num = row.current_num + 1 if row.current_num >= row.start_num else row.start_num
    row.current_num = next_num
    db.add(row)
    db.commit()
    return {"bill_id": f"{row.prefix}{next_num}", "series_id": series_id, "current_num": next_num}


@router.get("/current-bill-id/{series_id}", dependencies=[Depends(require_admin)])
def current_bill_id(series_id: int, db: Session = Depends(get_db)) -> dict:
    return peek_next_bill_id(series_id, db)
