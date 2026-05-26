"""Customer order billing & PO billing rows — align with Streamlit Billing."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.db_import import load_dashboard_db
from app.serialize import model_to_json

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/customer-order-billings")
def list_cob():
    db = load_dashboard_db()
    return [model_to_json(x) for x in db.list_customer_order_billings()]


@router.get("/customer-order-billings/{bid}")
def get_cob(bid: int):
    db = load_dashboard_db()
    b = db.get_customer_order_billing(bid)
    if not b:
        raise HTTPException(404, "Not found")
    return model_to_json(b)


@router.get("/customer-orders/eligible-billing")
def cob_eligible():
    db = load_dashboard_db()
    return {"order_ids": db.list_customer_order_ids_eligible_new_billing()}


@router.get("/po-billings")
def list_pob():
    db = load_dashboard_db()
    return [model_to_json(x) for x in db.list_po_billings()]


@router.get("/po-billings/{bid}")
def get_pob(bid: int):
    db = load_dashboard_db()
    b = db.get_po_billing(bid)
    if not b:
        raise HTTPException(404, "Not found")
    return model_to_json(b)


@router.get("/purchase-orders/eligible-billing")
def pob_eligible():
    db = load_dashboard_db()
    return {"po_ids": db.list_po_ids_eligible_new_billing()}
