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

from app.routers.vendor_orders.actions import _billed_summaries, _sort_dt, _to_bill_summaries
from app.routers.vendor_orders.common import _vendor_contexts
from app.routers.vendor_orders.get_vendor_closed_lines import _summaries_from_orders

@router.get("", response_model=List[VendorOrderSummary])
def list_vendor_orders(
    bucket: str = Query("open", pattern="^(open|placed|received|billed|cancelled|closed)$"),
    view: str = Query("default", pattern="^(default|open|placed)$"),
    day: str = Query("all", pattern="^(all|today)$"),
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.read")),
):
    """Same stages for Today and Past. `day=today` = IST calendar day; `day=all` = full history."""
    from sqlalchemy import func

    day_start = day_end = None
    if day == "today":
        day_start, day_end = ist_day_bounds_utc(today_ist())

    product_match_vids = _vendor_ids_matching_product_search(db, search, bucket=bucket)

    def _vids_with_placement_today(statuses: tuple[str, ...] | None = None) -> set[int]:
        assert day_start is not None and day_end is not None
        q = (
            db.query(VendorOrder.vendor_id)
            .join(VendorOrderPlacement, VendorOrderPlacement.vendor_order_id == VendorOrder.id)
            .filter(
                VendorOrder.is_open.is_(True),
                VendorOrderPlacement.placed_at >= day_start,
                VendorOrderPlacement.placed_at < day_end,
            )
        )
        if statuses:
            q = q.filter(VendorOrderPlacement.status.in_(statuses))
        return {int(r[0]) for r in q.distinct().all()}

    def _vids_closed_today() -> set[int]:
        assert day_start is not None and day_end is not None
        from_lines = {
            int(r[0])
            for r in (
                db.query(VendorOpenLine.vendor_id)
                .filter(
                    VendorOpenLine.status == "closed",
                    VendorOpenLine.updated_at >= day_start,
                    VendorOpenLine.updated_at < day_end,
                )
                .distinct()
                .all()
            )
        }
        from_placements = {
            int(r[0])
            for r in (
                db.query(VendorOrder.vendor_id)
                .join(VendorOrderPlacement, VendorOrderPlacement.vendor_order_id == VendorOrder.id)
                .filter(
                    VendorOrderPlacement.closed_at.isnot(None),
                    VendorOrderPlacement.closed_at >= day_start,
                    VendorOrderPlacement.closed_at < day_end,
                )
                .distinct()
                .all()
            )
        }
        return from_lines | from_placements

    def _vids_pending_bill_today() -> set[int]:
        assert day_start is not None and day_end is not None
        rows = (
            db.query(StockReceipt.vendor_id)
            .filter(
                StockReceipt.bill_status == "pending_bill",
                StockReceipt.deleted_at.is_(None),
                StockReceipt.received_at >= day_start,
                StockReceipt.received_at < day_end,
            )
            .distinct()
            .all()
        )
        return {int(r[0]) for r in rows}

    if bucket == "open":
        out: list[VendorOrderSummary] = []
        today_receive = None
        today_bill = None
        if day_start is not None:
            today_receive = _vids_with_placement_today(("placed",))
            today_bill = _vids_pending_bill_today()

        # Yet to receive (placed open lines)
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
        receive_vctx = _vendor_contexts(db, {int(vendor_id) for vendor_id, _, _ in rows})
        for vendor_id, total_qty, line_count in rows:
            vid = int(vendor_id)
            if today_receive is not None and vid not in today_receive:
                continue
            ctx = receive_vctx.get(vid)
            if ctx is None:
                continue
            vendor, city_name, label = ctx
            placed_order = (
                db.query(VendorOrder)
                .filter(VendorOrder.vendor_id == vid, VendorOrder.bucket == "placed", VendorOrder.is_open.is_(True))
                .first()
            )
            placement_count = 0
            latest = None
            if placed_order:
                latest = (
                    db.query(func.max(VendorOrderPlacement.placed_at))
                    .filter(
                        VendorOrderPlacement.vendor_order_id == placed_order.id,
                        VendorOrderPlacement.status == "placed",
                    )
                    .scalar()
                )
                placement_count = (
                    db.query(VendorOrderPlacement)
                    .filter(
                        VendorOrderPlacement.vendor_order_id == placed_order.id,
                        VendorOrderPlacement.status == "placed",
                    )
                    .count()
                )
            # Open qty can exist without a status="placed" placement (e.g. receipt
            # restore via add_to_open). Keep the row for day=all; day=today stays
            # gated by today_receive (placed_at in IST today). No placed_at →
            # display_date null; updated_at is required so use datetime.min UTC
            # (same sentinel _sort_dt uses for a missing date).
            out.append(
                VendorOrderSummary(
                    id=placed_order.id if placed_order else 0,
                    vendor_id=vid,
                    vendor_name=vendor.business_name,
                    vendor_city=city_name,
                    vendor_label=label,
                    alias=vendor.alias,
                    status="to_receive",
                    bucket="open",
                    is_open=True,
                    placement_count=placement_count,
                    line_count=int(line_count or 0),
                    total_quantity=int(total_qty or 0),
                    updated_at=latest if latest is not None else datetime.min.replace(tzinfo=timezone.utc),
                    display_date=latest,
                    open_kind="to_receive",
                )
            )

        # Yet to bill (pending StockReceipts, one-to-one model)
        out.extend(_to_bill_summaries(db, only_vendor_ids=today_bill))
        out.sort(key=lambda x: _sort_dt(x.display_date), reverse=True)
        return _filter_vendor_summaries(out, product_match_vids)

    if bucket == "closed":
        summaries: list[VendorOrderSummary] = []
        seen: set[int] = set()
        today_closed = _vids_closed_today() if day_start is not None else None
        closed_lines = db.query(VendorOpenLine).filter(VendorOpenLine.status == "closed").all()
        by_vendor: dict[int, list] = defaultdict(list)
        for ln in closed_lines:
            by_vendor[ln.vendor_id].append(ln)
        closed_vctx = _vendor_contexts(db, set(by_vendor.keys()))
        for vendor_id, lines in by_vendor.items():
            if today_closed is not None and vendor_id not in today_closed:
                continue
            ctx = closed_vctx.get(vendor_id)
            if ctx is None:
                continue
            vendor, city_name, label = ctx
            seen.add(vendor_id)
            summaries.append(
                VendorOrderSummary(
                    id=0,
                    vendor_id=vendor_id,
                    vendor_name=vendor.business_name,
                    vendor_city=city_name,
                    vendor_label=label,
                    alias=vendor.alias,
                    status="closed",
                    bucket="closed",
                    is_open=True,
                    placement_count=0,
                    line_count=len(lines),
                    total_quantity=sum(l.quantity for l in lines),
                    updated_at=max((l.updated_at for l in lines), default=datetime.now(timezone.utc)),
                    display_date=max((l.updated_at for l in lines), default=datetime.now(timezone.utc)),
                )
            )
        billed_rows_q = (
            db.query(
                StockReceipt.vendor_id,
                func.count(StockReceipt.id),
                func.coalesce(func.sum(StockReceiptLine.quantity_received), 0),
                func.max(StockReceipt.billed_at),
            )
            .join(StockReceiptLine, StockReceiptLine.receipt_id == StockReceipt.id)
            .filter(StockReceipt.bill_status == "billed", StockReceipt.deleted_at.is_(None))
        )
        if day_start is not None:
            billed_rows_q = billed_rows_q.filter(StockReceipt.billed_at >= day_start, StockReceipt.billed_at < day_end)
        billed_rows = billed_rows_q.group_by(StockReceipt.vendor_id).all()
        billed_vctx = _vendor_contexts(db, {int(vendor_id) for vendor_id, _, _, _ in billed_rows if int(vendor_id) not in seen})
        for vendor_id, receipt_count, total_qty, latest in billed_rows:
            vid = int(vendor_id)
            if vid in seen:
                for s in summaries:
                    if s.vendor_id == vid:
                        s.placement_count += int(receipt_count)
                        s.line_count += int(receipt_count)
                        s.total_quantity += int(total_qty or 0)
                        if latest and (not s.updated_at or latest > s.updated_at):
                            s.updated_at = latest
                            s.display_date = latest
                        break
                continue
            ctx = billed_vctx.get(vid)
            if ctx is None:
                continue
            vendor, city_name, label = ctx
            summaries.append(
                VendorOrderSummary(
                    id=0,
                    vendor_id=vid,
                    vendor_name=vendor.business_name,
                    vendor_city=city_name,
                    vendor_label=label,
                    alias=vendor.alias,
                    status="closed",
                    bucket="closed",
                    is_open=True,
                    placement_count=int(receipt_count),
                    line_count=int(receipt_count),
                    total_quantity=int(total_qty or 0),
                    updated_at=latest or datetime.now(timezone.utc),
                    display_date=latest or datetime.now(timezone.utc),
                )
            )
        summaries.sort(key=lambda x: _sort_dt(x.display_date), reverse=True)
        return _filter_vendor_summaries(summaries, product_match_vids)

    if bucket == "received":
        # "To bill" stage — VendorOrder.bucket never becomes "received" (see
        # _to_bill_summaries); source from StockReceipt.bill_status instead.
        # Day-scoped like every other bucket now: day=today shows only receipts that
        # came in today (StockReceipt.received_at), day=all shows the full backlog —
        # nothing is lost, it just moves from Today to Past.
        return _filter_vendor_summaries(
            _to_bill_summaries(db, day_start=day_start, day_end=day_end),
            product_match_vids,
        )

    if bucket == "billed":
        # Same story as "received" — VendorOrder.bucket never becomes "billed" either.
        return _filter_vendor_summaries(
            _billed_summaries(db, day_start=day_start, day_end=day_end),
            product_match_vids,
        )

    orders = (
        db.query(VendorOrder)
        .filter(VendorOrder.is_open.is_(True), VendorOrder.bucket == bucket)
        .all()
    )
    if bucket == "placed":
        placed_at_by_order = {
            int(order_id): placed_at
            for order_id, placed_at in (
                db.query(VendorOrderPlacement.vendor_order_id, func.max(VendorOrderPlacement.placed_at))
                .filter(VendorOrderPlacement.vendor_order_id.in_([o.id for o in orders]), VendorOrderPlacement.status == "placed")
                .group_by(VendorOrderPlacement.vendor_order_id)
                .all()
            )
        } if orders else {}
        if day_start is not None:
            orders = [
                o for o in orders
                if placed_at_by_order.get(o.id) and day_start <= placed_at_by_order[o.id].astimezone(timezone.utc) < day_end
            ]
        summaries = _summaries_from_orders(db, orders)
        for summary in summaries:
            display_date = placed_at_by_order.get(summary.id)
            if display_date is not None:
                summary.updated_at = display_date
                summary.display_date = display_date
        summaries.sort(key=lambda x: _sort_dt(x.display_date), reverse=True)
    else:
        if day_start is not None:
            orders = [
                o for o in orders
                if o.updated_at and day_start <= o.updated_at.astimezone(timezone.utc) < day_end
            ]
        summaries = _summaries_from_orders(db, orders)
    if bucket == "placed" and view == "open":
        summaries = [s for s in summaries if s.total_quantity > 0]
    return _filter_vendor_summaries(summaries, product_match_vids)

