from __future__ import annotations

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import require_admin
from app.models.fiscal_year import AccountingPeriod, FiscalYear

router = APIRouter(prefix="/fiscal-years", tags=["fiscal-years"])


class FiscalYearCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=32)
    start_date: date
    end_date: date


class FiscalYearPublic(BaseModel):
    id: int
    name: str
    start_date: date
    end_date: date
    is_closed: bool

    model_config = {"from_attributes": True}


class PeriodCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=32)
    start_date: date
    end_date: date


class PeriodPublic(BaseModel):
    id: int
    fiscal_year_id: int
    name: str
    start_date: date
    end_date: date
    is_locked: bool

    model_config = {"from_attributes": True}


@router.get("", response_model=List[FiscalYearPublic], dependencies=[Depends(require_admin)])
def list_fiscal_years(db: Session = Depends(get_db)) -> List[FiscalYearPublic]:
    return db.query(FiscalYear).order_by(FiscalYear.start_date.desc()).all()


@router.post("", response_model=FiscalYearPublic, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
def create_fiscal_year(body: FiscalYearCreate, db: Session = Depends(get_db)) -> FiscalYearPublic:
    if body.end_date <= body.start_date:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="end_date must be after start_date")
    row = FiscalYear(name=body.name.strip(), start_date=body.start_date, end_date=body.end_date)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post("/{fy_id}/close", dependencies=[Depends(require_admin)])
def close_fiscal_year(fy_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(FiscalYear, fy_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="fiscal year not found")
    row.is_closed = True
    db.add(row)
    db.commit()
    return {"ok": True, "id": fy_id, "closed": True}


@router.get("/{fy_id}/periods", response_model=List[PeriodPublic], dependencies=[Depends(require_admin)])
def list_periods(fy_id: int, db: Session = Depends(get_db)) -> List[PeriodPublic]:
    db.get(FiscalYear, fy_id) or (_ for _ in ()).throw(HTTPException(status.HTTP_404_NOT_FOUND, detail="fiscal year not found"))
    return db.query(AccountingPeriod).filter(AccountingPeriod.fiscal_year_id == fy_id).order_by(AccountingPeriod.start_date).all()


@router.post("/{fy_id}/periods", response_model=PeriodPublic, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
def create_period(fy_id: int, body: PeriodCreate, db: Session = Depends(get_db)) -> PeriodPublic:
    fy = db.get(FiscalYear, fy_id)
    if fy is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="fiscal year not found")
    if fy.is_closed:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="fiscal year is closed")
    row = AccountingPeriod(fiscal_year_id=fy_id, name=body.name.strip(), start_date=body.start_date, end_date=body.end_date)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post("/{fy_id}/periods/{period_id}/lock", dependencies=[Depends(require_admin)])
def lock_period(fy_id: int, period_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(AccountingPeriod, period_id)
    if row is None or row.fiscal_year_id != fy_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="period not found")
    row.is_locked = True
    db.add(row)
    db.commit()
    return {"ok": True, "id": period_id, "locked": True}


@router.post("/{fy_id}/periods/{period_id}/unlock", dependencies=[Depends(require_admin)])
def unlock_period(fy_id: int, period_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(AccountingPeriod, period_id)
    if row is None or row.fiscal_year_id != fy_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="period not found")
    row.is_locked = False
    db.add(row)
    db.commit()
    return {"ok": True, "id": period_id, "locked": False}
