from __future__ import annotations
from app.routers.vendor_orders.router import router
"""Split from app/routers/vendor_orders.py."""

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import AuthContext, require_permission
from app.models.catalog_alternative import CatalogAlternative
from app.models.catalog_product import CatalogProduct
from app.models.city import City
from app.models.vendor import Vendor
from app.models.vendor_order import VendorOrder, VendorOrderLine, VendorOrderPlacement
from app.models.vendor_open_line import VendorOpenLine
from app.models.stock import StockReceipt, StockReceiptLine
from app.schemas.vendor_order import (
    AggregatedLine,
    CatalogProductForOrder,
    OrderSummaryDrillDown,
    OrderSummaryEvent,
    OrderSummaryLine,
    PlacementCreate,
    PlacementLineDetail,
    PlacementSummary,
    VendorOrderDetail,
    VendorOrderLineUpdate,
    VendorOrderSummary,
    VendorOrderSummaryDetail,
    OpenLineOut,
    OpenVendorDetail,
    ClosedLineOut,
    OpenLineUpdate,
    CloseableVendorItemOut,
    CloseBatchIn,
    ReasonIn,
)
from app.services.activity import log_from_auth
from app.services.ap_ledger import receipt_bill_amount, receipt_debit_note_total
from app.services.biz_date import ist_day_bounds_utc, today_ist
from app.services.cost_visibility import hide_cost
from app.services.open_lines import add_to_open, cancel_open_qty, close_open_line, cancel_open_line, open_lines_for_vendor, reduce_from_open
from app.services.order_summary import pending_qty_by_product, placed_qty_by_product, received_qty_by_product
from app.services.stock_receipt import get_or_create_open_order
from app.services.doc_gen import generate_vendor_placement_document
from app.services.document_present import present
from app.services.storage import presigned_url, presigned_urls, storage_configured

from app.routers.vendor_orders.common import _vendor_context

@router.get("/vendor/{vendor_id}/order-summary", response_model=VendorOrderSummaryDetail)
def get_vendor_order_summary(
    vendor_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.read")),
):
    vendor, city_name, label = _vendor_context(db, vendor_id)
    placed_map = placed_qty_by_product(db, vendor_id)
    received_map = received_qty_by_product(db, vendor_id)
    pending_map = pending_qty_by_product(db, vendor_id)

    cancelled_order = (
        db.query(VendorOrder)
        .filter(VendorOrder.vendor_id == vendor_id, VendorOrder.bucket == "cancelled", VendorOrder.is_open.is_(True))
        .first()
    )
    cancelled_map: dict[int, int] = {}
    if cancelled_order:
        from sqlalchemy import func
        rows = (
            db.query(VendorOrderLine.catalog_product_id, func.coalesce(func.sum(VendorOrderLine.quantity), 0))
            .join(VendorOrderPlacement, VendorOrderLine.placement_id == VendorOrderPlacement.id)
            .filter(VendorOrderPlacement.vendor_order_id == cancelled_order.id)
            .group_by(VendorOrderLine.catalog_product_id)
            .all()
        )
        cancelled_map = {int(cat_id): int(qty or 0) for cat_id, qty in rows}

    closed_map: dict[int, int] = {}
    for row in db.query(VendorOpenLine).filter(
        VendorOpenLine.vendor_id == vendor_id, VendorOpenLine.status == "closed"
    ).all():
        closed_map[row.catalog_product_id] = closed_map.get(row.catalog_product_id, 0) + row.quantity

    open_line_map: dict[int, int] = {}
    for row in db.query(VendorOpenLine).filter(
        VendorOpenLine.vendor_id == vendor_id, VendorOpenLine.status == "open", VendorOpenLine.quantity > 0
    ).all():
        open_line_map[row.catalog_product_id] = row.id

    all_ids = set(placed_map) | set(received_map) | set(cancelled_map) | set(closed_map)
    lines: list[OrderSummaryLine] = []
    for cat_id in sorted(all_ids):
        prod = db.get(CatalogProduct, cat_id)
        if not prod:
            continue
        lines.append(
            OrderSummaryLine(
                catalog_product_id=cat_id,
                our_product_id=prod.our_product_id,
                vendor_product_id=prod.vendor_product_id,
                total_placed=placed_map.get(cat_id, 0),
                total_received=received_map.get(cat_id, 0),
                total_pending=pending_map.get(cat_id, 0),
                total_cancelled=cancelled_map.get(cat_id, 0),
                total_closed=closed_map.get(cat_id, 0),
                buying_price=hide_cost(str(prod.buying_price), auth),
                unit=prod.unit,
                image_urls=presigned_urls(prod.image_keys or []),
                open_line_id=open_line_map.get(cat_id),
            )
        )
    lines.sort(key=lambda x: x.our_product_id.lower())
    return VendorOrderSummaryDetail(vendor_id=vendor_id, vendor_label=label, lines=lines)

