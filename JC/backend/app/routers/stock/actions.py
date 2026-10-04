from __future__ import annotations
"""Split from app/routers/stock.py."""

from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import func, or_, text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import AuthContext, get_auth_context, require_admin, require_permission
from app.models.catalog_alternative import CatalogAlternative
from app.models.catalog_addon_link import CatalogAddonLink
from app.models.catalog_product import CatalogProduct
from app.models.city import City
from app.models.stock import StockBalance, StockLedger, StockReceipt, StockReceiptLine
from app.models.vendor import Vendor
from app.schemas.stock import (
    BillPreviewIn,
    BillPreviewOut,
    BulkSellingPriceIn,
    PendingBillReceipt,
    PlacedLineForReceipt,
    ReceiptForBillDetail,
    ReceiptLineForBill,
    ReservedByPartyRow,
    SellingPriceUpdate,
    StockAdjustIn,
    StockThresholdUpdate,
    StockLedgerEntry,
    StockProductDetail,
    StockProductSummary,
    VendorBillIn,
    VendorPendingBillList,
    VendorPlacedOrderForReceipt,
    VendorReceiptCreate,
    VendorReceiveCreate,
    OfflineVendorReceiptCreate,
    VoidIn,
)
from app.services.cost_visibility import can_see_cost, hide_cost
from app.services.pricing import coerce_selling_price, effective_selling_price
from app.services.stock_levels import admin_stock_status_label
from app.schemas.ledger import StockLedgerDetail
from app.models.debit_note import DebitNote
from app.services.ap_ledger import debit_note_payable_effect, receipt_bill_amount, receipt_debit_note_total
from app.services.activity import log_from_auth
from app.services.order_summary import pending_qty_by_product, placed_qty_by_product, received_qty_by_product, reserved_by_party
from app.services.stock_receipt import get_open_order
from app.services.doc_gen import generate_vendor_receipt_document
from app.services import response_cache
from app.services.history import list_entity_history
from app.services.document_present import present
from app.services.receipt_edit import update_vendor_receipt
from app.services.vendor_receive_bill import (
    bill_receipt,
    preview_bill_deviations,
    receive_vendor_goods,
)
from app.services.storage import bill_key, presigned_url, presigned_urls, storage_configured, upload_bytes, vendor_folder_slug
from app.services.void_service import void_receipt

from app.routers.stock.router import router

def _vendor_map(db: Session, vendor_ids: list[int]) -> dict[int, tuple[Optional[str], Optional[str]]]:
    ids = sorted({int(v) for v in vendor_ids if v})
    if not ids:
        return {}
    vendors = db.query(Vendor).filter(Vendor.id.in_(ids)).all()
    city_ids = sorted({v.city_id for v in vendors if v.city_id})
    cities = {
        c.id: c.name
        for c in (db.query(City).filter(City.id.in_(city_ids)).all() if city_ids else [])
    }
    return {
        v.id: (v.business_name, cities.get(v.city_id) if v.city_id else None)
        for v in vendors
    }

@router.get("/ledger/{ledger_id}", response_model=StockLedgerDetail)
def get_ledger_entry_detail(
    ledger_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("stock.read")),
):
    entry = db.get(StockLedger, ledger_id)
    if not entry:
        raise HTTPException(404, "ledger entry not found")
    receipt_data = None
    if entry.reference_type == "stock_receipt" and entry.reference_id:
        receipt = db.get(StockReceipt, entry.reference_id)
        if receipt:
            rlines = db.query(StockReceiptLine).filter(StockReceiptLine.receipt_id == receipt.id).all()
            rproducts = {
                p.id: p
                for p in db.query(CatalogProduct).filter(
                    CatalogProduct.id.in_([ln.catalog_product_id for ln in rlines])
                ).all()
            } if rlines else {}
            receipt_data = {
                "id": receipt.id,
                "vendor_id": receipt.vendor_id,
                "bill_number": receipt.bill_number,
                "additional_charges": format(receipt.additional_charges, "f") if receipt.additional_charges is not None else None,
                "bill_file_url": presigned_url(receipt.bill_file_key) if receipt.bill_file_key else None,
                "received_at": receipt.received_at.isoformat(),
                "lines": [
                    {
                        "our_product_id": ln.our_product_id,
                        "vendor_product_id": (rproducts.get(ln.catalog_product_id).vendor_product_id if rproducts.get(ln.catalog_product_id) else None),
                        "quantity_received": ln.quantity_received,
                        "quantity_billed": ln.quantity_billed,
                        "billed_amount": format(ln.billed_amount, "f"),
                        "buying_price": hide_cost(format(ln.buying_price, "f"), auth),
                    }
                    for ln in rlines
                ],
            }
            if auth.is_admin:
                receipt_data["received_by_name"] = receipt.received_by_name
                receipt_data["received_by_type"] = receipt.received_by_type
    return StockLedgerDetail(
        id=entry.id,
        entry_type=entry.entry_type,
        quantity_delta=entry.quantity_delta,
        balance_after=entry.balance_after,
        party=entry.party,
        notes=entry.notes,
        created_at=entry.created_at,
        reference_type=entry.reference_type,
        reference_id=entry.reference_id,
        receipt=receipt_data,
    )

