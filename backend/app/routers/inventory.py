from __future__ import annotations

import calendar
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
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
from app.models.vendor_order import VendorOrder as VendorOrderModel
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


def _vendor_order_count_for_product(db: Session, catalog_product_id: int) -> int:
    """Count vendor orders that include this product (any status)."""
    try:
        dialect = db.bind.dialect.name  # type: ignore[union-attr]
    except Exception:
        dialect = "postgresql"
    if dialect == "postgresql":
        sql = text(
            "SELECT COUNT(*) FROM portal_vendor_orders "
            "WHERE items::jsonb @> (:filter)::jsonb"
        )
        row = db.execute(sql, {"filter": json.dumps([{"catalog_product_id": catalog_product_id}])}).scalar()
        return int(row or 0)
    count = 0
    vorders = db.query(VendorOrderModel).all()
    for vo in vorders:
        items = vo.items if isinstance(vo.items, list) else []
        if any(isinstance(i, dict) and i.get("catalog_product_id") == catalog_product_id for i in items):
            count += 1
    return count


def _inventory_row_public(
    db: Session,
    p: CatalogProduct,
    bal: Optional[StockBalance],
    invoice_count: int = 0,
    vendor_order_count: int = 0,
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
        vendor_order_count=vendor_order_count,
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

    # ── bulk-fetch counts once (avoids N+1) ─────────────────────────────
    try:
        dialect = db.bind.dialect.name  # type: ignore[union-attr]
    except Exception:
        dialect = "postgresql"

    if dialect == "postgresql":
        inv_rows = db.execute(text(
            "SELECT items_elem->>'catalog_product_id' AS pid, COUNT(*) AS cnt "
            "FROM portal_customer_orders, jsonb_array_elements(items::jsonb) AS items_elem "
            "WHERE status != 'cancelled' GROUP BY 1"
        )).fetchall()
        invoice_counts: dict[int, int] = {int(r[0]): int(r[1]) for r in inv_rows if r[0]}

        vo_rows = db.execute(text(
            "SELECT items_elem->>'catalog_product_id' AS pid, COUNT(*) AS cnt "
            "FROM portal_vendor_orders, jsonb_array_elements(items::jsonb) AS items_elem "
            "GROUP BY 1"
        )).fetchall()
        vo_counts: dict[int, int] = {int(r[0]): int(r[1]) for r in vo_rows if r[0]}
    else:
        # sqlite fallback — scan in Python
        invoice_counts = {}
        for co in db.query(CustomerOrder).filter(CustomerOrder.status != "cancelled").all():
            for item in (co.items if isinstance(co.items, list) else []):
                if isinstance(item, dict) and item.get("catalog_product_id"):
                    pid = int(item["catalog_product_id"])
                    invoice_counts[pid] = invoice_counts.get(pid, 0) + 1
        vo_counts = {}
        for vo in db.query(VendorOrderModel).all():
            for item in (vo.items if isinstance(vo.items, list) else []):
                if isinstance(item, dict) and item.get("catalog_product_id"):
                    pid = int(item["catalog_product_id"])
                    vo_counts[pid] = vo_counts.get(pid, 0) + 1

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
            inv_cnt = invoice_counts.get(p.id, 0)
            vo_cnt = vo_counts.get(p.id, 0)
            row = _inventory_row_public(db, p, bal, invoice_count=inv_cnt, vendor_order_count=vo_cnt)
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
    # preload all products to avoid N+1 db.get() per row
    all_products: dict[int, CatalogProduct] = {p.id: p for p in db.query(CatalogProduct).all()}
    for bal in q_bal.order_by(CatalogProduct.our_product_id.asc()).all():
        p = all_products.get(bal.catalog_product_id)
        if p is None:
            continue
        inv_cnt = invoice_counts.get(p.id, 0)
        vo_cnt = vo_counts.get(p.id, 0)
        row = _inventory_row_public(db, p, bal, invoice_count=inv_cnt, vendor_order_count=vo_cnt)
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
    try:
        from app.services.audit import log_action
        sign = "+" if body.quantity_delta > 0 else ""
        log_action(db, action="adjust_stock", entity_type="stock_adjustment", entity_id=adj.id,
                   description=f"Stock adjustment for '{p.our_product_id}': {sign}{body.quantity_delta} units. Note: {adj.note or 'none'}",
                   performed_by="admin")
        db.commit()
    except Exception as ex:
        db.rollback(); print(f"Audit log failed: {ex}")
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


class AdhocReceiptItem(BaseModel):
    catalog_product_id: int
    quantity: int
    unit_price: Optional[float] = None


class AdhocReceiptBody(BaseModel):
    vendor_id: int
    items: List[AdhocReceiptItem]
    notes: Optional[str] = None


@router.post("/receipts/adhoc", response_model=dict, dependencies=[Depends(require_admin)],
             status_code=status.HTTP_201_CREATED)
def adhoc_receipt(body: AdhocReceiptBody, db: Session = Depends(get_db)) -> dict:
    """Add stock immediately and record against the vendor's open VendorOrder (or create one)."""
    from app.models.vendor import Vendor
    from app.models.stock_receipt import StockReceipt
    from app.services.audit import log_action

    vendor = db.get(Vendor, body.vendor_id)
    if vendor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor not found")
    if not body.items:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="at least one item required")

    # Validate all products belong to this vendor
    for item in body.items:
        p = db.get(CatalogProduct, item.catalog_product_id)
        if p is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"product {item.catalog_product_id} not found")
        if p.vendor_id != body.vendor_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"product {p.our_product_id} does not belong to this vendor")
        if item.quantity < 1:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="quantity must be >= 1")

    # Get or create the vendor's open VendorOrder
    import uuid as _uuid
    vo = db.query(VendorOrderModel).filter(
        VendorOrderModel.vendor_id == body.vendor_id,
        VendorOrderModel.status == "open",
    ).first()

    now_iso = datetime.now(timezone.utc).isoformat()
    new_lines = []
    for item in body.items:
        p = db.get(CatalogProduct, item.catalog_product_id)
        new_lines.append({
            "line_id": str(_uuid.uuid4()),
            "catalog_product_id": item.catalog_product_id,
            "product_name": p.our_product_id if p else str(item.catalog_product_id),
            "qty_ordered": item.quantity,
            "qty_received": item.quantity,
            "unit_price": float(item.unit_price or 0),
            "date_ordered": now_iso,
            "date_received": now_iso,
            "notes": (body.notes or "").strip() or "Ad-hoc manual stock entry",
        })

    if vo is None:
        vo = VendorOrderModel(
            vendor_id=body.vendor_id,
            status="closed",
            notes=(body.notes or "").strip() or "Ad-hoc manual stock entry",
            items=new_lines,
        )
        db.add(vo)
    else:
        existing = vo.items if isinstance(vo.items, list) else []
        existing.extend(new_lines)
        vo.items = existing
        from sqlalchemy.orm.attributes import flag_modified as _flag_modified
        _flag_modified(vo, "items")
        # Auto-close if all items (including newly appended ones) are fully received
        from app.routers.vendor_orders import _pending as _vp
        if all(_vp(it) == 0 for it in vo.items if isinstance(it, dict)):
            vo.status = "closed"

    db.flush()

    # Add stock delta for each item + build single receipt
    line_items_json = []
    for item in body.items:
        _apply_stock_delta(db, item.catalog_product_id, item.quantity)
        p = db.get(CatalogProduct, item.catalog_product_id)
        line_items_json.append({
            "catalog_product_id": item.catalog_product_id,
            "our_product_id": p.our_product_id if p else str(item.catalog_product_id),
            "quantity_received": item.quantity,
            "unit_price": float(item.unit_price or 0),
        })

    sr = StockReceipt(
        purchase_order_id=None,
        vendor_id=body.vendor_id,
        line_items=line_items_json,
        note=(body.notes or "").strip() or "Ad-hoc manual stock entry",
        is_partial=False,
    )
    db.add(sr)
    db.commit()

    try:
        names = []
        for item in body.items:
            p = db.get(CatalogProduct, item.catalog_product_id)
            names.append(f"{p.our_product_id if p else item.catalog_product_id} x{item.quantity}")
        log_action(
            db,
            action="create",
            entity_type="adhoc_receipt",
            entity_id=vo.id,
            description=f"Ad-hoc stock entry VO#{vo.id} for vendor '{vendor.company_name or vendor.person_name}': {', '.join(names)}",
            performed_by="admin",
        )
        db.commit()
    except Exception as ex:
        db.rollback()
        print(f"Audit log failed: {ex}")

    return {"ok": True, "vendor_order_id": vo.id, "items_received": len(body.items)}


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

    # inward — stock receipts (from purchase orders)
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

    # inward — vendor order receipts (received goods via vendor orders)
    vendor_orders = db.query(VendorOrderModel).all()
    for vo in vendor_orders:
        items = vo.items if isinstance(vo.items, list) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            if int(item.get("catalog_product_id", 0)) == catalog_product_id:
                qty_recv = int(item.get("qty_received", 0))
                if qty_recv > 0:
                    date_recv = item.get("date_received")
                    try:
                        from datetime import datetime as _dt, timezone as _tz
                        evt_date = _dt.fromisoformat(date_recv.replace("Z", "+00:00")) if date_recv else vo.updated_at
                    except Exception:
                        evt_date = vo.updated_at
                    events.append({
                        "date": evt_date,
                        "type": "inward",
                        "qty": qty_recv,
                        "reference": f"VO-{vo.id}",
                        "party": None,
                    })

    # outward — customer orders (all non-cancelled, non-pending)
    customer_map: dict[int, str] = {}
    orders = db.query(CustomerOrder).filter(
        CustomerOrder.status.notin_(["cancelled", "pending"])
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
