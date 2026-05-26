"""AR/AP ledgers and cash receipts — maps to ``Dashboard/db.py`` payment helpers."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db_import import load_dashboard_db

router = APIRouter(tags=["accounting-ar-ap"])


@router.get("/ar/ledger")
def ar_ledger():
    db = load_dashboard_db()
    return db.ar_ledger_rows()


@router.get("/ap/ledger")
def ap_ledger():
    db = load_dashboard_db()
    return db.ap_ledger_rows()


@router.get("/ar/open-balance")
def ar_open_balance(
    cob_id: Optional[int] = None,
    customer_invoice_id: Optional[int] = None,
):
    db = load_dashboard_db()
    return {"balance": db.get_ar_open_balance(cob_id, customer_invoice_id=customer_invoice_id)}


@router.get("/ap/open-balance")
def ap_open_balance(
    pob_id: Optional[int] = None,
    vendor_bill_doc_id: Optional[int] = None,
):
    db = load_dashboard_db()
    return {"balance": db.get_ap_open_balance(pob_id, vendor_bill_doc_id=vendor_bill_doc_id)}


@router.get("/ar/payments")
def ar_payments_log():
    db = load_dashboard_db()
    return db.list_ar_payments_log()


@router.get("/ap/payments")
def ap_payments_log():
    db = load_dashboard_db()
    return db.list_ap_payments_log()


class ArPaymentCreate(BaseModel):
    amount: float
    method: Optional[str] = None
    note: Optional[str] = None
    co_billing_id: Optional[int] = None
    customer_invoice_id: Optional[int] = None


class ApPaymentCreate(BaseModel):
    amount: float
    method: Optional[str] = None
    note: Optional[str] = None
    po_billing_id: Optional[int] = None
    vendor_bill_doc_id: Optional[int] = None


@router.post("/ar/payments", status_code=201)
def ar_payment_create(body: ArPaymentCreate):
    db = load_dashboard_db()
    try:
        pid = db.insert_ar_payment(
            body.co_billing_id,
            body.amount,
            body.method,
            body.note,
            customer_invoice_id=body.customer_invoice_id,
        )
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    return {"id": pid}


@router.post("/ap/payments", status_code=201)
def ap_payment_create(body: ApPaymentCreate):
    db = load_dashboard_db()
    try:
        pid = db.insert_ap_payment(
            body.po_billing_id,
            body.amount,
            body.method,
            body.note,
            vendor_bill_doc_id=body.vendor_bill_doc_id,
        )
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    return {"id": pid}


@router.delete("/ar/payments/{pid}")
def ar_payment_delete(pid: int):
    db = load_dashboard_db()
    try:
        db.delete_ar_payment(pid)
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True}


@router.delete("/ap/payments/{pid}")
def ap_payment_delete(pid: int):
    db = load_dashboard_db()
    try:
        db.delete_ap_payment(pid)
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True}
