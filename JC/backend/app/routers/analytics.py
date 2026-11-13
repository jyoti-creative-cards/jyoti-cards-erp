"""Admin-only analytics. Staff cannot open these numbers."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import AuthContext, require_admin
from app.services.analytics import core, pdf

router = APIRouter(prefix="/analytics", tags=["analytics"])


class PercentIn(BaseModel):
    percent: Decimal = Field(ge=0, le=10000)


def _pdf(name: str, payload: bytes) -> Response:
    return Response(
        content=payload,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{name}.pdf"'},
    )


@router.get("/filters")
def filters(db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)):
    return core.filter_choices(db)


@router.get("/stock")
def stock(
    from_date: Optional[date] = Query(None),
    year_group: str = Query("", max_length=30),
    categories: Optional[list[str]] = Query(None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    return core.stock_report(db, from_date=from_date, categories=categories or [], year_group=year_group)


@router.get("/stock/pdf")
def stock_pdf(
    from_date: Optional[date] = Query(None),
    year_group: str = Query("", max_length=30),
    categories: Optional[list[str]] = Query(None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    return _pdf("stock-management", pdf.stock_pdf(db, from_date=from_date, categories=categories or [], year_group=year_group))


@router.get("/sales")
def sales(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    return core.sale_balance_report(db, from_date=from_date, to_date=to_date)


@router.get("/sales/pdf")
def sales_pdf(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    return _pdf("sale-to-balance", pdf.sale_pdf(db, from_date=from_date, to_date=to_date))


@router.get("/parties")
def parties(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    return core.party_activity_report(db, from_date=from_date, to_date=to_date)


@router.get("/parties/pdf")
def parties_pdf(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    return _pdf("parties", pdf.party_pdf(db, from_date=from_date, to_date=to_date))


@router.get("/threshold")
def threshold(
    q: str = Query("", max_length=120),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    return core.threshold_list(db, q=q)


@router.get("/threshold/pdf")
def threshold_pdf(
    q: str = Query("", max_length=120),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    return _pdf("item-threshold", pdf.threshold_pdf(db, q=q))


@router.get("/threshold/{product_id}")
def threshold_one(
    product_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    row = core.threshold_detail(db, product_id)
    if row is None:
        raise HTTPException(404, "Item not found")
    return row


@router.patch("/threshold/{product_id}")
def threshold_set(
    product_id: int,
    body: PercentIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    row = core.set_threshold(db, product_id, body.percent)
    if row is None:
        raise HTTPException(404, "Item not found")
    db.commit()
    return row


@router.post("/threshold/defaults")
def threshold_defaults(
    body: PercentIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    count = core.set_default_threshold(db, body.percent)
    db.commit()
    return {"updated": count, "percent": f"{body.percent:.2f}"}
