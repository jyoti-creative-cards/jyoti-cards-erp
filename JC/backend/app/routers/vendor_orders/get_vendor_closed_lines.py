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

from app.routers.vendor_orders.build_detail import _build_detail
from app.routers.vendor_orders.common import _vendor_context, _vendor_contexts

@router.get("/vendor/{vendor_id}/closed", response_model=List[ClosedLineOut])
def get_vendor_closed_lines(
    vendor_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.read")),
):
    _vendor_context(db, vendor_id)
    open_rows = db.query(VendorOpenLine).filter(
        VendorOpenLine.vendor_id == vendor_id, VendorOpenLine.status == "closed"
    ).order_by(VendorOpenLine.updated_at.desc()).all()
    products: dict[int, CatalogProduct] = {}
    pids = {r.catalog_product_id for r in open_rows}
    out: list[ClosedLineOut] = []
    for row in open_rows:
        prod = db.get(CatalogProduct, row.catalog_product_id)
        out.append(
            ClosedLineOut(
                id=row.id,
                catalog_product_id=row.catalog_product_id,
                our_product_id=prod.our_product_id if prod else row.our_product_id,
                quantity=row.quantity,
                buying_price=hide_cost(str(row.buying_price), auth),
                source="open",
                closed_at=row.updated_at,
                bill_number=None,
                close_reason=row.close_reason,
            )
        )
    billed = db.query(VendorOrder).filter(
        VendorOrder.vendor_id == vendor_id, VendorOrder.bucket == "billed", VendorOrder.is_open.is_(True)
    ).first()
    if billed:
        placements = (
            db.query(VendorOrderPlacement)
            .filter(VendorOrderPlacement.vendor_order_id == billed.id, VendorOrderPlacement.closed_at.isnot(None))
            .order_by(VendorOrderPlacement.closed_at.desc())
            .all()
        )
        for p in placements:
            receipt = db.query(StockReceipt).filter(
                StockReceipt.billed_placement_id == p.id, StockReceipt.deleted_at.is_(None)
            ).first()
            plines = db.query(VendorOrderLine).filter(VendorOrderLine.placement_id == p.id).all()
            pids.update(ln.catalog_product_id for ln in plines)
            for ln in plines:
                prod = db.get(CatalogProduct, ln.catalog_product_id)
                out.append(
                    ClosedLineOut(
                        id=ln.id,
                        catalog_product_id=ln.catalog_product_id,
                        our_product_id=prod.our_product_id if prod else ln.our_product_id,
                        quantity=ln.quantity,
                        buying_price=hide_cost(str(ln.buying_price), auth),
                        source="billed",
                        closed_at=p.closed_at,
                        bill_number=receipt.bill_number if receipt else None,
                        close_reason=p.close_reason,
                        placement_id=p.id,
                    )
                )
    if pids:
        products = {row.id: row for row in db.query(CatalogProduct).filter(CatalogProduct.id.in_(pids)).all()}
    for item in out:
        prod = products.get(item.catalog_product_id)
        item.vendor_product_id = prod.vendor_product_id if prod else None
    return out

def _summaries_from_orders(db: Session, orders: list[VendorOrder]) -> list[VendorOrderSummary]:
    """Batched _summary_from_order — 3 queries total instead of 3 per order."""
    from sqlalchemy import func

    if not orders:
        return []
    order_ids = [o.id for o in orders]
    vctx = _vendor_contexts(db, {o.vendor_id for o in orders})

    placement_counts: dict[int, int] = defaultdict(int)
    for order_id, cnt in (
        db.query(VendorOrderPlacement.vendor_order_id, func.count(VendorOrderPlacement.id))
        .filter(VendorOrderPlacement.vendor_order_id.in_(order_ids))
        .group_by(VendorOrderPlacement.vendor_order_id)
        .all()
    ):
        placement_counts[int(order_id)] = int(cnt)

    lines_by_order: dict[int, list] = defaultdict(list)
    for order_id, ln in (
        db.query(VendorOrderPlacement.vendor_order_id, VendorOrderLine)
        .join(VendorOrderLine, VendorOrderLine.placement_id == VendorOrderPlacement.id)
        .filter(VendorOrderPlacement.vendor_order_id.in_(order_ids))
        .all()
    ):
        lines_by_order[int(order_id)].append(ln)

    out = []
    for order in orders:
        ctx = vctx.get(order.vendor_id)
        if ctx is None:
            continue
        vendor, city_name, label = ctx
        line_stats = lines_by_order.get(order.id, [])
        if order.bucket == "received":
            total_qty = sum(int(ln.quantity or 0) for ln in line_stats)
        else:
            total_qty = sum(ln.quantity for ln in line_stats)
        out.append(
            VendorOrderSummary(
                id=order.id,
                vendor_id=order.vendor_id,
                vendor_name=vendor.business_name,
                vendor_city=city_name,
                vendor_label=label,
                alias=vendor.alias,
                status=order.status,
                bucket=order.bucket,
                is_open=order.is_open,
                placement_count=placement_counts.get(order.id, 0),
                line_count=len(line_stats),
                total_quantity=total_qty,
                updated_at=order.updated_at,
                display_date=order.updated_at,
            )
        )
    return out

