from __future__ import annotations

import calendar
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import or_, text
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.db.session import get_db
from app.deps import require_admin
from app.models.catalog_product import CatalogProduct
from app.models.customer import Customer
from app.models.customer_order import CustomerOrder
from app.models.stock_adjustment import StockAdjustment
from app.models.stock_balance import StockBalance
from app.models.stock_receipt import StockReceipt
from app.models.vendor_purchase_order import VendorPurchaseOrder
from app.routers.purchase_orders import _int_snap, _to_public, receipt_allowed_status
from app.schemas.inventory import (
    BalanceThresholdBody,
    InventoryRowPublic,
    LedgerEntryDetail,
    LedgerMonthSummary,
    ManualStockBody,
    ProductLedgerResponse,
    StockAdjustmentCreate,
    StockAdjustmentPublic,
    StockAdjustmentUpdate,
)
from app.services.catalog_storage import presigned_urls, storage_configured, upload_bytes
from app.services.stock_levels import stock_status_label

router = APIRouter(prefix="/inventory", tags=["inventory"])

_PREFIX = "receipt_documents"


@router.get("/stock-balances", dependencies=[Depends(require_admin)])
def get_all_stock_balances(db: Session = Depends(get_db)) -> list[dict]:
    """Return all stock balances as [{catalog_product_id, balance}] list."""
    rows = db.query(StockBalance).all()
    return [{"catalog_product_id": r.catalog_product_id, "balance": int(r.quantity)} for r in rows]


@router.post("/stock-check", dependencies=[Depends(require_admin)])
def bulk_stock_check(
    body: dict,
    db: Session = Depends(get_db),
) -> dict:
    """Fast bulk stock check. POST {catalog_product_ids: [1,2,3]} → {id: qty}."""
    ids = [int(x) for x in (body.get("catalog_product_ids") or []) if str(x).isdigit()]
    if not ids:
        return {}
    rows = db.query(StockBalance).filter(StockBalance.catalog_product_id.in_(ids)).all()
    result = {r.catalog_product_id: int(r.quantity) for r in rows}
    # products with no balance row = 0 stock
    for cid in ids:
        if cid not in result:
            result[cid] = 0
    return result


def _apply_stock_delta(db: Session, catalog_product_id: int, delta: int) -> StockBalance:
    if delta == 0:
        row = db.get(StockBalance, catalog_product_id)
        if row is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="no stock row for this product")
        return row
    row = db.get(StockBalance, catalog_product_id)
    if row is None:
        if delta < 0:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="cannot remove stock: no balance row (quantity is already 0)",
            )
        nb = StockBalance(catalog_product_id=catalog_product_id, quantity=delta, low_stock_threshold=0)
        db.add(nb)
        db.flush()
        return nb
    new_q = int(row.quantity) + delta
    if new_q < 0:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"insufficient stock: would go to {new_q}",
        )
    row.quantity = new_q
    db.add(row)
    db.flush()
    return row


def _invoice_count_for_product(db: Session, catalog_product_id: int) -> int:
    try:
        dialect = db.bind.dialect.name  # type: ignore[union-attr]
    except Exception:
        dialect = "postgresql"
    if dialect == "postgresql":
        sql = text(
            "SELECT COUNT(*) FROM portal_customer_orders "
            "WHERE items::jsonb @> (:filter)::jsonb AND status != 'cancelled'"
        )
        row = db.execute(sql, {"filter": json.dumps([{"catalog_product_id": catalog_product_id}])}).scalar()
        return int(row or 0)
    # fallback for non-PG (dev sqlite)
    count = 0
    orders = db.query(CustomerOrder).filter(CustomerOrder.status != "cancelled").all()
    for o in orders:
        items = o.items if isinstance(o.items, list) else []
        if any(isinstance(i, dict) and i.get("catalog_product_id") == catalog_product_id for i in items):
            count += 1
    return count


def _inventory_row_public(
    db: Session,
    p: CatalogProduct,
    bal: Optional[StockBalance],
    invoice_count: int = 0,
    selling_price: float = 0.0,
) -> InventoryRowPublic:
    qty = int(bal.quantity) if bal else 0
    th = int(bal.low_stock_threshold) if bal else 0
    keys = p.image_keys if isinstance(p.image_keys, list) else []
    keys_str = [str(k) for k in keys]
    return InventoryRowPublic(
        catalog_product_id=p.id,
        our_product_id=p.our_product_id,
        name=p.name,
        category=p.category,
        vendor_id=p.vendor_id,
        quantity=qty,
        low_stock_threshold=th,
        stock_status=stock_status_label(qty, th),
        image_urls=presigned_urls(keys_str),
        invoice_count=invoice_count,
        selling_price=selling_price,
    )


