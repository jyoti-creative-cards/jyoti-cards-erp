from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db_import import load_dashboard_db
from app.serialize import model_to_json

router = APIRouter(prefix="/stock-receipts", tags=["stock-receipts"])


class StockReceiptCreate(BaseModel):
    product_id: int
    po_id: Optional[int] = None
    quantity: float
    shipment_id: Optional[str] = None
    grn_number: Optional[str] = None
    selling_price: Optional[float] = None
    notes: str = ""


class StockReceiptUpdate(BaseModel):
    product_id: int
    po_id: Optional[int] = None
    quantity: float
    shipment_id: Optional[str] = None
    grn_number: Optional[str] = None
    selling_price: Optional[float] = None
    notes: str = ""


@router.get("")
def list_receipts():
    db = load_dashboard_db()
    return [model_to_json(x) for x in db.list_stock_receipts()]


@router.get("/{rid}")
def get_receipt(rid: int):
    db = load_dashboard_db()
    x = db.get_stock_receipt(rid)
    if not x:
        raise HTTPException(404, "Stock receipt not found")
    return model_to_json(x)


@router.post("", status_code=201)
def create_receipt(body: StockReceiptCreate):
    db = load_dashboard_db()
    try:
        new_id = db.insert_stock_receipt(
            body.product_id,
            body.po_id,
            body.quantity,
            body.shipment_id,
            body.grn_number,
            body.selling_price,
            body.notes,
        )
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    return {"id": new_id}


@router.patch("/{rid}")
def patch_receipt(rid: int, body: StockReceiptUpdate):
    db = load_dashboard_db()
    try:
        db.update_stock_receipt(
            rid,
            body.product_id,
            body.po_id,
            body.quantity,
            body.shipment_id,
            body.grn_number,
            body.selling_price,
            body.notes,
        )
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True}


@router.delete("/{rid}")
def remove_receipt(rid: int):
    db = load_dashboard_db()
    try:
        db.delete_stock_receipt(rid)
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True}
