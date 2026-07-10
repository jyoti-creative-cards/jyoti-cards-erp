from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import AuthContext, get_auth_context
from app.models.catalog_alternative import CatalogAlternative
from app.models.catalog_addon_link import CatalogAddonLink
from app.models.catalog_product import CatalogProduct
from app.models.city import City
from app.models.stock import StockBalance, StockLedger, StockReceipt, StockReceiptLine
from app.models.vendor import Vendor
from app.models.vendor_order import VendorOrder, VendorOrderLine, VendorOrderPlacement
from app.schemas.stock import (
    PlacedLineForReceipt,
    SellingPriceUpdate,
    StockThresholdUpdate,
    StockLedgerEntry,
    StockProductDetail,
    StockProductSummary,
    VendorPlacedOrderForReceipt,
    VendorReceiptCreate,
    OfflineVendorReceiptCreate,
)
from app.services.stock_levels import stock_status_label
from app.schemas.ledger import StockLedgerDetail
from app.services.ap_ledger import post_bill_entry, receipt_bill_amount, receipt_debit_note_total
from app.services.debit_notes import create_debit_note
from app.services.activity import log_from_auth
from app.services.open_lines import reduce_from_open
from app.services.order_summary import pending_qty_by_product, placed_qty_by_product, received_qty_by_product
from app.services.stock_receipt import add_stock, get_open_order, get_or_create_open_order
from app.services.doc_gen import generate_vendor_receipt_document
from app.services.storage import bill_key, presigned_url, presigned_urls, storage_configured, upload_bytes, vendor_folder_slug

router = APIRouter(prefix="/stock", tags=["stock"])


def _vendor_label(vendor: Vendor, city_name: Optional[str]) -> str:
    city = city_name or ""
    return f"{vendor.business_name} — {city}" if city else vendor.business_name


def _vendor_city(db: Session, vendor: Vendor) -> Optional[str]:
    if not vendor.city_id:
        return None
    city = db.get(City, vendor.city_id)
    return city.name if city else None


def _product_public(
    row: CatalogProduct,
    db: Session,
    balance: int = 0,
    threshold: int = 5,
    *,
    addon_count: Optional[int] = None,
    alt_count: Optional[int] = None,
) -> dict:
    vendor = db.get(Vendor, row.vendor_id)
    city_name = _vendor_city(db, vendor) if vendor else None
    vn = vendor.business_name if vendor else None
    label = _vendor_label(vendor, city_name) if vendor else ""
    keys = row.image_keys or []
    if addon_count is None:
        addon_count = db.query(CatalogAddonLink).filter(CatalogAddonLink.catalog_product_id == row.id).count()
    if alt_count is None:
        alt_count = db.query(CatalogAlternative).filter(CatalogAlternative.product_id == row.id).count()
    return {
        "catalog_product_id": row.id,
        "our_product_id": row.our_product_id,
        "vendor_id": row.vendor_id,
        "vendor_name": vn,
        "vendor_city": city_name,
        "vendor_label": label,
        "category": row.category,
        "series": row.series,
        "quantity_on_hand": balance,
        "low_stock_threshold": threshold,
        "stock_status": stock_status_label(balance, threshold),
        "selling_price": format(row.selling_price, "f") if row.selling_price is not None else None,
        "buying_price": format(row.buying_price, "f"),
        "unit": row.unit,
        "image_urls": presigned_urls(keys),
        "addon_count": int(addon_count or 0),
        "alt_count": int(alt_count or 0),
    }