@router.get("/closeable", response_model=List[CloseableVendorItemOut])
def list_closeable_billed(
    vendor_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.read")),
):
    """Billed receipts not yet archived off the "Billed" tab. NB: VendorOrder.bucket /
    VendorOrderPlacement.status never become "billed" in the one-receipt-per-bill model
    (see _billed_summaries) — this used to source from that dead state and always
    returned empty, so "Close Billed Shipments" silently did nothing. Sources from
    StockReceipt directly instead."""
    q = db.query(StockReceipt).filter(
        StockReceipt.bill_status == "billed",
        StockReceipt.deleted_at.is_(None),
        StockReceipt.closed_at.is_(None),
    )
    if vendor_id is not None:
        q = q.filter(StockReceipt.vendor_id == vendor_id)
    receipts = q.order_by(StockReceipt.billed_at.desc()).all()
    from sqlalchemy import func

    line_counts = {
        int(rid): (cnt, qty)
        for rid, cnt, qty in (
            db.query(
                StockReceiptLine.receipt_id, func.count(StockReceiptLine.id),
                func.coalesce(func.sum(StockReceiptLine.quantity_received), 0),
            )
            .filter(StockReceiptLine.receipt_id.in_([r.id for r in receipts]))
            .group_by(StockReceiptLine.receipt_id)
            .all()
        )
    } if receipts else {}
    vctx = _vendor_contexts(db, {r.vendor_id for r in receipts})
    out: list[CloseableVendorItemOut] = []
    for r in receipts:
        ctx = vctx.get(r.vendor_id)
        if ctx is None:
            continue
        _vendor, _city_name, label = ctx
        cnt, qty = line_counts.get(r.id, (0, 0))
        out.append(
            CloseableVendorItemOut(
                id=r.id,
                item_type="receipt",
                vendor_id=r.vendor_id,
                vendor_label=label,
                bill_number=r.bill_number,
                line_count=int(cnt),
                total_qty=int(qty),
                placed_at=r.billed_at,
            )
        )
    return out

@router.get("/vendor/{vendor_id}/products", response_model=List[CatalogProductForOrder])
def list_vendor_products_for_order(
    vendor_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.read")),
):
    _vendor_context(db, vendor_id)
    products = (
        db.query(CatalogProduct)
        .filter(
            CatalogProduct.vendor_id == vendor_id,
            CatalogProduct.deleted_at.is_(None),
            CatalogProduct.is_active.is_(True),
        )
        .order_by(CatalogProduct.our_product_id.asc())
        .all()
    )
    if not products:
        return []

    product_map = {p.id: p for p in products}
    alt_rows = (
        db.query(CatalogAlternative)
        .filter(CatalogAlternative.product_id.in_(product_map.keys()))
        .all()
    )
    alts_by_product: dict[int, list[CatalogProduct]] = defaultdict(list)
    for alt in alt_rows:
        alt_prod = product_map.get(alt.alternative_product_id) or db.get(CatalogProduct, alt.alternative_product_id)
        if alt_prod and alt_prod.is_active and not alt_prod.deleted_at and alt_prod.vendor_id == vendor_id:
            alts_by_product[alt.product_id].append(alt_prod)

    out: list[CatalogProductForOrder] = []
    for p in products:
        out.append(
            CatalogProductForOrder(
                id=p.id,
                our_product_id=p.our_product_id,
                vendor_product_id=p.vendor_product_id,
                buying_price=hide_cost(str(p.buying_price), auth),
                unit=p.unit,
                image_urls=[],
                alternatives=[
                    {
                        "catalog_product_id": a.id,
                        "our_product_id": a.our_product_id,
                        "buying_price": hide_cost(str(a.buying_price), auth),
                    }
                    for a in sorted(alts_by_product.get(p.id, []), key=lambda x: x.our_product_id.lower())
                ],
            )
        )
    return out