def _vendor_ids_matching_product_search(
    db: Session, search: str | None, *, bucket: str | None = None
) -> set[int] | None:
    if not isinstance(search, str):
        return None
    needle = search.strip()
    if not needle:
        return None
    live_pids = _product_ids_matching_live_name(db, needle)
    matched: set[int] = set()

    # Placements: locked → card via present(); unlocked → live. Scoped to order bucket.
    # Closed hub does not list placements — only closed open lines + billed receipts.
    if bucket is None or bucket in ("placed", "cancelled"):
        for placement in db.query(VendorOrderPlacement).all():
            order = db.get(VendorOrder, placement.vendor_order_id)
            if not order:
                continue
            if getattr(placement, "status", None) in ("cancelled", "voided"):
                if bucket not in (None, "cancelled"):
                    continue
            if bucket in ("placed", "cancelled") and order.bucket != bucket:
                continue
            view = present(db, "vendor_order", placement)
            if _view_matches_product_search(view, needle, live_pids):
                matched.add(int(order.vendor_id))

    # Receipts: match the same document filters each hub bucket uses in list_vendor_orders.
    if bucket is None or bucket in ("open", "received", "billed", "closed"):
        for receipt in db.query(StockReceipt).filter(StockReceipt.deleted_at.is_(None)).all():
            bill_status = getattr(receipt, "bill_status", None)
            is_billed = bill_status == "billed"
            is_pending = bill_status == "pending_bill"
            if bucket == "received" and not is_pending:
                continue
            if bucket == "billed" and (not is_billed or receipt.closed_at is not None):
                continue
            if bucket == "open" and is_billed:
                continue
            if bucket == "closed" and not is_billed:
                continue
            kinds = ["vendor_bill"] if is_billed else ["vendor_receipt"]
            if bucket is None:
                kinds = ["vendor_receipt"]
                if is_billed:
                    kinds.append("vendor_bill")
            for kind in kinds:
                view = present(db, kind, receipt)
                if _view_matches_product_search(view, needle, live_pids):
                    matched.add(int(receipt.vendor_id))
                    break

    if bucket is None or bucket == "open":
        for row in db.query(VendorOpenLine).filter(VendorOpenLine.status == "open", VendorOpenLine.quantity > 0).all():
            prod = db.get(CatalogProduct, row.catalog_product_id)
            name = (prod.our_product_id if prod else row.our_product_id or "").lower()
            if needle.lower() in name or int(row.catalog_product_id or 0) in live_pids:
                matched.add(int(row.vendor_id))

    if bucket == "closed":
        for row in db.query(VendorOpenLine).filter(VendorOpenLine.status == "closed").all():
            prod = db.get(CatalogProduct, row.catalog_product_id)
            name = (prod.our_product_id if prod else row.our_product_id or "").lower()
            if needle.lower() in name or int(row.catalog_product_id or 0) in live_pids:
                matched.add(int(row.vendor_id))

    return matched

def _view_matches_product_search(view: dict, needle: str, live_pids: set[int]) -> bool:
    needle_l = needle.lower()
    for ln in view.get("lines") or []:
        name = str(ln.get("our_product_id") or "").lower()
        cid = int(ln.get("catalog_product_id") or 0)
        if needle_l in name or (cid and cid in live_pids):
            return True
    return False

def _product_ids_matching_live_name(db: Session, needle: str) -> set[int]:
    needle_l = needle.lower()
    return {
        int(p.id)
        for p in db.query(CatalogProduct).filter(CatalogProduct.deleted_at.is_(None)).all()
        if needle_l in (p.our_product_id or "").lower()
    }

def _filter_vendor_summaries(rows: list, match_vids: set[int] | None) -> list:
    if match_vids is None:
        return rows
    return [r for r in rows if int(getattr(r, "vendor_id", 0) or 0) in match_vids]