def _save_receipt_upload(file: Optional[UploadFile]) -> Optional[str]:
    if file is None or not getattr(file, "filename", None):
        return None
    raw = file.file.read()
    if not raw:
        return None
    suf = Path(file.filename or "upload").suffix.lower()
    if suf not in (".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif"):
        suf = ".bin"
    mime = file.content_type or "application/octet-stream"
    key = f"{_PREFIX}/{uuid.uuid4().hex}{suf}"
    upload_bytes(key, raw, mime)
    return key


@router.get("", response_model=List[InventoryRowPublic], dependencies=[Depends(require_admin)])
def list_inventory(
    db: Session = Depends(get_db),
    vendor_id: Optional[int] = Query(None, ge=1),
    q: Optional[str] = Query(None),
    include_zero: bool = Query(False),
    all_catalog: bool = Query(
        False,
        description="If true, list all catalog products (with optional balance); use for admin stock/thresholds",
    ),
    stock_status: Optional[str] = Query(
        None,
        description="Filter: in_stock | low_stock | out_of_stock | negative_stock",
    ),
) -> List[InventoryRowPublic]:
    st_f = (stock_status or "").strip().lower()
    if st_f and st_f not in ("in_stock", "low_stock", "out_of_stock", "negative_stock"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="stock_status must be in_stock, low_stock, out_of_stock, or negative_stock",
        )

    out: List[InventoryRowPublic] = []

    if all_catalog:
        qry = db.query(CatalogProduct)
        if vendor_id is not None:
            qry = qry.filter(CatalogProduct.vendor_id == vendor_id)
        if q and q.strip():
            term = f"%{q.strip()}%"
            qry = qry.filter(
                or_(
                    CatalogProduct.name.ilike(term),
                    CatalogProduct.our_product_id.ilike(term),
                    CatalogProduct.vendor_product_id.ilike(term),
                    CatalogProduct.category.ilike(term),
                )
            )
        for p in qry.order_by(CatalogProduct.our_product_id.asc()).all():
            bal = db.get(StockBalance, p.id)
            inv_cnt = _invoice_count_for_product(db, p.id)
            row = _inventory_row_public(db, p, bal, invoice_count=inv_cnt)
            if st_f and row.stock_status != st_f:
                continue
            out.append(row)
        return out

    q_bal = db.query(StockBalance).join(CatalogProduct, CatalogProduct.id == StockBalance.catalog_product_id)
    if not include_zero:
        q_bal = q_bal.filter(StockBalance.quantity > 0)
    if vendor_id is not None:
        q_bal = q_bal.filter(CatalogProduct.vendor_id == vendor_id)
    if q and q.strip():
        term = f"%{q.strip()}%"
        q_bal = q_bal.filter(
            or_(
                CatalogProduct.name.ilike(term),
                CatalogProduct.our_product_id.ilike(term),
                CatalogProduct.vendor_product_id.ilike(term),
                CatalogProduct.category.ilike(term),
            )
        )
    for bal in q_bal.order_by(CatalogProduct.our_product_id.asc()).all():
        p = db.get(CatalogProduct, bal.catalog_product_id)
        if p is None:
            continue
        inv_cnt = _invoice_count_for_product(db, p.id)
        row = _inventory_row_public(db, p, bal, invoice_count=inv_cnt)
        if st_f and row.stock_status != st_f:
            continue
        out.append(row)
    return out


@router.patch(
    "/balances/{catalog_product_id}",
    response_model=InventoryRowPublic,
    dependencies=[Depends(require_admin)],
)
def patch_balance_threshold(
    catalog_product_id: int,
    body: BalanceThresholdBody,
    db: Session = Depends(get_db),
) -> InventoryRowPublic:
    p = db.get(CatalogProduct, catalog_product_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="catalog product not found")
    bal = db.get(StockBalance, catalog_product_id)
    if bal is None:
        bal = StockBalance(
            catalog_product_id=catalog_product_id,
            quantity=0,
            low_stock_threshold=body.low_stock_threshold,
        )
        db.add(bal)
    else:
        bal.low_stock_threshold = body.low_stock_threshold
        db.add(bal)
    db.commit()
    db.refresh(bal)
    return _inventory_row_public(db, p, bal)


