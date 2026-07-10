from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
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
from app.services.open_lines import add_to_open, cancel_open_qty, close_open_line, cancel_open_line, open_lines_for_vendor, reduce_from_open
from app.services.order_summary import pending_qty_by_product, placed_qty_by_product, received_qty_by_product
from app.services.stock_receipt import get_or_create_open_order
from app.services.doc_gen import generate_vendor_placement_document
from app.services.storage import presigned_url, presigned_urls, storage_configured

router = APIRouter(prefix="/vendor-orders", tags=["vendor-orders"])


def _vendor_label(vendor: Vendor, city_name: Optional[str]) -> str:
    city = city_name or ""
    return f"{vendor.business_name} — {city}" if city else vendor.business_name


def _vendor_context(db: Session, vendor_id: int) -> tuple[Vendor, Optional[str], str]:
    vendor = db.get(Vendor, vendor_id)
    if not vendor or vendor.deleted_at:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor not found")
    city_name = None
    if vendor.city_id:
        city = db.get(City, vendor.city_id)
        city_name = city.name if city else None
    return vendor, city_name, _vendor_label(vendor, city_name)


def _placement_color_map(placements: list[VendorOrderPlacement]) -> dict[int, int]:
    ordered = sorted(placements, key=lambda p: (p.placed_at, p.id))
    return {p.id: idx for idx, p in enumerate(ordered)}