@router.patch("/open-lines/{line_id}", response_model=OpenVendorDetail)
def update_open_line(
    line_id: int,
    body: OpenLineUpdate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.write")),
):
    if body.catalog_product_id is None and body.quantity is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="nothing to update")
    row = db.get(VendorOpenLine, line_id)
    if not row or row.status != "open":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="open line not found")
    vendor, _, label = _vendor_context(db, row.vendor_id)
    changes: list[str] = []
    if body.quantity is not None and body.quantity != row.quantity:
        changes.append(f"qty {row.quantity}→{body.quantity}")
        row.quantity = body.quantity
    if body.catalog_product_id is not None and body.catalog_product_id != row.catalog_product_id:
        prod = (
            db.query(CatalogProduct)
            .filter(
                CatalogProduct.id == body.catalog_product_id,
                CatalogProduct.vendor_id == row.vendor_id,
                CatalogProduct.deleted_at.is_(None),
                CatalogProduct.is_active.is_(True),
            )
            .first()
        )
        if not prod:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="product must belong to same vendor")
        changes.append(f"product {row.our_product_id}→{prod.our_product_id}")
        row.catalog_product_id = prod.id
        row.our_product_id = prod.our_product_id
        row.buying_price = prod.buying_price
    if changes:
        log_from_auth(
            db, auth, action="update_open", entity_type="vendor_order", entity_id=row.vendor_id,
            entity_label=label, detail=f"open line #{line_id}: {', '.join(changes)}",
        )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="this vendor already has an open line for that product — merge quantities into the existing line instead",
        ) from None
    return _open_vendor_detail(db, row.vendor_id, auth=auth)

def _record_cancelled_lines(
    db: Session,
    auth: AuthContext,
    vendor_id: int,
    lines: list[tuple[int, int, str, Decimal]],
    reason: str | None = None,
) -> None:
    if not lines:
        return
    cancelled_order = get_or_create_open_order(db, vendor_id, "cancelled", "cancelled")
    placement = VendorOrderPlacement(
        vendor_order_id=cancelled_order.id,
        status="cancelled",
        placed_by_type=auth.actor_type,
        placed_by_id=auth.actor_id,
        placed_by_name=auth.actor_name,
        placed_at=datetime.now(timezone.utc),
        cancel_reason=(reason or "").strip() or None,
    )
    db.add(placement)
    db.flush()
    for cat_id, qty, our_id, price in lines:
        db.add(
            VendorOrderLine(
                placement_id=placement.id,
                catalog_product_id=cat_id,
                our_product_id=our_id,
                quantity=qty,
                quantity_remaining=qty,
                buying_price=price,
            )
        )
    cancelled_order.updated_at = datetime.now(timezone.utc)

@router.post("/vendor/{vendor_id}/products/{catalog_product_id}/close-pending", response_model=VendorOrderSummaryDetail)
def close_product_pending(
    vendor_id: int,
    catalog_product_id: int,
    body: ReasonIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.write")),
):
    vendor, _, label = _vendor_context(db, vendor_id)
    prod = db.get(CatalogProduct, catalog_product_id)
    if not prod or prod.vendor_id != vendor_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="product not found for vendor")
    row = (
        db.query(VendorOpenLine)
        .filter(
            VendorOpenLine.vendor_id == vendor_id,
            VendorOpenLine.catalog_product_id == catalog_product_id,
            VendorOpenLine.status == "open",
            VendorOpenLine.quantity > 0,
        )
        .first()
    )
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="no open line for this product")
    reason = body.reason.strip()
    close_open_line(db, row.id, reason=reason)
    log_from_auth(
        db, auth, action="close", entity_type="vendor_order", entity_id=vendor_id,
        entity_label=label, detail=f"closed pending: {prod.our_product_id}×{row.quantity} — {reason[:120]}",
    )
    db.commit()
    return get_vendor_order_summary(vendor_id, db, auth)

