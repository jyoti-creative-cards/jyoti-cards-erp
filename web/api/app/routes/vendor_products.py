from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db_import import load_dashboard_db
from app.serialize import model_to_json

router = APIRouter(prefix="/vendor-products", tags=["vendor-products"])


class VendorProductCreate(BaseModel):
    vendor_id: int
    vendor_product_id: str
    our_product_id: str
    name: str
    category: Optional[str] = None
    cost_price: Optional[float] = None
    tax_rate: Optional[float] = None
    tax_inclusive: Optional[int] = None
    low_stock_threshold: Optional[float] = None


class VendorProductUpdate(BaseModel):
    vendor_id: int
    vendor_product_id: str
    our_product_id: str
    name: str
    category: Optional[str] = None
    cost_price: Optional[float] = None
    tax_rate: Optional[float] = None
    tax_inclusive: Optional[int] = None
    image_paths: list[str] = []
    low_stock_threshold: Optional[float] = None


@router.get("")
def list_products(vendor_id: Optional[int] = None):
    db = load_dashboard_db()
    if vendor_id is not None:
        return [model_to_json(p) for p in db.list_vendor_products_by_vendor(vendor_id)]
    return [model_to_json(p) for p in db.list_vendor_products()]


@router.get("/{pid}")
def get_product(pid: int):
    db = load_dashboard_db()
    p = db.get_vendor_product(pid)
    if not p:
        raise HTTPException(404, "Product not found")
    return model_to_json(p)


@router.post("", status_code=201)
def create_product(body: VendorProductCreate):
    db = load_dashboard_db()
    pid = db.insert_vendor_product(
        body.vendor_id,
        body.vendor_product_id,
        body.our_product_id,
        body.name,
        body.category,
        body.cost_price,
        body.tax_rate,
        body.tax_inclusive,
        body.low_stock_threshold,
    )
    return {"id": pid}


@router.patch("/{pid}")
def patch_product(pid: int, body: VendorProductUpdate):
    db = load_dashboard_db()
    db.update_vendor_product(
        pid,
        body.vendor_id,
        body.vendor_product_id,
        body.our_product_id,
        body.name,
        body.category,
        body.cost_price,
        body.tax_rate,
        body.tax_inclusive,
        body.image_paths,
        body.low_stock_threshold,
    )
    return {"ok": True}


@router.delete("/{pid}")
def remove_product(pid: int):
    db = load_dashboard_db()
    try:
        db.delete_vendor_product(pid)
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True}
