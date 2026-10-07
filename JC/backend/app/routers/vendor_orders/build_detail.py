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

from app.routers.vendor_orders.common import _placement_color_map, _vendor_context

def _build_detail(db: Session, order: VendorOrder, *, auth: AuthContext, open_only: bool = False) -> VendorOrderDetail:
    vendor, city_name, label = _vendor_context(db, order.vendor_id, require_active=False)
    placements = (
        db.query(VendorOrderPlacement)
        .filter(VendorOrderPlacement.vendor_order_id == order.id)
        .order_by(VendorOrderPlacement.placed_at.asc(), VendorOrderPlacement.id.asc())
        .all()
    )
    color_map = _placement_color_map(placements)
    placement_summaries: list[PlacementSummary] = []
    lines_by_placement: dict[int, list[VendorOrderLine]] = defaultdict(list)
    all_lines: list[VendorOrderLine] = []

    for p in placements:
        plines = (
            db.query(VendorOrderLine)
            .filter(VendorOrderLine.placement_id == p.id)
            .order_by(VendorOrderLine.id.asc())
            .all()
        )
        lines_by_placement[p.id] = plines
        all_lines.extend(plines)
        receipt = None
        if order.bucket == "billed":
            receipt = db.query(StockReceipt).filter(
                StockReceipt.billed_placement_id == p.id, StockReceipt.deleted_at.is_(None)
            ).first()
        elif order.bucket == "received":
            receipt = db.query(StockReceipt).filter(
                StockReceipt.received_placement_id == p.id, StockReceipt.deleted_at.is_(None)
            ).first()
        bill_amt = dn_total = net = bill_file = None
        if receipt:
            if order.bucket == "billed":
                ba = receipt_bill_amount(db, receipt.id)
                dn = receipt_debit_note_total(db, receipt.id)
                bill_amt = format(ba, "f")
                dn_total = format(dn, "f")
                net = format(ba + dn, "f")
            bill_file = presigned_url(receipt.bill_file_key) if receipt.bill_file_key else None
        if receipt and order.bucket == "billed":
            view = present(db, "vendor_bill", receipt)
        elif receipt:
            view = present(db, "vendor_receipt", receipt)
        else:
            view = present(db, "vendor_order", p)
        placement_summaries.append(
            PlacementSummary(
                id=p.id,
                status=view.get("status") or p.status,
                placed_at=p.placed_at,
                display_date=view.get("display_date") or p.placed_at,
                display_name=view.get("display_name"),
                placed_by_name=p.placed_by_name,
                placed_by_type=p.placed_by_type,
                color_index=color_map[p.id],
                line_count=len(plines),
                total_quantity=sum(ln.quantity for ln in plines),
                receipt_id=receipt.id if receipt else None,
                bill_number=receipt.bill_number if receipt else None,
                order_receipt_number=(receipt.order_receipt_number if receipt else None),
                notes=(receipt.notes if receipt else None),
                bill_file_url=bill_file,
                closed_at=p.closed_at,
                cancel_reason=p.cancel_reason,
                close_reason=p.close_reason,
                bill_amount=bill_amt,
                debit_note_total=dn_total,
                net_payable=net,
            )
        )

    product_ids = {ln.catalog_product_id for ln in all_lines}
    products = {}
    if product_ids:
        for row in db.query(CatalogProduct).filter(CatalogProduct.id.in_(product_ids)).all():
            products[row.id] = row

    received_map = received_qty_by_product(db, order.vendor_id) if order.bucket == "placed" else {}
    placed_map = placed_qty_by_product(db, order.vendor_id) if order.bucket == "placed" else {}
    pending_map = pending_qty_by_product(db, order.vendor_id) if order.bucket == "placed" else {}

    agg: dict[int, dict] = {}
    for p in placements:
        for ln in lines_by_placement[p.id]:
            prod = products.get(ln.catalog_product_id)
            entry = agg.setdefault(
                ln.catalog_product_id,
                {
                    "catalog_product_id": ln.catalog_product_id,
                    "our_product_id": prod.our_product_id if prod else ln.our_product_id,
                    "vendor_product_id": prod.vendor_product_id if prod else None,
                    "total_quantity": 0,
                    "total_placed": 0,
                    "total_received": 0,
                    "total_pending": 0,
                    "buying_price": hide_cost(str(ln.buying_price), auth),
                    "unit": prod.unit if prod else None,
                    "image_urls": presigned_urls(prod.image_keys or []) if prod else [],
                    "marking": prod.marking if prod else None,
                    "breakdown": [],
                },
            )
            qty = ln.quantity
            entry["total_quantity"] += qty
            entry["breakdown"].append(
                PlacementLineDetail(
                    line_id=ln.id,
                    placement_id=p.id,
                    catalog_product_id=ln.catalog_product_id,
                    our_product_id=prod.our_product_id if prod else ln.our_product_id,
                    vendor_product_id=prod.vendor_product_id if prod else None,
                    quantity=qty,
                    quantity_remaining=ln.quantity_remaining,
                    quantity_billed=ln.quantity_billed,
                    billed_amount=format(ln.billed_amount, "f") if ln.billed_amount is not None else None,
                    buying_price=hide_cost(str(ln.buying_price), auth),
                    placed_at=p.placed_at,
                    placed_by_name=p.placed_by_name,
                    placed_by_type=p.placed_by_type,
                    placement_color_index=color_map[p.id],
                )
            )

    aggregated_lines = []
    for v in sorted(agg.values(), key=lambda x: x["our_product_id"].lower()):
        if order.bucket == "placed":
            pid = v["catalog_product_id"]
            v["total_placed"] = placed_map.get(pid, v["total_quantity"])
            v["total_received"] = received_map.get(pid, 0)
            v["total_pending"] = pending_map.get(pid, 0)
            v["total_quantity"] = v["total_placed"]
            if open_only and v["total_pending"] <= 0:
                continue
        elif order.bucket == "received":
            v["total_received"] = v["total_quantity"]
            v["total_pending"] = sum(
                int(ln.quantity_remaining or 0)
                for ln in all_lines
                if ln.catalog_product_id == v["catalog_product_id"]
            )
        elif order.bucket == "billed":
            v["total_received"] = v["total_quantity"]
        aggregated_lines.append(AggregatedLine(**v))

    return VendorOrderDetail(
        id=order.id,
        vendor_id=order.vendor_id,
        vendor_name=vendor.business_name,
        vendor_city=city_name,
        vendor_label=label,
        alias=vendor.alias,
        status=order.status,
        bucket=order.bucket,
        is_open=order.is_open,
        created_at=order.created_at,
        updated_at=order.updated_at,
        placements=placement_summaries,
        aggregated_lines=aggregated_lines,
    )