@router.post("/vendor/{vendor_id}/products/{catalog_product_id}/cancel-pending", response_model=VendorOrderSummaryDetail)
def cancel_product_pending(
    vendor_id: int,
    catalog_product_id: int,
    body: ReasonIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.write")),
):
    vendor, _, label = _vendor_context(db, vendor_id)
    prod = db.get(CatalogProduct, catalog_product_id)
    if not prod or prod.vendor_id != vendor_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="product not found for vendor")
    pending = pending_qty_by_product(db, vendor_id).get(catalog_product_id, 0)
    if pending <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="nothing pending for this product")
    reason = body.reason.strip()
    _record_cancelled_lines(
        db, auth, vendor_id,
        [(catalog_product_id, pending, prod.our_product_id, prod.buying_price)],
        reason=reason,
    )
    cancel_open_qty(db, vendor_id, [(catalog_product_id, pending)], reason=reason)
    log_from_auth(
        db, auth, action="cancel", entity_type="vendor_order", entity_id=vendor_id,
        entity_label=label, detail=f"cancelled pending: {prod.our_product_id}×{pending} — {reason[:120]}",
    )
    db.commit()
    return get_vendor_order_summary(vendor_id, db, auth)

@router.post("/open-lines/{line_id}/cancel", response_model=OpenVendorDetail)
def cancel_open_line_endpoint(
    line_id: int,
    body: ReasonIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.write")),
):
    row = db.get(VendorOpenLine, line_id)
    if not row or row.status != "open":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="open line not found")
    vendor, _, label = _vendor_context(db, row.vendor_id)
    qty = row.quantity
    reason = body.reason.strip()
    _record_cancelled_lines(
        db, auth, row.vendor_id,
        [(row.catalog_product_id, qty, row.our_product_id, row.buying_price)],
        reason=reason,
    )
    cancel_open_line(db, line_id, reason=reason)
    log_from_auth(
        db, auth, action="cancel", entity_type="vendor_order", entity_id=row.vendor_id,
        entity_label=label, detail=f"cancelled open line: {row.our_product_id}×{qty} — {reason[:120]}",
    )
    db.commit()
    return _open_vendor_detail(db, row.vendor_id, auth=auth)

@router.post("/open-lines/{line_id}/close", response_model=OpenVendorDetail)
def close_open_line_endpoint(
    line_id: int,
    body: ReasonIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.write")),
):
    row = db.get(VendorOpenLine, line_id)
    if not row or row.status != "open":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="open line not found")
    vendor, _, label = _vendor_context(db, row.vendor_id)
    reason = body.reason.strip()
    close_open_line(db, line_id, reason=reason)
    log_from_auth(
        db, auth, action="close", entity_type="vendor_order", entity_id=row.vendor_id,
        entity_label=label, detail=f"closed open line: {row.our_product_id}×{row.quantity} — {reason[:120]}",
    )
    db.commit()
    return _open_vendor_detail(db, row.vendor_id, auth=auth)

def _open_line_out(db: Session, row: VendorOpenLine, *, auth: AuthContext) -> OpenLineOut:
    prod = db.get(CatalogProduct, row.catalog_product_id)
    return OpenLineOut(
        id=row.id,
        catalog_product_id=row.catalog_product_id,
        our_product_id=prod.our_product_id if prod else row.our_product_id,
        vendor_product_id=prod.vendor_product_id if prod else None,
        quantity=row.quantity,
        buying_price=hide_cost(str(row.buying_price), auth),
        unit=prod.unit if prod else None,
        image_urls=presigned_urls(prod.image_keys or []) if prod else [],
        marking=prod.marking if prod else None,
        status=row.status,
    )

def _open_vendor_detail(db: Session, vendor_id: int, *, auth: AuthContext) -> OpenVendorDetail:
    _, _, label = _vendor_context(db, vendor_id)
    lines = open_lines_for_vendor(db, vendor_id, status="open")
    lines = [ln for ln in lines if ln.quantity > 0]
    return OpenVendorDetail(
        vendor_id=vendor_id,
        vendor_label=label,
        lines=[_open_line_out(db, ln, auth=auth) for ln in lines],
    )

@router.get("/vendor/{vendor_id}/open", response_model=OpenVendorDetail)
def get_vendor_open_order(
    vendor_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.read")),
):
    return _open_vendor_detail(db, vendor_id, auth=auth)