@router.get("/products", response_model=List[StockProductSummary])
def list_stock(
    db: Session = Depends(get_db),
    search: Optional[str] = Query(None),
    auth: AuthContext = Depends(get_auth_context),
):
    q = (
        db.query(CatalogProduct, StockBalance.quantity_on_hand, StockBalance.low_stock_threshold)
        .outerjoin(StockBalance, StockBalance.catalog_product_id == CatalogProduct.id)
        .filter(CatalogProduct.is_active.is_(True), CatalogProduct.deleted_at.is_(None))
    )
    if search:
        s = f"%{search.lower()}%"
        q = q.filter(
            or_(
                func.lower(CatalogProduct.our_product_id).like(s),
                func.lower(CatalogProduct.vendor_product_id).like(s),
            )
        )
    rows = q.order_by(CatalogProduct.our_product_id.asc()).all()
    ids = [prod.id for prod, _, _ in rows]
    addon_counts: dict[int, int] = {}
    alt_counts: dict[int, int] = {}
    if ids:
        for pid, cnt in (
            db.query(CatalogAddonLink.catalog_product_id, func.count(CatalogAddonLink.id))
            .filter(CatalogAddonLink.catalog_product_id.in_(ids))
            .group_by(CatalogAddonLink.catalog_product_id)
            .all()
        ):
            addon_counts[int(pid)] = int(cnt)
        for pid, cnt in (
            db.query(CatalogAlternative.product_id, func.count(CatalogAlternative.id))
            .filter(CatalogAlternative.product_id.in_(ids))
            .group_by(CatalogAlternative.product_id)
            .all()
        ):
            alt_counts[int(pid)] = int(cnt)
    out = []
    for prod, qty, th in rows:
        d = _product_public(prod, db, qty or 0, th or 5, addon_count=addon_counts.get(prod.id, 0), alt_count=alt_counts.get(prod.id, 0))
        out.append(StockProductSummary(**d))
    return out