def _build_detail(db: Session, order: VendorOrder, *, open_only: bool = False) -> VendorOrderDetail:
    vendor, city_name, label = _vendor_context(db, order.vendor_id)
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
            receipt = db.query(StockReceipt).filter(StockReceipt.billed_placement_id == p.id).first()
        bill_amt = dn_total = net = bill_file = None
        if receipt:
            ba = receipt_bill_amount(db, receipt.id)
            dn = receipt_debit_note_total(db, receipt.id)
            bill_amt = format(ba, "f")
            dn_total = format(dn, "f")
            net = format(ba + dn, "f")
            bill_file = presigned_url(receipt.bill_file_key) if receipt.bill_file_key else None
        placement_summaries.append(
            PlacementSummary(
                id=p.id,
                status=p.status,
                placed_at=p.placed_at,
                placed_by_name=p.placed_by_name,
                placed_by_type=p.placed_by_type,
                color_index=color_map[p.id],
                line_count=len(plines),
                total_quantity=sum(ln.quantity for ln in plines),
                receipt_id=receipt.id if receipt else None,
                bill_number=receipt.bill_number if receipt else None,
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
                    "our_product_id": ln.our_product_id,
                    "total_quantity": 0,
                    "total_placed": 0,
                    "total_received": 0,
                    "total_pending": 0,
                    "buying_price": str(ln.buying_price),
                    "unit": prod.unit if prod else None,
                    "image_urls": presigned_urls(prod.image_keys or []) if prod else [],
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
                    our_product_id=ln.our_product_id,
                    quantity=qty,
                    quantity_billed=ln.quantity_billed,
                    billed_amount=format(ln.billed_amount, "f") if ln.billed_amount is not None else None,
                    buying_price=str(ln.buying_price),
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
        elif order.bucket == "billed":
            v["total_received"] = v["total_quantity"]
        aggregated_lines.append(AggregatedLine(**v))

    return VendorOrderDetail(
        id=order.id,
        vendor_id=order.vendor_id,
        vendor_name=vendor.business_name,
        vendor_city=city_name,
        vendor_label=label,
        status=order.status,
        bucket=order.bucket,
        is_open=order.is_open,
        created_at=order.created_at,
        updated_at=order.updated_at,
        placements=placement_summaries,
        aggregated_lines=aggregated_lines,
    )


def _summary_from_order(db: Session, order: VendorOrder) -> VendorOrderSummary:
    vendor, city_name, label = _vendor_context(db, order.vendor_id)
    placement_count = (
        db.query(VendorOrderPlacement).filter(VendorOrderPlacement.vendor_order_id == order.id).count()
    )
    line_stats = (
        db.query(VendorOrderLine)
        .join(VendorOrderPlacement, VendorOrderLine.placement_id == VendorOrderPlacement.id)
        .filter(VendorOrderPlacement.vendor_order_id == order.id)
        .all()
    )
    total_qty = sum(ln.quantity for ln in line_stats)
    return VendorOrderSummary(
        id=order.id,
        vendor_id=order.vendor_id,
        vendor_name=vendor.business_name,
        vendor_city=city_name,
        vendor_label=label,
        status=order.status,
        bucket=order.bucket,
        is_open=order.is_open,
        placement_count=placement_count,
        line_count=len(line_stats),
        total_quantity=total_qty,
        updated_at=order.updated_at,
    )


@router.get("", response_model=List[VendorOrderSummary])
def list_vendor_orders(
    bucket: str = Query("open", pattern="^(open|placed|billed|cancelled|closed)$"),
    view: str = Query("default", pattern="^(default|open|placed)$"),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.read")),
):
    if bucket == "open":
        from sqlalchemy import func
        rows = (
            db.query(
                VendorOpenLine.vendor_id,
                func.coalesce(func.sum(VendorOpenLine.quantity), 0),
                func.count(VendorOpenLine.id),
            )
            .filter(VendorOpenLine.status == "open", VendorOpenLine.quantity > 0)
            .group_by(VendorOpenLine.vendor_id)
            .all()
        )
        out: list[VendorOrderSummary] = []
        for vendor_id, total_qty, line_count in rows:
            vendor, city_name, label = _vendor_context(db, int(vendor_id))
            placed_order = (
                db.query(VendorOrder)
                .filter(VendorOrder.vendor_id == vendor_id, VendorOrder.bucket == "placed", VendorOrder.is_open.is_(True))
                .first()
            )
            placement_count = 0
            if placed_order:
                placement_count = (
                    db.query(VendorOrderPlacement)
                    .filter(
                        VendorOrderPlacement.vendor_order_id == placed_order.id,
                        VendorOrderPlacement.status == "placed",
                    )
                    .count()
                )
            out.append(
                VendorOrderSummary(
                    id=placed_order.id if placed_order else 0,
                    vendor_id=int(vendor_id),
                    vendor_name=vendor.business_name,
                    vendor_city=city_name,
                    vendor_label=label,
                    status="open",
                    bucket="open",
                    is_open=True,
                    placement_count=placement_count,
                    line_count=int(line_count or 0),
                    total_quantity=int(total_qty or 0),
                    updated_at=datetime.now(timezone.utc),
                )
            )
        out.sort(key=lambda x: x.vendor_label.lower())
        return out

    if bucket == "closed":
        summaries: list[VendorOrderSummary] = []
        seen: set[int] = set()
        closed_lines = db.query(VendorOpenLine).filter(VendorOpenLine.status == "closed").all()
        by_vendor: dict[int, list] = defaultdict(list)
        for ln in closed_lines:
            by_vendor[ln.vendor_id].append(ln)
        for vendor_id, lines in by_vendor.items():
            vendor, city_name, label = _vendor_context(db, vendor_id)
            seen.add(vendor_id)
            summaries.append(
                VendorOrderSummary(
                    id=0,
                    vendor_id=vendor_id,
                    vendor_name=vendor.business_name,
                    vendor_city=city_name,
                    vendor_label=label,
                    status="closed",
                    bucket="closed",
                    is_open=True,
                    placement_count=0,
                    line_count=len(lines),
                    total_quantity=sum(l.quantity for l in lines),
                    updated_at=max((l.updated_at for l in lines), default=datetime.now(timezone.utc)),
                )
            )
        billed_order = db.query(VendorOrder).filter(VendorOrder.bucket == "billed", VendorOrder.is_open.is_(True)).all()
        for order in billed_order:
            closed_ps = (
                db.query(VendorOrderPlacement)
                .filter(VendorOrderPlacement.vendor_order_id == order.id, VendorOrderPlacement.closed_at.isnot(None))
                .all()
            )
            if not closed_ps:
                continue
            closed_line_rows = (
                db.query(VendorOrderLine)
                .filter(VendorOrderLine.placement_id.in_([p.id for p in closed_ps]))
                .all()
            )
            line_count = len(closed_line_rows)
            total_qty = sum(ln.quantity for ln in closed_line_rows)
            latest = max((p.closed_at for p in closed_ps if p.closed_at), default=order.updated_at)
            if order.vendor_id in seen:
                for s in summaries:
                    if s.vendor_id == order.vendor_id:
                        s.id = order.id or s.id
                        s.placement_count += len(closed_ps)
                        s.line_count += line_count
                        s.total_quantity += total_qty
                        if latest and (not s.updated_at or latest > s.updated_at):
                            s.updated_at = latest
                        break
                continue
            vendor, city_name, label = _vendor_context(db, order.vendor_id)
            summaries.append(
                VendorOrderSummary(
                    id=order.id,
                    vendor_id=order.vendor_id,
                    vendor_name=vendor.business_name,
                    vendor_city=city_name,
                    vendor_label=label,
                    status="closed",
                    bucket="closed",
                    is_open=True,
                    placement_count=len(closed_ps),
                    line_count=line_count,
                    total_quantity=total_qty,
                    updated_at=latest,
                )
            )
        summaries.sort(key=lambda x: x.vendor_label.lower())
        return summaries

    orders = (
        db.query(VendorOrder)
        .filter(VendorOrder.is_open.is_(True), VendorOrder.bucket == bucket)
        .order_by(VendorOrder.updated_at.desc())
        .all()
    )
    summaries = [_summary_from_order(db, o) for o in orders]
    if bucket == "placed" and view == "open":
        summaries = [s for s in summaries if s.total_quantity > 0]
    return summaries


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
                total_placed=placed_map.get(cat_id, 0),
                total_received=received_map.get(cat_id, 0),
                total_pending=pending_map.get(cat_id, 0),
                total_cancelled=cancelled_map.get(cat_id, 0),
                total_closed=closed_map.get(cat_id, 0),
                buying_price=str(prod.buying_price),
                unit=prod.unit,
                image_urls=presigned_urls(prod.image_keys or []),
                open_line_id=open_line_map.get(cat_id),
            )
        )
    lines.sort(key=lambda x: x.our_product_id.lower())
    return VendorOrderSummaryDetail(vendor_id=vendor_id, vendor_label=label, lines=lines)


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