@router.post("/products/selling-price/bulk", dependencies=[Depends(require_admin)])
def bulk_update_selling_price(
    body: BulkSellingPriceIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    updated = 0
    for item in body.items:
        row = db.get(CatalogProduct, item.catalog_product_id)
        if not row or not row.is_active or row.deleted_at:
            raise HTTPException(400, f"product {item.catalog_product_id} not found")
        coerced = coerce_selling_price(row.buying_price, item.selling_price)
        if coerced is None:
            raise HTTPException(400, f"sell price for {row.our_product_id} must differ from buy price")
        row.selling_price = coerced
        updated += 1
    log_from_auth(
        db,
        auth,
        action="update",
        entity_type="catalog",
        entity_id=None,
        entity_label=None,
        detail=f"bulk selling price — {updated} products",
    )
    db.commit()
    response_cache.invalidate("stock:")
    response_cache.invalidate("catalog:")
    response_cache.invalidate("shop:")
    return {"ok": True, "updated": updated}

@router.get("/vendor-order/{vendor_id}/billed")
def get_billed_receipts_detail(
    vendor_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.read")),
) -> dict:
    """Detail for the 'Billed' tab's per-vendor expand/drill-down — see
    build_vendor_billed_detail docstring for why this can't come from /vendor-orders/{id}."""
    from app.services.stock_receipt import build_vendor_billed_detail

    vendor = db.get(Vendor, vendor_id)
    if not vendor or vendor.deleted_at:
        raise HTTPException(404, "vendor not found")
    return build_vendor_billed_detail(db, vendor_id, auth)

@router.get("/vendor-order/{vendor_id}/received-detail")
def get_received_receipts_detail(
    vendor_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.read")),
) -> dict:
    """Detail for the 'Received' tab's full-page per-vendor drill-down (per-line
    breakdown) — see build_vendor_received_detail docstring. The lighter-weight
    receipt-summary `/received` endpoint above still powers the hub card's mini-expand
    and the "Bill Order" review; this one is for the full detail page's line tables."""
    from app.services.stock_receipt import build_vendor_received_detail

    vendor = db.get(Vendor, vendor_id)
    if not vendor or vendor.deleted_at:
        raise HTTPException(404, "vendor not found")
    return build_vendor_received_detail(db, vendor_id, auth)

@router.post("/receipts/{receipt_id}/bill-preview", response_model=BillPreviewOut)
def preview_receipt_bill(
    receipt_id: int,
    body: BillPreviewIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.read")),
) -> BillPreviewOut:
    receipt = db.get(StockReceipt, receipt_id)
    if not receipt or receipt.deleted_at or receipt.bill_status != "pending_bill":
        raise HTTPException(404, "receipt not open for billing")
    vendor = db.get(Vendor, receipt.vendor_id)
    if not vendor or vendor.deleted_at:
        raise HTTPException(404, "vendor not found")
    rlines = db.query(StockReceiptLine).filter(StockReceiptLine.receipt_id == receipt_id).all()
    billed_qty_by_pid = {
        ln_in.catalog_product_id: int(ln_in.quantity_billed)
        for ln_in in (body.lines or [])
        if ln_in.quantity_billed is not None
    }
    billed_amount_by_pid = {
        ln_in.catalog_product_id: ln_in.billed_amount
        for ln_in in (body.lines or [])
        if ln_in.billed_amount is not None
    }
    products = {
        p.id: p
        for p in db.query(CatalogProduct).filter(
            CatalogProduct.id.in_([ln.catalog_product_id for ln in rlines])
        ).all()
    } if rlines else {}
    result = preview_bill_deviations(
        db, vendor, rlines, billed_qty_by_pid, body.total_billed_amount.quantize(Decimal("0.01")),
        products=products, billed_amount_by_pid=billed_amount_by_pid,
        billing_pct=body.billing_pct_override, gst_rate_pct=body.gst_rate_pct_override,
    )
    return BillPreviewOut(**result)

@router.post("/upload-bill")
async def upload_bill(
    vendor_id: int = Form(...),
    bill_number: str = Form(""),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.write")),
) -> dict:
    if not storage_configured():
        raise HTTPException(503, "S3 not configured")
    vendor = db.get(Vendor, vendor_id)
    if not vendor:
        raise HTTPException(400, "vendor not found")
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty file")
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(400, "file too large (max 10MB)")
    ext = "pdf"
    if file.filename and "." in file.filename:
        ext = file.filename.rsplit(".", 1)[-1].lower()[:8]
    slug = vendor_folder_slug(vendor.business_name)
    key = bill_key(slug, (bill_number or "").strip() or "receive", ext)
    upload_bytes(key, data, file.content_type or "application/pdf")
    url = presigned_url(key)
    return {"key": key, "url": url}

@router.post("/receipts/vendor-receive", status_code=status.HTTP_201_CREATED)
def create_vendor_receive(
    body: VendorReceiveCreate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.write")),
):
    payload = VendorReceiptCreate(
        vendor_id=body.vendor_id,
        lines=body.lines,
        order_receipt_number=body.order_receipt_number,
        bill_file_key=body.bill_file_key,
        notes=body.notes,
        debit_notes=[],
        received_on=body.received_on,
    )
    result = receive_vendor_goods(db, auth, payload)
    response_cache.invalidate("stock:")
    response_cache.invalidate("shop:")
    return result

@router.post("/receipts/{receipt_id}/bill", status_code=status.HTTP_201_CREATED)
def create_receipt_bill(
    receipt_id: int,
    body: VendorBillIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.write")),
):
    result = bill_receipt(db, auth, receipt_id, body)
    response_cache.invalidate("stock:")
    response_cache.invalidate("shop:")
    return result

@router.post("/receipts/offline-vendor", status_code=status.HTTP_201_CREATED)
def create_offline_vendor_receipt(
    body: VendorReceiveCreate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.write")),
):
    """Offline receive only — stock up + Received bucket. Bill later via vendor-bill."""
    payload = VendorReceiptCreate(
        vendor_id=body.vendor_id,
        lines=body.lines,
        order_receipt_number=body.order_receipt_number,
        bill_file_key=body.bill_file_key,
        notes=body.notes,
        debit_notes=[],
        received_on=body.received_on,
    )
    result = receive_vendor_goods(db, auth, payload, offline=True)
    response_cache.invalidate("stock:")
    response_cache.invalidate("shop:")
    return result

@router.get("/receipts/{receipt_id}")
def get_receipt_detail(
    receipt_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.read")),
):
    receipt = db.get(StockReceipt, receipt_id)
    if not receipt:
        raise HTTPException(404, "receipt not found")
    rlines = db.query(StockReceiptLine).filter(StockReceiptLine.receipt_id == receipt.id).all()
    bill_amt = receipt_bill_amount(db, receipt.id)
    dn_total = receipt_debit_note_total(db, receipt.id)
    notes = (
        db.query(DebitNote)
        .filter(DebitNote.receipt_id == receipt.id, DebitNote.deleted_at.is_(None))
        .order_by(DebitNote.id.asc())
        .all()
    )
    history = list_entity_history(db, "stock_receipt", receipt.id)
    products = {
        p.id: p
        for p in db.query(CatalogProduct).filter(
            CatalogProduct.id.in_([ln.catalog_product_id for ln in rlines])
        ).all()
    } if rlines else {}
    kind = "vendor_bill" if receipt.bill_status == "billed" else "vendor_receipt"
    view = present(db, kind, receipt)
    data = {
        "id": receipt.id,
        "vendor_id": receipt.vendor_id,
        "receipt_type": receipt.receipt_type,
        "bill_status": receipt.bill_status,
        "deleted_at": receipt.deleted_at.isoformat() if receipt.deleted_at else None,
        "deleted_reason": receipt.deleted_reason,
        "bill_number": receipt.bill_number,
        "order_receipt_number": receipt.order_receipt_number,
        "display_date": view.get("display_date") or receipt.received_at,
        "display_name": view.get("display_name"),
        "status": view.get("status"),
        "notes": receipt.notes,
        "bill_file_key": receipt.bill_file_key,
        "additional_charges": format(receipt.additional_charges, "f") if receipt.additional_charges is not None else None,
        "billing_pct_applied": format(receipt.billing_pct_applied, "f") if receipt.billing_pct_applied is not None else None,
        "gst_rate_pct_applied": format(receipt.gst_rate_pct_applied, "f") if receipt.gst_rate_pct_applied is not None else None,
        "total_billed_amount": format(receipt.total_billed_amount, "f") if receipt.total_billed_amount is not None else None,
        "bill_amount": format(bill_amt, "f"),
        "debit_note_total": format(dn_total, "f"),
        "net_payable": format(bill_amt + dn_total, "f"),
        "bill_file_url": presigned_url(receipt.bill_file_key) if receipt.bill_file_key else None,
        "receipt_document_url": presigned_url(receipt.receipt_document_key) if receipt.receipt_document_key else None,
        "received_at": receipt.received_at.isoformat(),
        "lines": [
            {
                "catalog_product_id": ln.catalog_product_id,
                "our_product_id": ln.our_product_id,
                "vendor_product_id": (products.get(ln.catalog_product_id).vendor_product_id if products.get(ln.catalog_product_id) else None),
                "quantity_received": ln.quantity_received,
                "quantity_billed": ln.quantity_billed,
                "billed_amount": format(ln.billed_amount, "f"),
                "buying_price": hide_cost(format(ln.buying_price, "f"), auth),
            }
            for ln in rlines
        ],
        "debit_notes": [
            {
                "id": n.id,
                "note_type": n.note_type,
                "direction": n.direction,
                "catalog_product_id": n.catalog_product_id,
                "our_product_id": n.our_product_id,
                "vendor_product_id": (products.get(n.catalog_product_id).vendor_product_id if n.catalog_product_id and products.get(n.catalog_product_id) else None),
                "quantity": n.quantity,
                "amount": format(n.amount, "f"),
                "payable_effect": format(debit_note_payable_effect(n.amount, n.note_type), "f"),
                "notes": n.notes,
            }
            for n in notes
        ],
        "change_history": [
            {
                "change_summary": h.change_summary,
                "valid_from": h.valid_from.isoformat() if h.valid_from else None,
                "snapshot_json": h.snapshot_json,
            }
            for h in history
        ],
    }
    if auth.is_admin:
        data["received_by_name"] = receipt.received_by_name
    return data

@router.post("/receipts/{receipt_id}/void", dependencies=[Depends(require_admin)])
def void_receipt_endpoint(
    receipt_id: int,
    body: VoidIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    result = void_receipt(db, auth, receipt_id, body.reason)
    response_cache.invalidate("stock:")
    response_cache.invalidate("shop:")
    return result

@router.patch("/receipts/{receipt_id}")
def patch_receipt(
    receipt_id: int,
    body: VendorReceiptCreate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.write")),
):
    result = update_vendor_receipt(db, auth, receipt_id, body)
    response_cache.invalidate("stock:")
    response_cache.invalidate("shop:")
    return result

@router.get("/receipts/{receipt_id}/document")
def get_receipt_document(
    receipt_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.read")),
):
    receipt = db.get(StockReceipt, receipt_id)
    if not receipt:
        raise HTTPException(404, "receipt not found")
    if storage_configured():
        try:
            generate_vendor_receipt_document(db, receipt.id, auth)
            db.commit()
            db.refresh(receipt)
        except Exception as exc:
            db.rollback()
            import logging
            logging.getLogger(__name__).exception("receipt PDF generate failed for %s", receipt_id)
            raise HTTPException(500, f"document generation failed: {exc}") from exc
    if not receipt.receipt_document_key:
        raise HTTPException(404, "document not available")
    url = presigned_url(receipt.receipt_document_key)
    if not url:
        raise HTTPException(503, "storage not available")
    return {"document_url": url, "document_key": receipt.receipt_document_key}

@router.get("/receipts/{receipt_id}/lines")
def get_receipt_lines(
    receipt_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.read")),
):
    receipt = db.get(StockReceipt, receipt_id)
    if not receipt:
        raise HTTPException(404, "receipt not found")
    lines = db.query(StockReceiptLine).filter(StockReceiptLine.receipt_id == receipt_id).all()
    products = {
        p.id: p
        for p in db.query(CatalogProduct).filter(
            CatalogProduct.id.in_([ln.catalog_product_id for ln in lines])
        ).all()
    } if lines else {}
    return [
        {
            "catalog_product_id": ln.catalog_product_id,
            "our_product_id": ln.our_product_id,
            "vendor_product_id": (products.get(ln.catalog_product_id).vendor_product_id if products.get(ln.catalog_product_id) else None),
            "buying_price": hide_cost(format(ln.buying_price, "f"), auth),
            "quantity_received": ln.quantity_received,
        }
        for ln in lines
    ]