@router.post("/manual", response_model=InventoryRowPublic, dependencies=[Depends(require_admin)])
def add_manual_stock(body: ManualStockBody, db: Session = Depends(get_db)) -> InventoryRowPublic:
    p = db.get(CatalogProduct, body.catalog_product_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="catalog product not found")
    _apply_stock_delta(db, body.catalog_product_id, body.quantity)
    db.commit()
    bal = db.get(StockBalance, body.catalog_product_id)
    return _inventory_row_public(db, p, bal)


@router.get("/adjustments", response_model=List[StockAdjustmentPublic], dependencies=[Depends(require_admin)])
def list_adjustments(
    db: Session = Depends(get_db),
    catalog_product_id: Optional[int] = Query(None, ge=1),
) -> List[StockAdjustmentPublic]:
    q = db.query(StockAdjustment).order_by(StockAdjustment.id.desc())
    if catalog_product_id is not None:
        q = q.filter(StockAdjustment.catalog_product_id == catalog_product_id)
    rows = q.limit(500).all()
    out: List[StockAdjustmentPublic] = []
    for r in rows:
        p = db.get(CatalogProduct, r.catalog_product_id)
        out.append(
            StockAdjustmentPublic(
                id=r.id,
                catalog_product_id=r.catalog_product_id,
                our_product_id=p.our_product_id if p else "",
                quantity_delta=r.quantity_delta,
                note=r.note,
                created_at=r.created_at,
            )
        )
    return out


@router.post(
    "/adjustments",
    response_model=StockAdjustmentPublic,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
def create_adjustment(body: StockAdjustmentCreate, db: Session = Depends(get_db)) -> StockAdjustmentPublic:
    p = db.get(CatalogProduct, body.catalog_product_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="catalog product not found")
    if body.quantity_delta == 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="quantity_delta cannot be 0")

    _apply_stock_delta(db, body.catalog_product_id, body.quantity_delta)
    adj = StockAdjustment(
        catalog_product_id=body.catalog_product_id,
        quantity_delta=body.quantity_delta,
        note=(body.note or "").strip() or None,
    )
    db.add(adj)
    db.commit()
    db.refresh(adj)
    return StockAdjustmentPublic(
        id=adj.id,
        catalog_product_id=adj.catalog_product_id,
        our_product_id=p.our_product_id,
        quantity_delta=adj.quantity_delta,
        note=adj.note,
        created_at=adj.created_at,
    )


@router.patch(
    "/adjustments/{adjustment_id}",
    response_model=StockAdjustmentPublic,
    dependencies=[Depends(require_admin)],
)
def update_adjustment_note(
    adjustment_id: int,
    body: StockAdjustmentUpdate,
    db: Session = Depends(get_db),
) -> StockAdjustmentPublic:
    row = db.get(StockAdjustment, adjustment_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="adjustment not found")
    if body.note is not None:
        row.note = body.note.strip() or None
    db.add(row)
    db.commit()
    db.refresh(row)
    p = db.get(CatalogProduct, row.catalog_product_id)
    return StockAdjustmentPublic(
        id=row.id,
        catalog_product_id=row.catalog_product_id,
        our_product_id=p.our_product_id if p else "",
        quantity_delta=row.quantity_delta,
        note=row.note,
        created_at=row.created_at,
    )


@router.delete("/adjustments/{adjustment_id}", dependencies=[Depends(require_admin)])
def delete_adjustment(adjustment_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(StockAdjustment, adjustment_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="adjustment not found")
    try:
        _apply_stock_delta(db, row.catalog_product_id, -row.quantity_delta)
    except HTTPException:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="cannot delete: reversing this adjustment would make stock negative",
        ) from None
    db.delete(row)
    db.commit()
    return {"ok": True, "id": adjustment_id}


def _parse_bool_form(raw: Optional[str]) -> bool:
    if raw is None:
        return False
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