def _summary_from_order(db: Session, order: VendorOrder) -> VendorOrderSummary:
    vendor, city_name, label = _vendor_context(db, order.vendor_id, require_active=False)
    placement_count = (
        db.query(VendorOrderPlacement).filter(VendorOrderPlacement.vendor_order_id == order.id).count()
    )
    line_stats = (
        db.query(VendorOrderLine)
        .join(VendorOrderPlacement, VendorOrderLine.placement_id == VendorOrderPlacement.id)
        .filter(VendorOrderPlacement.vendor_order_id == order.id)
        .all()
    )
    if order.bucket == "received":
        total_qty = sum(int(ln.quantity_remaining or 0) for ln in line_stats)
        # Hub shows total received qty; keep sum of quantity for aggregate card
        total_qty = sum(int(ln.quantity or 0) for ln in line_stats)
    else:
        total_qty = sum(ln.quantity for ln in line_stats)
    return VendorOrderSummary(
        id=order.id,
        vendor_id=order.vendor_id,
        vendor_name=vendor.business_name,
        vendor_city=city_name,
        vendor_label=label,
        alias=vendor.alias,
        status=order.status,
        bucket=order.bucket,
        is_open=order.is_open,
        placement_count=placement_count,
        line_count=len(line_stats),
        total_quantity=total_qty,
        updated_at=order.updated_at,
        display_date=order.updated_at,
    )

@router.post("/placements/{placement_id}/close")
def close_billed_placement(
    placement_id: int,
    body: ReasonIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.write")),
):
    """`placement_id` is a StockReceipt id here — see build_vendor_billed_detail. This
    used to require a VendorOrder with bucket == "billed", which never exists in the
    one-receipt-per-bill model, so every call 400'd with "only billed placements can be
    closed" and the per-bill Close button inside the Billed tab's drill-down never worked."""
    from app.services.stock_receipt import build_vendor_billed_detail

    receipt = db.get(StockReceipt, placement_id)
    if not receipt or receipt.deleted_at:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="bill not found")
    if receipt.bill_status != "billed":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="only billed shipments can be closed")
    if receipt.closed_at:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="already closed")
    _vendor, _city, label = _vendor_context(db, receipt.vendor_id, require_active=False)
    reason = body.reason.strip()
    receipt.closed_at = datetime.now(timezone.utc)
    receipt.close_reason = reason
    receipt.closed_by_name = auth.actor_name
    log_from_auth(
        db, auth, action="close", entity_type="stock_receipt", entity_id=receipt.id,
        entity_label=label, detail=f"closed billed shipment #{placement_id}: {reason[:120]}",
    )
    db.commit()
    return build_vendor_billed_detail(db, receipt.vendor_id, auth)

@router.post("/close-batch")
def close_batch_placements(
    body: CloseBatchIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.write")),
):
    """Archive billed receipts off the "Billed" tab (they stay visible under "Closed").
    `placement_ids` now holds StockReceipt ids (see list_closeable_billed)."""
    closed = 0
    now = datetime.now(timezone.utc)
    reason = body.reason.strip()
    for rid in body.placement_ids:
        receipt = db.get(StockReceipt, rid)
        if not receipt or receipt.closed_at or receipt.bill_status != "billed" or receipt.deleted_at:
            continue
        vendor, _, label = _vendor_context(db, receipt.vendor_id, require_active=False)
        receipt.closed_at = now
        receipt.close_reason = reason
        receipt.closed_by_name = auth.actor_name
        log_from_auth(
            db, auth, action="close", entity_type="stock_receipt", entity_id=receipt.id,
            entity_label=label, detail=f"batch closed receipt #{rid}: {reason[:120]}",
        )
        closed += 1
    db.commit()
    return {"ok": True, "closed": closed}

@router.delete("/lines/{line_id}", response_model=VendorOrderDetail)
def delete_line(
    line_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.write")),
):
    line = db.get(VendorOrderLine, line_id)
    if not line:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="line not found")
    placement = db.get(VendorOrderPlacement, line.placement_id)
    if not placement or placement.status != "placed":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="can only delete lines from placed placements")
    order = db.get(VendorOrder, placement.vendor_order_id)
    if not order or not order.is_open or order.bucket != "placed":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="order is closed")
    _, _, label = _vendor_context(db, order.vendor_id)
    detail = f"removed line #{line_id}: {line.our_product_id} x{line.quantity}"
    if int(line.quantity or 0) > 0:
        reduce_from_open(db, order.vendor_id, [(line.catalog_product_id, int(line.quantity))])
    db.delete(line)
    order.updated_at = datetime.now(timezone.utc)
    placement.document_key = None
    placement.cost_document_key = None
    log_from_auth(db, auth, action="delete_line", entity_type="vendor_order", entity_id=order.id, entity_label=label, detail=detail)
    db.commit()
    from app.services.doc_jobs import enqueue_vendor_placement_pdf
    enqueue_vendor_placement_pdf(placement.id)
    db.refresh(order)
    return _build_detail(db, order, auth=auth)

