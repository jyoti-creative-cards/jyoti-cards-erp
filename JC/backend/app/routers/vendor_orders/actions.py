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

from app.routers.vendor_orders.common import _placement_color_map, _vendor_context, _vendor_contexts

def _to_bill_summaries(
    db: Session, *, day_start: datetime | None = None, day_end: datetime | None = None,
    only_vendor_ids: set[int] | None = None,
) -> list["VendorOrderSummary"]:
    """Vendors with a StockReceipt still pending_bill (one-to-one receive→bill model).

    `VendorOrder.bucket` never transitions to "received"/"billed" anywhere in the
    codebase — those legacy bucket values are dead. This is the real source of truth
    for the "To bill" queue.
    """
    from sqlalchemy import func

    q = (
        db.query(
            StockReceipt.vendor_id,
            func.count(func.distinct(StockReceipt.id)),
            func.count(StockReceiptLine.id),
            func.coalesce(func.sum(StockReceiptLine.quantity_received), 0),
        )
        .join(StockReceiptLine, StockReceiptLine.receipt_id == StockReceipt.id)
        .filter(StockReceipt.bill_status == "pending_bill", StockReceipt.deleted_at.is_(None))
    )
    if day_start is not None and day_end is not None:
        q = q.filter(StockReceipt.received_at >= day_start, StockReceipt.received_at < day_end)
    if only_vendor_ids is not None:
        q = q.filter(StockReceipt.vendor_id.in_(only_vendor_ids)) if only_vendor_ids else q.filter(False)
    rows = q.group_by(StockReceipt.vendor_id).all()
    vctx = _vendor_contexts(db, {int(vendor_id) for vendor_id, _, _, _ in rows})
    out: list[VendorOrderSummary] = []
    for vendor_id, receipt_count, line_count, total_qty in rows:
        vid = int(vendor_id)
        ctx = vctx.get(vid)
        if ctx is None:
            continue
        vendor, city_name, label = ctx
        latest = (
            db.query(func.max(StockReceipt.received_at))
            .filter(
                StockReceipt.vendor_id == vid,
                StockReceipt.bill_status == "pending_bill",
                StockReceipt.deleted_at.is_(None),
            )
            .scalar()
        )
        out.append(
            VendorOrderSummary(
                id=0,
                vendor_id=vid,
                vendor_name=vendor.business_name,
                vendor_city=city_name,
                vendor_label=label,
                alias=vendor.alias,
                status="to_bill",
                bucket="open",
                is_open=True,
                placement_count=int(receipt_count),
                line_count=int(line_count),
                total_quantity=int(total_qty or 0),
                updated_at=latest or datetime.now(timezone.utc),
                display_date=latest or datetime.now(timezone.utc),
                open_kind="to_bill",
            )
        )
    out.sort(key=lambda x: _sort_dt(x.display_date), reverse=True)
    return out

def _billed_summaries(
    db: Session, *, day_start: datetime | None = None, day_end: datetime | None = None,
) -> list["VendorOrderSummary"]:
    """Billed vendors for the 'Billed' past-browse stage. Same dead-VendorOrder-bucket
    issue as _to_bill_summaries — bucket never becomes "billed" either — so this sources
    straight from StockReceipt.bill_status == 'billed' (mirrors the closed-bucket query)."""
    from sqlalchemy import func

    q = (
        db.query(
            StockReceipt.vendor_id,
            func.count(func.distinct(StockReceipt.id)),
            func.count(StockReceiptLine.id),
            func.coalesce(func.sum(StockReceiptLine.quantity_received), 0),
            func.max(StockReceipt.billed_at),
        )
        .join(StockReceiptLine, StockReceiptLine.receipt_id == StockReceipt.id)
        .filter(
            StockReceipt.bill_status == "billed",
            StockReceipt.deleted_at.is_(None),
            StockReceipt.closed_at.is_(None),
        )
    )
    if day_start is not None and day_end is not None:
        q = q.filter(StockReceipt.billed_at >= day_start, StockReceipt.billed_at < day_end)
    rows = q.group_by(StockReceipt.vendor_id).all()
    vctx = _vendor_contexts(db, {int(vendor_id) for vendor_id, _, _, _, _ in rows})
    out: list[VendorOrderSummary] = []
    for vendor_id, receipt_count, line_count, total_qty, latest in rows:
        vid = int(vendor_id)
        ctx = vctx.get(vid)
        if ctx is None:
            continue
        vendor, city_name, label = ctx
        out.append(
            VendorOrderSummary(
                id=0,
                vendor_id=vid,
                vendor_name=vendor.business_name,
                vendor_city=city_name,
                vendor_label=label,
                alias=vendor.alias,
                status="billed",
                bucket="billed",
                is_open=True,
                placement_count=int(receipt_count),
                line_count=int(line_count),
                total_quantity=int(total_qty or 0),
                updated_at=latest or datetime.now(timezone.utc),
                display_date=latest or datetime.now(timezone.utc),
            )
        )
    out.sort(key=lambda x: _sort_dt(x.display_date), reverse=True)
    return out