@router.post("/receipts/from-po", response_model=dict, dependencies=[Depends(require_admin)])
def receipt_from_po(
    purchase_order_id: int = Form(...),
    is_partial: str = Form("false"),
    receipt_number: Optional[str] = Form(None),
    contact_number: Optional[str] = Form(None),
    lines: str = Form(...),
    notes: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    vendor_bill_no: Optional[str] = Form(None),
    bill_photo: Optional[UploadFile] = File(None),
    force_close: str = Form("false"),
    db: Session = Depends(get_db),
) -> dict:
    is_partial_f = _parse_bool_form(is_partial)
    po = db.get(VendorPurchaseOrder, purchase_order_id)
    if po is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="purchase order not found")

    if not receipt_allowed_status(po.status):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="can only receive against a PO in booked or in_progress status",
        )

    try:
        raw_lines = json.loads(lines)
    except json.JSONDecodeError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"invalid lines JSON: {e}") from e
    if not isinstance(raw_lines, list) or not raw_lines:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="lines must be a non-empty array")

    parsed: list[tuple[int, int]] = []
    for x in raw_lines:
        if not isinstance(x, dict):
            continue
        try:
            cid = int(x["catalog_product_id"])
            q = int(x["quantity"])
        except (KeyError, TypeError, ValueError):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="each line needs catalog_product_id and quantity") from None
        if q < 1:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="quantity must be >= 1")
        parsed.append((cid, q))

    if not parsed:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="no valid lines")

    rn = (receipt_number or "").strip()
    cn = (contact_number or "").strip() or None
    if not rn:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="receipt_number is required for each shipment",
        )

    raw_items = po.items if isinstance(po.items, list) else []
    pending_map: dict[int, int] = {}
    item_row_by_cid: dict[int, dict] = {}
    for row in raw_items:
        if not isinstance(row, dict):
            continue
        try:
            cid = int(row["catalog_product_id"])
            ordered = int(row["quantity"])
        except (KeyError, TypeError, ValueError):
            continue
        recv = min(ordered, _int_snap(row, "received_quantity"))
        pend = max(0, ordered - recv)
        pending_map[cid] = pend
        item_row_by_cid[cid] = row

    incoming: dict[int, int] = {}
    for cid, q in parsed:
        if cid not in pending_map:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"catalog_product_id {cid} not on this PO")
        incoming[cid] = incoming.get(cid, 0) + q

    img_key: Optional[str] = None
    if file is not None and getattr(file, "filename", None):
        try:
            img_key = _save_receipt_upload(file)
        except RuntimeError as e:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)) from e

    bill_photo_key: Optional[str] = None
    if bill_photo is not None and getattr(bill_photo, "filename", None):
        try:
            from pathlib import Path as _Path
            raw_bp = bill_photo.file.read()
            if raw_bp:
                suf_bp = _Path(bill_photo.filename or "upload").suffix.lower()
                if suf_bp not in (".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif"):
                    suf_bp = ".bin"
                mime_bp = bill_photo.content_type or "application/octet-stream"
                bill_photo_key = f"po_receipts/{uuid.uuid4().hex}{suf_bp}"
                upload_bytes(bill_photo_key, raw_bp, mime_bp)
        except RuntimeError as e:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)) from e

    line_items_store: list[dict] = []
    for cid, q in incoming.items():
        row = item_row_by_cid.get(cid)
        if row is None:
            continue
        row["received_quantity"] = _int_snap(row, "received_quantity") + q
        line_items_store.append({"catalog_product_id": cid, "quantity": q})
        _apply_stock_delta(db, cid, q)

    sr = StockReceipt(
        purchase_order_id=po.id,
        receipt_number=rn if rn else None,
        contact_number=cn,
        receipt_image_key=img_key,
        is_partial=is_partial_f,
        line_items=line_items_store,
        note=(notes or "").strip() or None,
        vendor_bill_no=(vendor_bill_no or "").strip() or None,
        bill_photo_key=bill_photo_key,
    )
    db.add(sr)

    flag_modified(po, "items")

    all_done = True
    for row in raw_items:
        if not isinstance(row, dict):
            continue
        try:
            ordered = int(row["quantity"])
            recv = _int_snap(row, "received_quantity")
        except (KeyError, TypeError, ValueError):
            continue
        if recv < ordered:
            all_done = False
            break

    force_close_f = _parse_bool_form(force_close)
    if force_close_f or all_done:
        po.status = "closed"
    elif is_partial_f or po.status == "booked":
        po.status = "in_progress"

    db.add(po)
    db.commit()
    db.refresh(po)
    return {
        "ok": True,
        "fully_received": all_done,
        "purchase_order": _to_public(db, po),
    }