@router.get("/closeable", response_model=List[CloseableVendorItemOut])
def list_closeable_billed(
    vendor_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.read")),
):
    q = (
        db.query(VendorOrderPlacement, VendorOrder)
        .join(VendorOrder, VendorOrderPlacement.vendor_order_id == VendorOrder.id)
        .filter(VendorOrder.bucket == "billed", VendorOrderPlacement.status == "billed", VendorOrderPlacement.closed_at.is_(None))
    )
    if vendor_id is not None:
        q = q.filter(VendorOrder.vendor_id == vendor_id)
    rows = q.order_by(VendorOrderPlacement.placed_at.desc()).all()
    out: list[CloseableVendorItemOut] = []
    for placement, order in rows:
        vendor, city_name, label = _vendor_context(db, order.vendor_id)
        lines = db.query(VendorOrderLine).filter(VendorOrderLine.placement_id == placement.id).all()
        receipt = db.query(StockReceipt).filter(StockReceipt.billed_placement_id == placement.id).first()
        out.append(
            CloseableVendorItemOut(
                id=placement.id,
                vendor_id=order.vendor_id,
                vendor_label=label,
                bill_number=receipt.bill_number if receipt else None,
                line_count=len(lines),
                total_qty=sum(ln.quantity for ln in lines),
                placed_at=placement.placed_at,
            )
        )
    return out


