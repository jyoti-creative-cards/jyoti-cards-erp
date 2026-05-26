from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.db_import import load_dashboard_db
from app.serialize import customer_public

router = APIRouter(prefix="/customers", tags=["customers"])


class CustomerCreate(BaseModel):
    name: str
    company_name: str = ""
    phone: str
    alternate_phone: str = ""
    address: str = ""
    plain_password: str = Field(..., min_length=1)


class CustomerUpdate(BaseModel):
    name: str
    company_name: str = ""
    phone: str
    alternate_phone: str = ""
    address: str = ""
    new_password: Optional[str] = None


@router.get("")
def list_customers():
    db = load_dashboard_db()
    return [customer_public(c) for c in db.list_customers()]


@router.get("/{cid}")
def get_customer(cid: int):
    db = load_dashboard_db()
    c = db.get_customer(cid)
    if not c:
        raise HTTPException(404, "Customer not found")
    return customer_public(c)


@router.post("", status_code=201)
def create_customer(body: CustomerCreate):
    db = load_dashboard_db()
    try:
        new_id = db.insert_customer(
            body.name,
            body.company_name,
            body.phone,
            body.alternate_phone,
            body.address,
            body.plain_password,
        )
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    return {"id": new_id}


@router.patch("/{cid}")
def patch_customer(cid: int, body: CustomerUpdate):
    db = load_dashboard_db()
    try:
        db.update_customer(
            cid,
            body.name,
            body.company_name,
            body.phone,
            body.alternate_phone,
            body.address,
            body.new_password,
        )
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True}


@router.delete("/{cid}")
def remove_customer(cid: int):
    db = load_dashboard_db()
    try:
        db.delete_customer(cid)
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True}
