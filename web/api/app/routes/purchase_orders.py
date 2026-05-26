from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db_import import load_dashboard_db
from app.serialize import model_to_json

router = APIRouter(prefix="/purchase-orders", tags=["purchase-orders"])


class PurchaseOrderCreate(BaseModel):
    vendor_id: int
    product_id: int
    quantity: float
    unit_cost: float
    payment_terms: Optional[int] = None
    billing: Optional[int] = None
    tax_rate: Optional[float] = None
    tax_inclusive: Optional[int] = None
    notes: str = ""
    transport_name: Optional[str] = None
    transport_number: Optional[str] = None


class PurchaseOrderUpdate(BaseModel):
    vendor_id: int
    product_id: int
    quantity: float
    unit_cost: float
    payment_terms: Optional[int] = None
    billing: Optional[int] = None
    tax_rate: Optional[float] = None
    tax_inclusive: Optional[int] = None
    notes: str = ""
    status: str = "open"
    transport_name: Optional[str] = None
    transport_number: Optional[str] = None


@router.get("")
def list_pos():
    db = load_dashboard_db()
    return [model_to_json(x) for x in db.list_purchase_orders()]


@router.get("/status-counts")
def po_status_counts():
    db = load_dashboard_db()
    return db.get_po_status_counts()


@router.get("/{poid}")
def get_po(poid: int):
    db = load_dashboard_db()
    x = db.get_purchase_order(poid)
    if not x:
        raise HTTPException(404, "Purchase order not found")
    return model_to_json(x)


@router.post("", status_code=201)
def create_po(body: PurchaseOrderCreate):
    db = load_dashboard_db()
    try:
        new_id = db.insert_purchase_order(
            body.vendor_id,
            body.product_id,
            body.quantity,
            body.unit_cost,
            body.payment_terms,
            body.billing,
            body.tax_rate,
            body.tax_inclusive,
            body.notes,
            body.transport_name,
            body.transport_number,
        )
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    return {"id": new_id}


@router.patch("/{poid}")
def patch_po(poid: int, body: PurchaseOrderUpdate):
    db = load_dashboard_db()
    try:
        db.update_purchase_order(
            poid,
            body.vendor_id,
            body.product_id,
            body.quantity,
            body.unit_cost,
            body.payment_terms,
            body.billing,
            body.tax_rate,
            body.tax_inclusive,
            body.notes,
            body.status,
            body.transport_name,
            body.transport_number,
        )
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True}


@router.delete("/{poid}")
def remove_po(poid: int):
    db = load_dashboard_db()
    try:
        db.delete_purchase_order(poid)
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True}