@router.patch("/lines/{line_id}", response_model=VendorOrderDetail)
def update_line(
    line_id: int,
    body: VendorOrderLineUpdate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.write")),
):
    if body.catalog_product_id is None and body.quantity is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="nothing to update")

    line = db.get(VendorOrderLine, line_id)
    if not line:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="line not found")

    placement = db.get(VendorOrderPlacement, line.placement_id)
    if not placement or placement.status != "placed":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="can only edit placed placements")

    order = db.get(VendorOrder, placement.vendor_order_id)
    if not order or not order.is_open or order.bucket != "placed":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="order is closed or not placed")

    vendor, _, label = _vendor_context(db, order.vendor_id)
    changes: list[str] = []
    before_snap = {
        "line_id": line.id,
        "catalog_product_id": line.catalog_product_id,
        "our_product_id": line.our_product_id,
        "quantity": line.quantity,
        "placement_id": placement.id,
    }
    old_pid = line.catalog_product_id
    old_qty = int(line.quantity or 0)

    if body.quantity is not None and body.quantity != line.quantity:
        changes.append(f"qty {line.quantity}→{body.quantity}")
        line.quantity = body.quantity
        line.quantity_remaining = body.quantity

    if body.catalog_product_id is not None and body.catalog_product_id != line.catalog_product_id:
        prod = (
            db.query(CatalogProduct)
            .filter(
                CatalogProduct.id == body.catalog_product_id,
                CatalogProduct.vendor_id == order.vendor_id,
                CatalogProduct.deleted_at.is_(None),
                CatalogProduct.is_active.is_(True),
            )
            .first()
        )
        if not prod:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="product must belong to same vendor")
        changes.append(f"product {line.our_product_id}→{prod.our_product_id}")
        line.catalog_product_id = prod.id
        line.our_product_id = prod.our_product_id
        line.buying_price = prod.buying_price

    if not changes:
        return _build_detail(db, order, auth=auth)

    # Keep Open pending in sync with placed line edits
    new_pid = line.catalog_product_id
    new_qty = int(line.quantity or 0)
    if old_pid != new_pid:
        if old_qty > 0:
            reduce_from_open(db, order.vendor_id, [(old_pid, old_qty)])
        if new_qty > 0:
            add_to_open(db, order.vendor_id, [(new_pid, new_qty)])
    elif new_qty != old_qty:
        delta = new_qty - old_qty
        if delta > 0:
            add_to_open(db, order.vendor_id, [(new_pid, delta)])
        elif delta < 0:
            reduce_from_open(db, order.vendor_id, [(new_pid, -delta)])

    from app.services.history import record_entity_history

    summary = f"placed line #{line_id}: {', '.join(changes)}"
    record_entity_history(db, "vendor_order_line", line.id, before_snap, summary)
    order.updated_at = datetime.now(timezone.utc)
    log_from_auth(
        db,
        auth,
        action="update_line",
        entity_type="vendor_order",
        entity_id=order.id,
        entity_label=label,
        detail=summary,
    )
    placement.document_key = None
    placement.cost_document_key = None
    db.commit()
    from app.services.doc_jobs import enqueue_vendor_placement_pdf
    enqueue_vendor_placement_pdf(placement.id)
    db.refresh(order)
    return _build_detail(db, order, auth=auth)