def _sort_dt(value: datetime | None) -> datetime:
    if value is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

@router.get("/vendor/{vendor_id}/order-summary/{catalog_product_id}", response_model=OrderSummaryDrillDown)
def get_order_summary_drill(
    vendor_id: int,
    catalog_product_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.read")),
):
    vendor, _, label = _vendor_context(db, vendor_id)
    prod = db.get(CatalogProduct, catalog_product_id)
    if not prod or prod.vendor_id != vendor_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="product not found for vendor")

    events: list[OrderSummaryEvent] = []
    for bucket in ("placed", "cancelled"):
        order = (
            db.query(VendorOrder)
            .filter(VendorOrder.vendor_id == vendor_id, VendorOrder.bucket == bucket, VendorOrder.is_open.is_(True))
            .first()
        )
        if not order:
            continue
        placements = (
            db.query(VendorOrderPlacement)
            .filter(VendorOrderPlacement.vendor_order_id == order.id)
            .order_by(VendorOrderPlacement.placed_at.asc(), VendorOrderPlacement.id.asc())
            .all()
        )
        color_map = _placement_color_map(placements)
        event_type = "placed" if bucket == "placed" else "cancelled"
        for p in placements:
            plines = (
                db.query(VendorOrderLine)
                .filter(VendorOrderLine.placement_id == p.id, VendorOrderLine.catalog_product_id == catalog_product_id)
                .all()
            )
            for ln in plines:
                events.append(
                    OrderSummaryEvent(
                        event_type=event_type,
                        quantity=ln.quantity,
                        quantity_billed=ln.quantity_billed,
                        billed_amount=format(ln.billed_amount, "f") if ln.billed_amount is not None else None,
                        occurred_at=p.placed_at,
                        actor_name=p.placed_by_name,
                        bill_number=None,
                        placement_index=color_map.get(p.id),
                    )
                )

    receipt_lines = (
        db.query(StockReceiptLine, StockReceipt)
        .join(StockReceipt, StockReceiptLine.receipt_id == StockReceipt.id)
        .filter(StockReceipt.vendor_id == vendor_id, StockReceiptLine.catalog_product_id == catalog_product_id)
        .order_by(StockReceipt.received_at.asc())
        .all()
    )
    for rline, receipt in receipt_lines:
        events.append(
            OrderSummaryEvent(
                event_type="received",
                quantity=rline.quantity_received,
                quantity_billed=rline.quantity_billed,
                billed_amount=format(rline.billed_amount, "f"),
                occurred_at=receipt.received_at,
                actor_name=receipt.received_by_name,
                bill_number=receipt.bill_number,
                placement_index=None,
            )
        )

    events.sort(key=lambda e: e.occurred_at)

    for row in db.query(VendorOpenLine).filter(
        VendorOpenLine.vendor_id == vendor_id,
        VendorOpenLine.catalog_product_id == catalog_product_id,
        VendorOpenLine.status == "closed",
    ).all():
        events.append(
            OrderSummaryEvent(
                event_type="closed",
                quantity=row.quantity,
                quantity_billed=None,
                billed_amount=None,
                occurred_at=row.updated_at,
                actor_name=None,
                bill_number=None,
                placement_index=None,
            )
        )
    events.sort(key=lambda e: e.occurred_at)
    return OrderSummaryDrillDown(
        vendor_id=vendor_id,
        vendor_label=label,
        catalog_product_id=catalog_product_id,
        our_product_id=prod.our_product_id,
        events=events,
    )

@router.get("/placements/{placement_id}/document")
def get_placement_document(
    placement_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.read")),
):
    placement = db.get(VendorOrderPlacement, placement_id)
    if not placement:
        raise HTTPException(404, "placement not found")
    if storage_configured():
        try:
            # Always regenerate so PDF matches current lines (fixes stale empty PDFs)
            generate_vendor_placement_document(db, placement.id, auth)
            db.commit()
            db.refresh(placement)
        except Exception as exc:
            db.rollback()
            import logging
            logging.getLogger(__name__).exception("placement PDF generate failed for %s", placement_id)
            raise HTTPException(500, f"document generation failed: {exc}") from exc
    if not placement.document_key:
        raise HTTPException(404, "document not available")
    url = presigned_url(placement.document_key)
    if not url:
        raise HTTPException(503, "storage not available")
    return {"document_url": url, "document_key": placement.document_key}