@router.post("/receipts/from-vendor", response_model=dict, dependencies=[Depends(require_admin)])
def receipt_from_vendor(
    vendor_id: int = Form(...),
    items: str = Form(...),
    extra_charges: str = Form("0"),
    notes: Optional[str] = Form(None),
    bill_photo: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
) -> dict:
    """Receive goods from a vendor (not tied to a specific PO). Auto-matches to open POs."""
    from app.models.vendor import Vendor

    vendor = db.get(Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor not found")

    try:
        raw_items = json.loads(items)
    except json.JSONDecodeError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"invalid items JSON: {e}") from e
    if not isinstance(raw_items, list) or not raw_items:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="items must be a non-empty array")

    try:
        extra = float(extra_charges or 0)
    except ValueError:
        extra = 0.0

    parsed: list[tuple[int, int, float]] = []
    for x in raw_items:
        if not isinstance(x, dict):
            continue
        try:
            cid = int(x["catalog_product_id"])
            q = int(x["quantity"])
            unit_price = float(x.get("unit_price", 0) or 0)
        except (KeyError, TypeError, ValueError):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="each item needs catalog_product_id, quantity") from None
        if q < 1:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="quantity must be >= 1")
        parsed.append((cid, q, unit_price))

    if not parsed:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="no valid items")

    # Get all open POs for this vendor (sorted oldest first for FIFO matching)
    open_pos = (
        db.query(VendorPurchaseOrder)
        .filter(
            VendorPurchaseOrder.vendor_id == vendor_id,
            VendorPurchaseOrder.status.in_(["booked", "in_progress"]),
            VendorPurchaseOrder.deleted_at.is_(None),
        )
        .order_by(VendorPurchaseOrder.created_at.asc())
        .all()
    )

    # Upload bill photo if provided
    bill_key: Optional[str] = None
    if bill_photo is not None and getattr(bill_photo, "filename", None):
        try:
            raw_bytes = bill_photo.file.read()
            if raw_bytes and storage_configured():
                ext = Path(bill_photo.filename or "bill").suffix or ".jpg"
                key = f"{_PREFIX}/vendor_{vendor_id}/{uuid.uuid4().hex}{ext}"
                bill_key = upload_bytes(raw_bytes, bill_photo.content_type or "image/jpeg", key)
        except Exception as ex:
            print(f"Bill photo upload failed: {ex}")

    total_value = 0.0
    line_items_store: list[dict] = []

    for cid, qty, unit_price in parsed:
        # Add stock
        _apply_stock_delta(db, cid, qty)
        total_value += unit_price * qty
        line_items_store.append({"catalog_product_id": cid, "quantity": qty, "unit_price": unit_price})

        # FIFO matching against open POs
        remaining = qty
        for po in open_pos:
            if remaining <= 0:
                break
            po_items = po.items if isinstance(po.items, list) else []
            for po_item in po_items:
                if not isinstance(po_item, dict):
                    continue
                try:
                    po_cid = int(po_item.get("catalog_product_id", 0))
                except (TypeError, ValueError):
                    continue
                if po_cid != cid:
                    continue
                ordered = int(po_item.get("quantity", 0))
                received = _int_snap(po_item, "received_quantity")
                pending = max(0, ordered - received)
                if pending <= 0:
                    continue
                can_match = min(pending, remaining)
                po_item["received_quantity"] = received + can_match
                remaining -= can_match
                flag_modified(po, "items")
                if remaining <= 0:
                    break

    # Auto-close POs that are fully received; mark others as in_progress
    for po in open_pos:
        po_items = po.items if isinstance(po.items, list) else []
        all_done = all(
            _int_snap(it, "received_quantity") >= int(it.get("quantity", 0))
            for it in po_items
            if isinstance(it, dict) and it.get("quantity")
        )
        any_received = any(
            _int_snap(it, "received_quantity") > 0
            for it in po_items
            if isinstance(it, dict)
        )
        if all_done:
            po.status = "closed"
        elif any_received and po.status == "booked":
            po.status = "in_progress"
        db.add(po)

    # Create stock receipt record
    receipt = StockReceipt(
        vendor_id=vendor_id,
        purchase_order_id=None,
        receipt_number=f"VR-{vendor_id}-{uuid.uuid4().hex[:8].upper()}",
        contact_number=None,
        notes=(notes or "").strip() or None,
        line_items=line_items_store,
        image_key=bill_key,
        vendor_bill_no=None,
        bill_photo_key=bill_key,
        extra_charges=extra,
    )
    db.add(receipt)

    total_with_extra = total_value + extra

    db.commit()
    return {
        "ok": True,
        "vendor_id": vendor_id,
        "items_received": len(line_items_store),
        "total_value": round(total_with_extra, 2),
        "bill_photo_key": bill_key,
    }