@router.get("/products/{catalog_product_id}", response_model=StockProductDetail)
def get_stock_detail(
    catalog_product_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    row = db.get(CatalogProduct, catalog_product_id)
    if not row or not row.is_active:
        raise HTTPException(404, "product not found")
    balance_row = db.query(StockBalance).filter(StockBalance.catalog_product_id == catalog_product_id).first()
    qty = balance_row.quantity_on_hand if balance_row else 0
    threshold = balance_row.low_stock_threshold if balance_row else 5

    pending_map = pending_qty_by_product(db, row.vendor_id)
    pending = pending_map.get(catalog_product_id, 0)

    alts = db.query(CatalogAlternative).filter(CatalogAlternative.product_id == catalog_product_id).all()
    alt_pub = []
    for a in alts:
        alt = db.get(CatalogProduct, a.alternative_product_id)
        if alt and alt.is_active:
            vendor = db.get(Vendor, alt.vendor_id)
            city_name = None
            if vendor and vendor.city_id:
                city = db.get(City, vendor.city_id)
                city_name = city.name if city else None
            alt_pub.append({
                "catalog_product_id": alt.id,
                "our_product_id": alt.our_product_id,
                "vendor_name": vendor.business_name if vendor else None,
                "vendor_city": city_name,
                "buying_price": format(alt.buying_price, "f"),
                "selling_price": format(alt.selling_price, "f") if alt.selling_price is not None else None,
                "image_urls": presigned_urls(alt.image_keys or []),
            })

    ledger_rows = (
        db.query(StockLedger)
        .filter(StockLedger.catalog_product_id == catalog_product_id)
        .order_by(StockLedger.created_at.desc())
        .limit(100)
        .all()
    )
    ledger = [
        StockLedgerEntry(
            id=e.id,
            entry_type=e.entry_type,
            quantity_delta=e.quantity_delta,
            balance_after=e.balance_after,
            party=e.party,
            notes=e.notes,
            created_at=e.created_at,
            reference_type=e.reference_type,
            reference_id=e.reference_id,
        )
        for e in ledger_rows
    ]

    base = _product_public(row, db, qty, threshold)
    return StockProductDetail(
        **base,
        vendor_product_id=row.vendor_product_id,
        alternatives=alt_pub,
        quantity_pending=int(pending),
        quantity_sold=0,
        ledger=ledger,
    )


@router.get("/ledger/{ledger_id}", response_model=StockLedgerDetail)
def get_ledger_entry_detail(
    ledger_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    entry = db.get(StockLedger, ledger_id)
    if not entry:
        raise HTTPException(404, "ledger entry not found")
    receipt_data = None
    if entry.reference_type == "stock_receipt" and entry.reference_id:
        receipt = db.get(StockReceipt, entry.reference_id)
        if receipt:
            rlines = db.query(StockReceiptLine).filter(StockReceiptLine.receipt_id == receipt.id).all()
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
                        "quantity_received": ln.quantity_received,
                        "quantity_billed": ln.quantity_billed,
                        "billed_amount": format(ln.billed_amount, "f"),
                        "buying_price": format(ln.buying_price, "f"),
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


@router.patch("/products/{catalog_product_id}/selling-price", response_model=StockProductSummary)
def update_selling_price(
    catalog_product_id: int,
    body: SellingPriceUpdate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    row = db.get(CatalogProduct, catalog_product_id)
    if not row or not row.is_active:
        raise HTTPException(404, "product not found")
    row.selling_price = body.selling_price.quantize(Decimal("0.01")) if body.selling_price is not None else None
    db.commit()
    db.refresh(row)
    balance_row = db.query(StockBalance).filter(StockBalance.catalog_product_id == catalog_product_id).first()
    th = balance_row.low_stock_threshold if balance_row else 5
    qty = balance_row.quantity_on_hand if balance_row else 0
    d = _product_public(row, db, qty, th)
    return StockProductSummary(**d)


@router.patch("/products/{catalog_product_id}/threshold", response_model=StockProductSummary)
def update_stock_threshold(
    catalog_product_id: int,
    body: StockThresholdUpdate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    row = db.get(CatalogProduct, catalog_product_id)
    if not row or not row.is_active:
        raise HTTPException(404, "product not found")
    balance_row = db.query(StockBalance).filter(StockBalance.catalog_product_id == catalog_product_id).first()
    if not balance_row:
        from app.services.stock_receipt import add_stock
        balance_row = StockBalance(catalog_product_id=catalog_product_id, quantity_on_hand=0, low_stock_threshold=body.low_stock_threshold)
        db.add(balance_row)
    else:
        balance_row.low_stock_threshold = body.low_stock_threshold
    db.commit()
    db.refresh(balance_row)
    d = _product_public(row, db, balance_row.quantity_on_hand, balance_row.low_stock_threshold)
    return StockProductSummary(**d)


@router.get("/vendor-order/{vendor_id}/placed", response_model=VendorPlacedOrderForReceipt)
def get_placed_order_for_receipt(
    vendor_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    vendor = db.get(Vendor, vendor_id)
    if not vendor or vendor.deleted_at:
        raise HTTPException(404, "vendor not found")
    city_name = _vendor_city(db, vendor)
    label = _vendor_label(vendor, city_name)
    placed = get_open_order(db, vendor_id, "placed")
    placed_map = placed_qty_by_product(db, vendor_id)
    pending_map = pending_qty_by_product(db, vendor_id)
    if not placed:
        return VendorPlacedOrderForReceipt(vendor_id=vendor_id, vendor_label=label, order_id=None, lines=[])

    all_ids = set(placed_map) | set(pending_map)

    lines: list[PlacedLineForReceipt] = []
    for cat_id in all_ids:
        pending = pending_map.get(cat_id, 0)
        if pending <= 0:
            continue
        prod = db.get(CatalogProduct, cat_id)
        if not prod:
            continue
        lines.append(
            PlacedLineForReceipt(
                catalog_product_id=cat_id,
                our_product_id=prod.our_product_id,
                quantity_ordered=int(placed_map.get(cat_id, 0)),
                quantity_remaining=int(pending),
                buying_price=format(prod.buying_price, "f"),
                unit=prod.unit,
                image_urls=presigned_urls(prod.image_keys or []),
            )
        )
    lines.sort(key=lambda x: x.our_product_id.lower())
    return VendorPlacedOrderForReceipt(
        vendor_id=vendor_id, vendor_label=label, order_id=placed.id, lines=lines
    )


@router.post("/upload-bill")
async def upload_bill(
    vendor_id: int = Form(...),
    bill_number: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
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
    key = bill_key(slug, bill_number, ext)
    upload_bytes(key, data, file.content_type or "application/pdf")
    url = presigned_url(key)
    return {"key": key, "url": url}


@router.post("/receipts/vendor-order", status_code=status.HTTP_201_CREATED)
def create_vendor_receipt(
    body: VendorReceiptCreate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    return _finalize_vendor_receipt(db, auth, body, offline=False)


def _finalize_vendor_receipt(
    db: Session,
    auth: AuthContext,
    body: VendorReceiptCreate,
    *,
    offline: bool,
) -> dict:
    # Include billed-only lines (received 0, billed > 0) so debit notes can attach to them.
    stock_lines = [ln for ln in body.lines if ln.quantity_received > 0]
    bill_lines = [ln for ln in body.lines if ln.quantity_received > 0 or (ln.quantity_billed or 0) > 0]
    if not bill_lines:
        raise HTTPException(400, "enter quantity received or billed on at least one row")

    line_bill_total = sum((ln.billed_amount or Decimal("0")) for ln in bill_lines)
    if body.total_billed_amount is None and line_bill_total <= 0:
        raise HTTPException(400, "enter total bill amount for this shipment")

    vendor = db.get(Vendor, body.vendor_id)
    if not vendor or vendor.deleted_at:
        raise HTTPException(404, "vendor not found")
    city_name = _vendor_city(db, vendor)
    label = _vendor_label(vendor, city_name)

    placed = None
    if not offline:
        placed = get_open_order(db, body.vendor_id, "placed")
        if not placed:
            raise HTTPException(400, "no open placed order for this vendor")

    billed = get_or_create_open_order(db, body.vendor_id, "billed", "billed")
    now = datetime.now(timezone.utc)

    placement = VendorOrderPlacement(
        vendor_order_id=billed.id,
        status="billed",
        placed_by_type=auth.actor_type,
        placed_by_id=auth.actor_id,
        placed_by_name=auth.actor_name,
        placed_at=now,
    )
    db.add(placement)
    db.flush()

    receipt = StockReceipt(
        receipt_type="offline_vendor" if offline else "vendor_order",
        vendor_id=body.vendor_id,
        placed_order_id=placed.id if placed else None,
        billed_placement_id=placement.id,
        additional_charges=body.additional_charges.quantize(Decimal("0.01")) if body.additional_charges is not None else None,
        total_billed_amount=body.total_billed_amount.quantize(Decimal("0.01")) if body.total_billed_amount is not None else None,
        bill_number=(body.bill_number or "").strip() or None,
        bill_file_key=body.bill_file_key,
        received_by_type=auth.actor_type,
        received_by_id=auth.actor_id,
        received_by_name=auth.actor_name,
        received_at=now,
    )
    db.add(receipt)
    db.flush()

    line_summary = []
    for ln in bill_lines:
        prod = db.get(CatalogProduct, ln.catalog_product_id)
        if not prod or prod.vendor_id != body.vendor_id:
            raise HTTPException(400, f"invalid product {ln.catalog_product_id} for vendor")

        recv_qty = int(ln.quantity_received or 0)
        billed_qty = int(ln.quantity_billed or 0)

        if recv_qty > 0:
            db.add(
                VendorOrderLine(
                    placement_id=placement.id,
                    catalog_product_id=prod.id,
                    our_product_id=prod.our_product_id,
                    quantity=recv_qty,
                    quantity_remaining=recv_qty,
                    quantity_billed=billed_qty,
                    billed_amount=ln.billed_amount.quantize(Decimal("0.01")),
                    buying_price=prod.buying_price,
                )
            )

        # Always persist receipt line (including billed-only) for debit-note product resolution.
        db.add(
            StockReceiptLine(
                receipt_id=receipt.id,
                catalog_product_id=prod.id,
                our_product_id=prod.our_product_id,
                quantity_received=recv_qty,
                quantity_billed=billed_qty,
                billed_amount=ln.billed_amount.quantize(Decimal("0.01")),
                buying_price=prod.buying_price,
            )
        )
        if recv_qty > 0:
            add_stock(
                db,
                catalog_product_id=prod.id,
                our_product_id=prod.our_product_id,
                quantity=recv_qty,
                entry_type="received",
                reference_type="stock_receipt",
                reference_id=receipt.id,
                party=label,
                notes=f"Bill {body.bill_number or '—'}" + (" (offline)" if offline else ""),
            )
            line_summary.append(f"{prod.our_product_id}+{recv_qty}")
        else:
            line_summary.append(f"{prod.our_product_id} billed {billed_qty} (0 received)")

    if not offline and stock_lines:
        reduce_from_open(
            db,
            body.vendor_id,
            [(ln.catalog_product_id, ln.quantity_received) for ln in stock_lines],
        )

    bill_total = receipt_bill_amount(db, receipt.id)
    if bill_total != 0:
        from app.models.accounts_payable import ApLedgerEntry
        existing_bill = (
            db.query(ApLedgerEntry)
            .filter(ApLedgerEntry.receipt_id == receipt.id, ApLedgerEntry.entry_type == "bill")
            .first()
        )
        if not existing_bill:
            post_bill_entry(
                db,
                vendor_id=body.vendor_id,
                receipt_id=receipt.id,
                amount=bill_total,
                description=f"Bill {body.bill_number or receipt.id} — ₹{bill_total}",
                actor_type=auth.actor_type,
                actor_id=auth.actor_id,
                actor_name=auth.actor_name,
            )

    bill_product_ids = {ln.catalog_product_id for ln in bill_lines}
    for dn_in in body.debit_notes or []:
        if dn_in.note_type == "item" and dn_in.catalog_product_id not in bill_product_ids:
            raise HTTPException(400, "debit note item must be from billed or received lines")
        create_debit_note(db, auth, vendor_id=body.vendor_id, receipt_id=receipt.id, body=dn_in)

    if placed:
        placed.updated_at = now
    billed.updated_at = now
    log_from_auth(
        db,
        auth,
        action="receive" if not offline else "offline_receive",
        entity_type="stock_receipt",
        entity_id=receipt.id,
        entity_label=label,
        detail=", ".join(line_summary[:10]),
    )
    doc_url = None
    if storage_configured():
        try:
            key = generate_vendor_receipt_document(db, receipt.id)
            doc_url = presigned_url(key) if key else None
        except Exception:
            pass
    db.commit()
    return {
        "ok": True,
        "receipt_id": receipt.id,
        "billed_placement_id": placement.id,
        "message": f"{'Offline order' if offline else 'Received stock'} for {len(stock_lines)} product(s)",
        "document_url": doc_url,
        "receipt_document_key": receipt.receipt_document_key,
    }


@router.post("/receipts/offline-vendor", status_code=status.HTTP_201_CREATED)
def create_offline_vendor_receipt(
    body: OfflineVendorReceiptCreate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    return _finalize_vendor_receipt(db, auth, body, offline=True)


@router.get("/receipts/{receipt_id}")
def get_receipt_detail(
    receipt_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    receipt = db.get(StockReceipt, receipt_id)
    if not receipt:
        raise HTTPException(404, "receipt not found")
    rlines = db.query(StockReceiptLine).filter(StockReceiptLine.receipt_id == receipt.id).all()
    bill_amt = receipt_bill_amount(db, receipt.id)
    dn_total = receipt_debit_note_total(db, receipt.id)
    data = {
        "id": receipt.id,
        "vendor_id": receipt.vendor_id,
        "bill_number": receipt.bill_number,
        "additional_charges": format(receipt.additional_charges, "f") if receipt.additional_charges is not None else None,
        "total_billed_amount": format(receipt.total_billed_amount, "f") if receipt.total_billed_amount is not None else None,
        "bill_amount": format(bill_amt, "f"),
        "debit_note_total": format(dn_total, "f"),
        "net_payable": format(bill_amt + dn_total, "f"),
        "bill_file_url": presigned_url(receipt.bill_file_key) if receipt.bill_file_key else None,
        "receipt_document_url": presigned_url(receipt.receipt_document_key) if receipt.receipt_document_key else None,
        "received_at": receipt.received_at.isoformat(),
        "lines": [
            {
                "our_product_id": ln.our_product_id,
                "quantity_received": ln.quantity_received,
                "quantity_billed": ln.quantity_billed,
                "billed_amount": format(ln.billed_amount, "f"),
                "buying_price": format(ln.buying_price, "f"),
            }
            for ln in rlines
        ],
    }
    if auth.is_admin:
        data["received_by_name"] = receipt.received_by_name
    return data


@router.get("/receipts/{receipt_id}/document")
def get_receipt_document(
    receipt_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    receipt = db.get(StockReceipt, receipt_id)
    if not receipt:
        raise HTTPException(404, "receipt not found")
    if storage_configured():
        try:
            generate_vendor_receipt_document(db, receipt.id)
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
    auth: AuthContext = Depends(get_auth_context),
):
    receipt = db.get(StockReceipt, receipt_id)
    if not receipt:
        raise HTTPException(404, "receipt not found")
    lines = db.query(StockReceiptLine).filter(StockReceiptLine.receipt_id == receipt_id).all()
    return [
        {
            "catalog_product_id": ln.catalog_product_id,
            "our_product_id": ln.our_product_id,
            "buying_price": format(ln.buying_price, "f"),
            "quantity_received": ln.quantity_received,
        }
        for ln in lines
    ]
