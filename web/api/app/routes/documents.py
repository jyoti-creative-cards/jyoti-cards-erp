"""Document queues (PO / GRN / bills / SO / delivery / invoice) — read-only lists."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.db_import import load_dashboard_db

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("/purchase-orders")
def docs_po():
    db = load_dashboard_db()
    return db.list_purchase_order_documents()


@router.get("/purchase-orders/{doc_id}")
def docs_po_one(doc_id: int):
    db = load_dashboard_db()
    r = db.get_purchase_order_document(doc_id)
    if not r:
        raise HTTPException(404, "Not found")
    return r


@router.get("/purchase-orders/{doc_id}/lines")
def docs_po_lines(doc_id: int):
    db = load_dashboard_db()
    return db.list_purchase_order_document_lines(doc_id)


@router.get("/goods-receipts")
def docs_grn():
    db = load_dashboard_db()
    return db.list_goods_receipt_documents()


@router.get("/goods-receipts/{receipt_id}")
def docs_grn_one(receipt_id: int):
    db = load_dashboard_db()
    r = db.get_goods_receipt_document(receipt_id)
    if not r:
        raise HTTPException(404, "Not found")
    return r


@router.get("/goods-receipts/{receipt_id}/lines")
def docs_grn_lines(receipt_id: int):
    db = load_dashboard_db()
    return db.list_goods_receipt_lines(receipt_id)


@router.get("/vendor-bills")
def docs_vendor_bills():
    db = load_dashboard_db()
    return db.list_vendor_bill_documents()


@router.get("/vendor-bills/{bill_id}")
def docs_vendor_bill_one(bill_id: int):
    db = load_dashboard_db()
    r = db.get_vendor_bill_document(bill_id)
    if not r:
        raise HTTPException(404, "Not found")
    return r


@router.get("/vendor-bills/{bill_id}/lines")
def docs_vendor_bill_lines(bill_id: int):
    db = load_dashboard_db()
    return db.list_vendor_bill_lines(bill_id)


@router.get("/sales-orders")
def docs_so():
    db = load_dashboard_db()
    return db.list_sales_order_documents()


@router.get("/sales-orders/{so_id}")
def docs_so_one(so_id: int):
    db = load_dashboard_db()
    r = db.get_sales_order_document(so_id)
    if not r:
        raise HTTPException(404, "Not found")
    return r


@router.get("/sales-orders/{so_id}/lines")
def docs_so_lines(so_id: int):
    db = load_dashboard_db()
    return db.list_sales_order_document_lines(so_id)


@router.get("/deliveries")
def docs_deliveries():
    db = load_dashboard_db()
    return db.list_delivery_documents()


@router.get("/customer-invoices")
def docs_cust_inv():
    db = load_dashboard_db()
    return db.list_customer_invoice_documents()


@router.get("/history/{entity_type}/{entity_id}")
def docs_history(entity_type: str, entity_id: int):
    db = load_dashboard_db()
    return db.get_document_history(entity_type, entity_id)
