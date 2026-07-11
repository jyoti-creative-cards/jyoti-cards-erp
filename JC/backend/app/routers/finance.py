from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import AuthContext, require_admin
from app.models.city import City
from app.models.customer import Customer
from app.models.manual_loss import ManualLoss
from app.models.route import Route
from app.services.ar_ledger import build_ar_ledger, customer_ar_totals
from app.services.finance_overview import finance_overview
from app.services.route_collection_pdf import render_route_collection_pdf

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


@router.get("/route-collections")
def list_route_collections(db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)):
    """Routes with AR outstanding from customers in cities on that route."""
    routes = (
        db.query(Route)
        .filter(Route.is_active.is_(True), Route.deleted_at.is_(None))
        .order_by(Route.name.asc())
        .all()
    )
    out = []
    for route in routes:
        city_ids = [
            c.id
            for c in db.query(City)
            .filter(City.route_id == route.id, City.is_active.is_(True), City.deleted_at.is_(None))
            .all()
        ]
        customers = []
        if city_ids:
            customers = (
                db.query(Customer)
                .filter(
                    Customer.city_id.in_(city_ids),
                    Customer.is_active.is_(True),
                    Customer.deleted_at.is_(None),
                )
                .all()
            )
        total = Decimal("0")
        with_balance = 0
        for cust in customers:
            outstanding = customer_ar_totals(db, cust.id)["outstanding"]
            if outstanding > 0:
                with_balance += 1
                total += outstanding
        out.append({
            "route_id": route.id,
            "route_name": route.name,
            "city_count": len(city_ids),
            "customer_count": len(customers),
            "customers_with_outstanding": with_balance,
            "total_outstanding": format(total.quantize(Decimal("0.01")), "f"),
        })
    out.sort(key=lambda x: (-float(x["total_outstanding"]), x["route_name"].lower()))
    return out


@router.get("/route-collections/{route_id}")
def get_route_collection(route_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)):
    route = db.get(Route, route_id)
    if not route or route.deleted_at or not route.is_active:
        raise HTTPException(404, "route not found")
    cities = (
        db.query(City)
        .filter(City.route_id == route_id, City.is_active.is_(True), City.deleted_at.is_(None))
        .order_by(City.name.asc())
        .all()
    )
    city_map = {c.id: c.name for c in cities}
    customers = []
    if cities:
        customers = (
            db.query(Customer)
            .filter(
                Customer.city_id.in_(list(city_map.keys())),
                Customer.is_active.is_(True),
                Customer.deleted_at.is_(None),
            )
            .order_by(Customer.business_name.asc())
            .all()
        )
    rows = []
    total = Decimal("0")
    for cust in customers:
        totals = customer_ar_totals(db, cust.id)
        outstanding = totals["outstanding"]
        if outstanding <= 0:
            continue
        total += outstanding
        rows.append({
            "customer_id": cust.id,
            "business_name": cust.business_name,
            "person_name": cust.person_name,
            "phone": cust.phone,
            "city_id": cust.city_id,
            "city_name": city_map.get(cust.city_id),
            "outstanding": format(outstanding, "f"),
            "bill_total": format(totals["bill_total"], "f"),
            "payment_total": format(totals["payment_total"], "f"),
        })
    return {
        "route_id": route.id,
        "route_name": route.name,
        "cities": [{"id": c.id, "name": c.name} for c in cities],
        "total_outstanding": format(total.quantize(Decimal("0.01")), "f"),
        "customers": rows,
    }


@router.get("/route-collections/{route_id}/customer/{customer_id}")
def get_route_collection_customer(
    route_id: int,
    customer_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    route = db.get(Route, route_id)
    if not route or route.deleted_at:
        raise HTTPException(404, "route not found")
    cust = db.get(Customer, customer_id)
    if not cust or not cust.is_active or cust.deleted_at:
        raise HTTPException(404, "customer not found")
    city = db.get(City, cust.city_id) if cust.city_id else None
    if not city or city.route_id != route_id:
        raise HTTPException(400, "customer not on this route")
    totals = customer_ar_totals(db, customer_id)
    return {
        "route_id": route.id,
        "route_name": route.name,
        "customer_id": cust.id,
        "business_name": cust.business_name,
        "person_name": cust.person_name,
        "phone": cust.phone,
        "city_name": city.name if city else None,
        "outstanding": format(totals["outstanding"], "f"),
        "bill_total": format(totals["bill_total"], "f"),
        "payment_total": format(totals["payment_total"], "f"),
        "ledger": build_ar_ledger(db, customer_id),
    }


@router.get("/route-collections/{route_id}/pdf")
def download_route_collection_pdf(
    route_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    detail = get_route_collection(route_id, db, auth)
    customers_full = []
    for row in detail["customers"]:
        ledger = build_ar_ledger(db, int(row["customer_id"]))
        customers_full.append({**row, "ledger": ledger})
    pdf = render_route_collection_pdf({
        "route_name": detail["route_name"],
        "generated_at": datetime.now(timezone.utc),
        "total_outstanding": detail["total_outstanding"],
        "customers": customers_full,
    })
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in detail["route_name"])[:40]
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="route-collection-{safe}.pdf"'},
    )


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
