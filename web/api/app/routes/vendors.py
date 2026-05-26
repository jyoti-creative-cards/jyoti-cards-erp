from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db_import import load_dashboard_db
from app.serialize import model_to_json

router = APIRouter(prefix="/vendors", tags=["vendors"])


class VendorCreate(BaseModel):
    person_name: str
    company_name: str = ""
    primary_phone: str
    secondary_phone: str = ""
    payment_terms: Optional[int] = None
    billing: Optional[int] = None
    notes: str = ""
    issuer_legal_name: Optional[str] = None
    issuer_address: Optional[str] = None
    issuer_city_pin: Optional[str] = None
    issuer_gstin: Optional[str] = None
    issuer_phone: Optional[str] = None
    issuer_email: Optional[str] = None


class VendorUpdate(VendorCreate):
    pass


@router.get("")
def list_vendors():
    db = load_dashboard_db()
    return [model_to_json(v) for v in db.list_vendors()]


@router.get("/{vid}")
def get_vendor(vid: int):
    db = load_dashboard_db()
    v = db.get_vendor(vid)
    if not v:
        raise HTTPException(404, "Vendor not found")
    return model_to_json(v)


@router.post("", status_code=201)
def create_vendor(body: VendorCreate):
    db = load_dashboard_db()
    vid = db.insert_vendor(
        body.person_name,
        body.company_name,
        body.primary_phone,
        body.secondary_phone,
        body.payment_terms,
        body.billing,
        body.notes,
        body.issuer_legal_name,
        body.issuer_address,
        body.issuer_city_pin,
        body.issuer_gstin,
        body.issuer_phone,
        body.issuer_email,
    )
    return {"id": vid}


@router.patch("/{vid}")
def patch_vendor(vid: int, body: VendorUpdate):
    db = load_dashboard_db()
    db.update_vendor(
        vid,
        body.person_name,
        body.company_name,
        body.primary_phone,
        body.secondary_phone,
        body.payment_terms,
        body.billing,
        body.notes,
        body.issuer_legal_name,
        body.issuer_address,
        body.issuer_city_pin,
        body.issuer_gstin,
        body.issuer_phone,
        body.issuer_email,
    )
    return {"ok": True}


@router.delete("/{vid}")
def remove_vendor(vid: int):
    db = load_dashboard_db()
    try:
        db.delete_vendor(vid)
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True}