@router.post("/close-batch")
def close_batch_placements(
    body: CloseBatchIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.write")),
):
    closed = 0
    now = datetime.now(timezone.utc)
    for pid in body.placement_ids:
        placement = db.get(VendorOrderPlacement, pid)
        if not placement or placement.closed_at:
            continue
        order = db.get(VendorOrder, placement.vendor_order_id)
        if not order or order.bucket != "billed":
            continue
        vendor, _, label = _vendor_context(db, order.vendor_id)
        placement.closed_at = now
        placement.close_reason = body.reason.strip()
        order.updated_at = now
        log_from_auth(
            db, auth, action="close", entity_type="vendor_order", entity_id=order.id,
            entity_label=label, detail=f"batch closed placement #{pid}: {body.reason[:120]}",
        )
        closed += 1
    db.commit()
    return {"ok": True, "closed": closed}


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
    return _build_detail(db, order, open_only=open_only)


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
                buying_price=str(p.buying_price),
                unit=p.unit,
                image_urls=presigned_urls(p.image_keys or []),
                alternatives=[
                    {
                        "catalog_product_id": a.id,
                        "our_product_id": a.our_product_id,
                        "buying_price": str(a.buying_price),
                    }
                    for a in sorted(alts_by_product.get(p.id, []), key=lambda x: x.our_product_id.lower())
                ],
            )
        )
    return out


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

    order = get_or_create_open_order(db, body.vendor_id, "placed", "placed")
    placement = VendorOrderPlacement(
        vendor_order_id=order.id,
        status="placed",
        placed_by_type=auth.actor_type,
        placed_by_id=auth.actor_id,
        placed_by_name=auth.actor_name,
        placed_at=datetime.now(timezone.utc),
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

    order.updated_at = datetime.now(timezone.utc)
    add_to_open(db, body.vendor_id, [(ln.catalog_product_id, ln.quantity) for ln in body.lines])
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
    if storage_configured():
        try:
            db.flush()
            generate_vendor_placement_document(db, placement.id)
        except Exception:
            pass
    db.commit()
    db.refresh(order)
    return _build_detail(db, order)


def _open_line_out(db: Session, row: VendorOpenLine) -> OpenLineOut:
    prod = db.get(CatalogProduct, row.catalog_product_id)
    return OpenLineOut(
        id=row.id,
        catalog_product_id=row.catalog_product_id,
        our_product_id=row.our_product_id,
        quantity=row.quantity,
        buying_price=str(row.buying_price),
        unit=prod.unit if prod else None,
        image_urls=presigned_urls(prod.image_keys or []) if prod else [],
        status=row.status,
    )


def _open_vendor_detail(db: Session, vendor_id: int) -> OpenVendorDetail:
    _, _, label = _vendor_context(db, vendor_id)
    lines = open_lines_for_vendor(db, vendor_id, status="open")
    lines = [ln for ln in lines if ln.quantity > 0]
    return OpenVendorDetail(
        vendor_id=vendor_id,
        vendor_label=label,
        lines=[_open_line_out(db, ln) for ln in lines],
    )


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


@router.get("/vendor/{vendor_id}/open", response_model=OpenVendorDetail)
def get_vendor_open_order(
    vendor_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.read")),
):
    return _open_vendor_detail(db, vendor_id)


@router.get("/vendor/{vendor_id}/closed", response_model=List[ClosedLineOut])
def get_vendor_closed_lines(
    vendor_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.read")),
):
    _vendor_context(db, vendor_id)
    out: list[ClosedLineOut] = []
    for row in db.query(VendorOpenLine).filter(
        VendorOpenLine.vendor_id == vendor_id, VendorOpenLine.status == "closed"
    ).order_by(VendorOpenLine.updated_at.desc()).all():
        out.append(
            ClosedLineOut(
                id=row.id,
                catalog_product_id=row.catalog_product_id,
                our_product_id=row.our_product_id,
                quantity=row.quantity,
                buying_price=str(row.buying_price),
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
            receipt = db.query(StockReceipt).filter(StockReceipt.billed_placement_id == p.id).first()
            plines = db.query(VendorOrderLine).filter(VendorOrderLine.placement_id == p.id).all()
            for ln in plines:
                out.append(
                    ClosedLineOut(
                        id=ln.id,
                        catalog_product_id=ln.catalog_product_id,
                        our_product_id=ln.our_product_id,
                        quantity=ln.quantity,
                        buying_price=str(ln.buying_price),
                        source="billed",
                        closed_at=p.closed_at,
                        bill_number=receipt.bill_number if receipt else None,
                        close_reason=p.close_reason,
                        placement_id=p.id,
                    )
                )
    return out


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
    db.commit()
    return _open_vendor_detail(db, row.vendor_id)



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
    return _open_vendor_detail(db, row.vendor_id)


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
    return _open_vendor_detail(db, row.vendor_id)


@router.post("/placements/{placement_id}/close", response_model=VendorOrderDetail)
def close_billed_placement(
    placement_id: int,
    body: ReasonIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.write")),
):
    placement = db.get(VendorOrderPlacement, placement_id)
    if not placement:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="placement not found")
    order = db.get(VendorOrder, placement.vendor_order_id)
    if not order or order.bucket != "billed":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="only billed placements can be closed")
    if placement.closed_at:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="already closed")
    vendor, _, label = _vendor_context(db, order.vendor_id)
    reason = body.reason.strip()
    placement.closed_at = datetime.now(timezone.utc)
    placement.close_reason = reason
    order.updated_at = placement.closed_at
    log_from_auth(
        db, auth, action="close", entity_type="vendor_order", entity_id=order.id,
        entity_label=label, detail=f"closed billed placement #{placement_id}: {reason[:120]}",
    )
    db.commit()
    db.refresh(order)
    return _build_detail(db, order)


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
    return _build_detail(db, order)
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
        return _build_detail(db, order)

    order.updated_at = datetime.now(timezone.utc)
    log_from_auth(
        db,
        auth,
        action="update_line",
        entity_type="vendor_order",
        entity_id=order.id,
        entity_label=label,
        detail=f"line #{line_id}: {', '.join(changes)}",
    )
    db.commit()
    db.refresh(order)
    return _build_detail(db, order)
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
    db.delete(line)
    order.updated_at = datetime.now(timezone.utc)
    log_from_auth(db, auth, action="delete_line", entity_type="vendor_order", entity_id=order.id, entity_label=label, detail=detail)
    db.commit()
    db.refresh(order)
    return _build_detail(db, order)


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
            generate_vendor_placement_document(db, placement.id)
            db.commit()
            db.refresh(placement)
        except Exception:
            db.rollback()
    if not placement.document_key:
        raise HTTPException(404, "document not available")
    url = presigned_url(placement.document_key)
    if not url:
        raise HTTPException(503, "storage not available")
    return {"document_url": url, "document_key": placement.document_key}