@router.get(
    "/{catalog_product_id}/ledger",
    response_model=ProductLedgerResponse,
    dependencies=[Depends(require_admin)],
)
def get_product_ledger(
    catalog_product_id: int,
    db: Session = Depends(get_db),
) -> ProductLedgerResponse:
    p = db.get(CatalogProduct, catalog_product_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="catalog product not found")

    bal = db.get(StockBalance, catalog_product_id)
    current_stock = int(bal.quantity) if bal else 0

    # ── collect all events ───────────────────────────────────────────
    events: list[dict] = []

    # inward — stock receipts
    receipts = db.query(StockReceipt).all()
    for sr in receipts:
        line_items = sr.line_items if isinstance(sr.line_items, list) else []
        for li in line_items:
            if not isinstance(li, dict):
                continue
            if int(li.get("catalog_product_id", 0)) == catalog_product_id:
                events.append({
                    "date": sr.created_at,
                    "type": "inward",
                    "qty": int(li.get("quantity", 0)),
                    "reference": sr.receipt_number or f"SR-{sr.id}",
                    "party": None,
                })

    # outward — customer orders (confirmed / billed / shipped)
    customer_map: dict[int, str] = {}
    orders = db.query(CustomerOrder).filter(
        CustomerOrder.status.in_(["confirmed", "billed", "shipped"])
    ).all()
    for co in orders:
        items = co.items if isinstance(co.items, list) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            if int(item.get("catalog_product_id", 0)) == catalog_product_id:
                qty = int(item.get("quantity", 0))
                if co.customer_id not in customer_map:
                    cust = db.get(Customer, co.customer_id)
                    customer_map[co.customer_id] = cust.name if cust else f"Customer {co.customer_id}"
                events.append({
                    "date": co.created_at,
                    "type": "outward",
                    "qty": -qty,
                    "reference": f"ORD-{co.id}",
                    "party": customer_map[co.customer_id],
                })

    # adjustments
    adjs = db.query(StockAdjustment).filter(
        StockAdjustment.catalog_product_id == catalog_product_id
    ).all()
    for adj in adjs:
        events.append({
            "date": adj.created_at,
            "type": "adjustment",
            "qty": int(adj.quantity_delta),
            "reference": adj.note or f"ADJ-{adj.id}",
            "party": None,
        })

    # sort by date
    events.sort(key=lambda e: e["date"] if e["date"] is not None else datetime.min.replace(tzinfo=timezone.utc))

    # compute running balances
    running = 0
    for e in events:
        running += e["qty"]
        e["running_balance"] = running

    # invoice_count — any non-cancelled orders containing this product
    invoice_count = _invoice_count_for_product(db, catalog_product_id)

    # ── group into months ─────────────────────────────────────────────
    month_map: dict[tuple[int, int], list[dict]] = {}
    for e in events:
        dt: datetime = e["date"]
        key = (dt.year, dt.month)
        month_map.setdefault(key, []).append(e)

    months_out: list[LedgerMonthSummary] = []
    prev_closing = 0

    for key in sorted(month_map.keys()):
        yr, mo = key
        month_events = month_map[key]
        opening = prev_closing
        inward = sum(e["qty"] for e in month_events if e["qty"] > 0)
        outward = sum(abs(e["qty"]) for e in month_events if e["qty"] < 0)
        closing = month_events[-1]["running_balance"]
        entries = [
            LedgerEntryDetail(
                date=e["date"],
                type=e["type"],
                qty=e["qty"],
                reference=e["reference"],
                party=e["party"],
                running_balance=e["running_balance"],
            )
            for e in month_events
        ]
        months_out.append(
            LedgerMonthSummary(
                year=yr,
                month=mo,
                month_label=f"{calendar.month_abbr[mo]} {yr}",
                opening=opening,
                inward=inward,
                outward=outward,
                closing=closing,
                entries=entries,
            )
        )
        prev_closing = closing

    return ProductLedgerResponse(
        catalog_product_id=p.id,
        our_product_id=p.our_product_id,
        name=p.name,
        current_stock=current_stock,
        invoice_count=invoice_count,
        months=months_out,
    )