@router.post("/placements", response_model=VendorOrderDetail, status_code=status.HTTP_201_CREATED)
def create_placement(
    body: PlacementCreate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.write")),
):
    vendor, _, label = _vendor_context(db, body.vendor_id)
    if not body.lines:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="at least one line required")

    product_ids = [ln.catalog_product_id for ln in body.lines]
    products = (
        db.query(CatalogProduct)
        .filter(
            CatalogProduct.id.in_(product_ids),
            CatalogProduct.vendor_id == body.vendor_id,
            CatalogProduct.deleted_at.is_(None),
            CatalogProduct.is_active.is_(True),
        )
        .all()
    )
    product_map = {p.id: p for p in products}
    missing = [pid for pid in product_ids if pid not in product_map]
    if missing:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"invalid catalog products for vendor: {missing}")

    from app.services.biz_date import resolve_biz_dt

    when = resolve_biz_dt(body.placed_on)
    order = get_or_create_open_order(db, body.vendor_id, "placed", "placed")
    placement = VendorOrderPlacement(
        vendor_order_id=order.id,
        status="placed",
        placed_by_type=auth.actor_type,
        placed_by_id=auth.actor_id,
        placed_by_name=auth.actor_name,
        placed_at=when,
    )
    db.add(placement)
    db.flush()

    for ln in body.lines:
        prod = product_map[ln.catalog_product_id]
        db.add(
            VendorOrderLine(
                placement_id=placement.id,
                catalog_product_id=prod.id,
                our_product_id=prod.our_product_id,
                quantity=ln.quantity,
                quantity_remaining=ln.quantity,
                buying_price=prod.buying_price,
            )
        )

    order.updated_at = when
    add_to_open(db, body.vendor_id, [(ln.catalog_product_id, ln.quantity) for ln in body.lines], as_of=when)
    line_summary = ", ".join(f"{product_map[ln.catalog_product_id].our_product_id}×{ln.quantity}" for ln in body.lines)
    log_from_auth(
        db,
        auth,
        action="place",
        entity_type="vendor_order",
        entity_id=order.id,
        entity_label=label,
        detail=f"placement #{placement.id}: {line_summary}",
    )
    # PDF is built after the save, so Place does not wait on photos.
    db.commit()
    from app.services.doc_jobs import enqueue_vendor_placement_pdf
    enqueue_vendor_placement_pdf(placement.id)
    db.refresh(order)
    return _build_detail(db, order, auth=auth)

@router.post("/placements/{placement_id}/cancel", response_model=VendorOrderDetail)
def cancel_placement(
    placement_id: int,
    body: ReasonIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.write")),
):
    """Cancel a placed drop: copy into Cancelled with note; leave Placed qty untouched; clear Open."""
    placement = db.get(VendorOrderPlacement, placement_id)
    if not placement:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="placement not found")
    if placement.status != "placed":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="only placed placements can be cancelled")
    if placement.cancel_reason:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="placement already cancelled")

    order = db.get(VendorOrder, placement.vendor_order_id)
    if not order or order.bucket != "placed" or not order.is_open:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="cannot cancel — order not open placed")

    lines = db.query(VendorOrderLine).filter(VendorOrderLine.placement_id == placement.id).all()
    if not lines:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="placement has no lines")

    vendor, _, label = _vendor_context(db, order.vendor_id)
    reason = body.reason.strip()
    cancelled_order = get_or_create_open_order(db, order.vendor_id, "cancelled", "cancelled")
    now = datetime.now(timezone.utc)
    new_placement = VendorOrderPlacement(
        vendor_order_id=cancelled_order.id,
        status="cancelled",
        placed_by_type=placement.placed_by_type,
        placed_by_id=placement.placed_by_id,
        placed_by_name=placement.placed_by_name,
        placed_at=placement.placed_at,
        cancel_reason=reason,
    )
    db.add(new_placement)
    db.flush()

    for ln in lines:
        db.add(
            VendorOrderLine(
                placement_id=new_placement.id,
                catalog_product_id=ln.catalog_product_id,
                our_product_id=ln.our_product_id,
                quantity=ln.quantity,
                quantity_remaining=ln.quantity,
                buying_price=ln.buying_price,
            )
        )

    # Placed qty stays; note on original; Cancelled bucket holds history copy.
    placement.cancel_reason = reason
    line_summary = ", ".join(f"{ln.our_product_id}×{ln.quantity}" for ln in lines)
    cancel_open_qty(db, order.vendor_id, [(ln.catalog_product_id, ln.quantity) for ln in lines], reason=reason)
    order.updated_at = now
    cancelled_order.updated_at = now
    log_from_auth(
        db,
        auth,
        action="cancel",
        entity_type="vendor_order",
        entity_id=order.id,
        entity_label=label,
        detail=f"cancelled placement #{placement_id}: {line_summary} — {reason[:120]}",
    )
    db.commit()
    db.refresh(order)
    return _build_detail(db, order, auth=auth)

@router.get("/{order_id}", response_model=VendorOrderDetail)
def get_vendor_order(
    order_id: int,
    view: str = Query("default", pattern="^(default|open)$"),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.read")),
):
    order = db.get(VendorOrder, order_id)
    if not order:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor order not found")
    open_only = order.bucket == "placed" and view == "open"
    return _build_detail(db, order, auth=auth, open_only=open_only)

