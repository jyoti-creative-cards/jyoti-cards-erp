"""BizAnalyst-style phone books."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.customer import Customer
from app.services import biz_analyst as biz

router = APIRouter(prefix="/biz", tags=["biz"])


def _rate(raw: Optional[str]) -> Optional[Decimal]:
    text = (raw or "").strip()
    if not text:
        return None
    return Decimal(text)


@router.get("/home")
def biz_home(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    return biz.home(db, from_date, to_date)


@router.get("/drill")
def biz_drill(
    metric: str = Query("sales"),
    group: str = Query("party"),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    rate_min: Optional[str] = Query(None),
    rate_max: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    return biz.drill(db, metric, group, from_date, to_date, _rate(rate_min), _rate(rate_max))


@router.get("/items")
def biz_items(
    q: str = Query(""),
    db: Session = Depends(get_db),
):
    return {"items": biz.search_items(db, q)}


@router.get("/items/{product_id}")
def biz_item(
    product_id: int,
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    row = biz.item_summary(db, product_id, from_date, to_date)
    if not row:
        raise HTTPException(404, "item not found")
    return row


@router.get("/items/{product_id}/customers")
def biz_item_customers(
    product_id: int,
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    return {"rows": biz.item_customers(db, product_id, from_date, to_date)}


@router.get("/items/{product_id}/suppliers")
def biz_item_suppliers(
    product_id: int,
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    return {"rows": biz.item_suppliers(db, product_id, from_date, to_date)}


@router.get("/bills/{bill_id}")
def biz_bill(
    bill_id: int,
    db: Session = Depends(get_db),
):
    row = biz.customer_bill(db, bill_id)
    if not row:
        raise HTTPException(404, "bill not found")
    return row


@router.get("/receipts/{receipt_id}")
def biz_receipt(
    receipt_id: int,
    db: Session = Depends(get_db),
):
    row = biz.supplier_receipt(db, receipt_id)
    if not row:
        raise HTTPException(404, "receipt not found")
    return row


@router.get("/parties")
def biz_parties(q: str = Query(""), db: Session = Depends(get_db)):
    return {"parties": biz.search_parties(db, q)}


@router.post("/orders", status_code=201)
def biz_place_order(body: dict, db: Session = Depends(get_db)):
    """Order punched from the books app. It lands in New orders as Anshul."""
    from app.services.customer_selling.place import create_received_placement
    from app.services import response_cache
    from app.services.doc_jobs import enqueue_order_pdf

    customer = db.get(Customer, int(body.get("customer_id") or 0))
    if not customer:
        raise HTTPException(404, "customer not found")
    lines = []
    for raw in body.get("lines") or []:
        qty = int(raw.get("quantity") or 0)
        product_id = int(raw.get("catalog_product_id") or 0)
        if qty > 0 and product_id:
            lines.append({"catalog_product_id": product_id, "quantity": qty})
    if not lines:
        raise HTTPException(400, "Pick an item and a quantity")
    try:
        placement = create_received_placement(
            db,
            customer_id=customer.id,
            customer_name=customer.business_name,
            lines=lines,
            customer_notes=None,
            allow_negative_stock=False,
            order_source="staff",
            placed_by_name="Anshul",
        )
        typed = (body.get("marking") or "").strip()
        if typed:
            from app.models.customer_order import CustomerOrder
            from app.services.customer_selling.marking import set_order_marking

            set_order_marking(db.get(CustomerOrder, placement.customer_order_id), typed)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    response_cache.invalidate("stock:")
    enqueue_order_pdf(placement.id)
    return {"ok": True, "placement_id": placement.id}


@router.get("/vendor-order-report")
def biz_vendor_order_report(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    include_dcu: bool = Query(False),
    db: Session = Depends(get_db),
):
    from app.services.reports.vendor_order_report import vendor_order_report
    return vendor_order_report(db, from_date, to_date, include_dcu=include_dcu)


@router.get("/markings")
def biz_markings(q: str = Query(""), db: Session = Depends(get_db)):
    from app.services.product_markings import list_assignments
    return {"items": list_assignments(db, q=q), "items_search": biz.search_items(db, q) if q else []}


@router.post("/markings", status_code=201)
def biz_marking_add(
    body: dict,
    db: Session = Depends(get_db),
):
    from datetime import date as date_cls
    from app.services.product_markings import assign_marking
    try:
        count = assign_marking(
            db,
            body.get("product_ids") or [],
            body.get("marking") or "",
            date_cls.fromisoformat(body.get("starts_on")),
            date_cls.fromisoformat(body.get("ends_on")),
        )
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc) or "Check the marking and the dates") from None
    db.commit()
    return {"assigned": count}


@router.patch("/markings/{marking_id}")
def biz_marking_edit(marking_id: int, body: dict, db: Session = Depends(get_db)):
    from datetime import date as date_cls
    from app.services.product_markings import update_marking
    try:
        update_marking(
            db, marking_id,
            text=body.get("marking") or "",
            starts_on=date_cls.fromisoformat(body.get("starts_on")),
            ends_on=date_cls.fromisoformat(body.get("ends_on")),
        )
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc) or "Check the marking and the dates") from None
    db.commit()
    return {"ok": True}


@router.delete("/markings/{marking_id}")
def biz_marking_delete(marking_id: int, db: Session = Depends(get_db)):
    from app.services.product_markings import delete_marking
    try:
        delete_marking(db, marking_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    db.commit()
    return {"ok": True}
