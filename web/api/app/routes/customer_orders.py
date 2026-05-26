from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db_import import load_dashboard_db
from app.serialize import model_to_json

router = APIRouter(prefix="/customer-orders", tags=["customer-orders"])


class CustomerOrderCreate(BaseModel):
    customer_id: int
    product_id: int
    quantity: float
    unit_price: Optional[float] = None
    notes: Optional[str] = None


class CustomerOrderUpdate(BaseModel):
    status: Optional[str] = None
    shipment_id: Optional[str] = None
    transport_name: Optional[str] = None
    transport_number: Optional[str] = None
    notes: Optional[str] = None
    delivery_receipt_number: Optional[str] = None
    delivery_contact: Optional[str] = None
    delivery_notes: Optional[str] = None
    receipt_image_path: Optional[str] = None


@router.get("")
def list_orders(customer_id: Optional[int] = None):
    db = load_dashboard_db()
    if customer_id is not None:
        rows = db.list_customer_orders_for_customer(customer_id)
    else:
        rows = db.list_customer_orders()
    return [model_to_json(x) for x in rows]


@router.get("/{oid}")
def get_order(oid: int):
    db = load_dashboard_db()
    x = db.get_customer_order(oid)
    if not x:
        raise HTTPException(404, "Order not found")
    return model_to_json(x)


@router.post("", status_code=201)
def create_order(body: CustomerOrderCreate):
    db = load_dashboard_db()
    try:
        new_id = db.insert_customer_order(
            body.customer_id,
            body.product_id,
            body.quantity,
            unit_price=body.unit_price,
            notes=body.notes,
        )
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    return {"id": new_id}


@router.patch("/{oid}")
def patch_order(oid: int, body: CustomerOrderUpdate):
    db = load_dashboard_db()
    try:
        db.update_customer_order(
            oid,
            status=body.status,
            shipment_id=body.shipment_id,
            transport_name=body.transport_name,
            transport_number=body.transport_number,
            notes=body.notes,
            delivery_receipt_number=body.delivery_receipt_number,
            delivery_contact=body.delivery_contact,
            delivery_notes=body.delivery_notes,
            receipt_image_path=body.receipt_image_path,
        )
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True}


@router.delete("/{oid}")
def remove_order(oid: int):
    db = load_dashboard_db()
    try:
        db.delete_customer_order(oid)
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True}
