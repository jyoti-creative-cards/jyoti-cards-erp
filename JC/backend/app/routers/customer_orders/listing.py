from __future__ import annotations
"""Split from app/routers/customer_orders.py."""

from collections import defaultdict
from datetime import date, datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import AuthContext, require_admin, require_permission
from app.models.catalog_product import CatalogProduct
from app.models.city import City
from app.models.customer import Customer
from app.models.customer_bill import CustomerBill, CustomerBillLine
from app.models.customer_order import CustomerOpenLine, CustomerOrder, CustomerOrderLine, CustomerOrderPlacement
from app.schemas.customer_order import (
    CancelRequest,
    EditBillIn,
    PatchBillNumberIn,
    EditQtyIn,
    CustomerBillLineOut,
    CustomerBillOut,
    CustomerOpenLineOut,
    CustomerOrderDetail,
    CustomerOrderSummary,
    CustomerOrderLineOut,
    CustomerPlacementOut,
    ProcessBillIn,
    ProcessContextOut,
    ProcessLineOut,
    OfflineCustomerOrderIn,
    CloseableItemOut,
    CloseBatchIn,
)
from app.services.storage import presigned_urls
from decimal import Decimal

from app.models.freight_agent import FreightAgent
from app.services.activity import log_from_auth
from app.services.biz_date import ist_day_bounds_utc, today_ist
from app.services.customer_bill_math import assert_discount_xor, compute_bill_totals
from app.services.transport_mode import normalize_transport, stamp_transport_on_totals
from app.services.customer_bill_process import (
    cancel_customer_bill,
    cancel_open_line,
    close_bill_line,
    edit_customer_bill,
    get_process_lines,
    process_customer_bill,
)
from app.services.customer_order_flow import (
    cancel_customer_placement,
    create_received_placement,
    edit_customer_open_qty,
    edit_customer_placement_line_qty,
    replace_received_placement,
)
from app.services.doc_gen import generate_customer_bill_document, generate_customer_order_document
from app.services import response_cache
from app.services.storage import presigned_url, storage_configured
from app.schemas.stock import VoidIn
from app.services.void_service import void_customer_bill, void_customer_placement

from app.routers.customer_orders.router import router

def _sort_business_date(value: date | datetime | None) -> tuple[int, datetime]:
    if isinstance(value, datetime):
        ts = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return (1, ts.astimezone(timezone.utc))
    if isinstance(value, date):
        return (1, ist_day_bounds_utc(value)[0])
    return (0, datetime.min.replace(tzinfo=timezone.utc))

def _product_ids_matching_live_name(db: Session, needle: str) -> set[int]:
    escaped = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    rows = (
        db.query(CatalogProduct.id)
        .filter(
            CatalogProduct.deleted_at.is_(None),
            CatalogProduct.our_product_id.ilike(f"%{escaped}%", escape="\\"),
        )
        .all()
    )
    return {int(pid) for (pid,) in rows}

def _customer_ids_matching_product_search(
    db: Session, search: str | None, *, bucket: str | None = None
) -> set[int] | None:
    """None = no filter. Empty set = no matches. Otherwise customer ids with a matching product line
    in the given hub bucket (placements / bills / open lines as appropriate).

    Match the live catalog name, not a stale code frozen on an old line. One indexed
    lookup — do not load every order and rebuild its card.
    """
    if not isinstance(search, str):
        return None
    needle = search.strip()
    if not needle:
        return None
    live_pids = _product_ids_matching_live_name(db, needle)
    if not live_pids:
        return set()
    matched: set[int] = set()

    if bucket is None or bucket in ("received", "cancelled", "closed"):
        q = (
            db.query(CustomerOrder.customer_id)
            .join(CustomerOrderPlacement, CustomerOrderPlacement.customer_order_id == CustomerOrder.id)
            .join(CustomerOrderLine, CustomerOrderLine.placement_id == CustomerOrderPlacement.id)
            .filter(
                CustomerOrderPlacement.deleted_at.is_(None),
                CustomerOrderLine.catalog_product_id.in_(live_pids),
            )
        )
        if bucket is not None:
            q = q.filter(CustomerOrder.bucket == bucket)
        matched.update(int(cid) for (cid,) in q.distinct().all())

    if bucket is None or bucket == "billed":
        # Match the billed hub: active bills only (not cancelled / closed / deleted).
        q = (
            db.query(CustomerBill.customer_id)
            .join(CustomerBillLine, CustomerBillLine.bill_id == CustomerBill.id)
            .filter(
                CustomerBill.cancelled_at.is_(None),
                CustomerBill.closed_at.is_(None),
                CustomerBill.deleted_at.is_(None),
                CustomerBillLine.catalog_product_id.in_(live_pids),
            )
        )
        matched.update(int(cid) for (cid,) in q.distinct().all())

    if bucket is None or bucket == "open":
        q = (
            db.query(CustomerOpenLine.customer_id)
            .filter(
                CustomerOpenLine.status == "open",
                CustomerOpenLine.quantity_open > 0,
                CustomerOpenLine.catalog_product_id.in_(live_pids),
            )
        )
        matched.update(int(cid) for (cid,) in q.distinct().all())

    return matched

def _customer_name(db: Session, customer_id: int) -> str:
    c = db.get(Customer, customer_id)
    return c.business_name if c else f"Customer #{customer_id}"

def _placement_source(notes: str | None) -> str:
    n = (notes or "").lower()
    if "placed by admin" in n or n.startswith("[phone]"):
        return "phone"
    return "portal"

def _sources_for_received(db: Session, received_order_id: int | None) -> list[str]:
    if not received_order_id:
        return []
    notes = (
        db.query(CustomerOrderPlacement.customer_notes)
        .filter(
            CustomerOrderPlacement.customer_order_id == received_order_id,
            CustomerOrderPlacement.deleted_at.is_(None),
        )
        .all()
    )
    found: set[str] = set()
    for (note,) in notes:
        found.add(_placement_source(note))
    return sorted(found)

def _sources_for_received_many(db: Session, received_order_ids: list[int]) -> dict[int, list[str]]:
    """Batched version of _sources_for_received — one query for all orders instead of
    one query per order (was an N+1 hit on every "Confirmed" hub load)."""
    if not received_order_ids:
        return {}
    rows = (
        db.query(CustomerOrderPlacement.customer_order_id, CustomerOrderPlacement.customer_notes)
        .filter(
            CustomerOrderPlacement.customer_order_id.in_(received_order_ids),
            CustomerOrderPlacement.deleted_at.is_(None),
        )
        .all()
    )
    found: dict[int, set[str]] = {}
    for order_id, note in rows:
        found.setdefault(order_id, set()).add(_placement_source(note))
    return {oid: sorted(s) for oid, s in found.items()}

def _summaries_batch(db: Session, orders: list[CustomerOrder]) -> list[CustomerOrderSummary]:
    """One round of queries for a list of orders. Replaces per-order _summary."""
    if not orders:
        return []
    ids = [o.id for o in orders]
    cids = list({o.customer_id for o in orders})
    placement_counts = dict(
        db.query(CustomerOrderPlacement.customer_order_id, func.count(CustomerOrderPlacement.id))
        .filter(
            CustomerOrderPlacement.customer_order_id.in_(ids),
            CustomerOrderPlacement.deleted_at.is_(None),
        )
        .group_by(CustomerOrderPlacement.customer_order_id)
        .all()
    )
    line_rows = (
        db.query(
            CustomerOrderPlacement.customer_order_id,
            func.count(CustomerOrderLine.id),
            func.coalesce(func.sum(CustomerOrderLine.quantity), 0),
        )
        .join(CustomerOrderLine, CustomerOrderLine.placement_id == CustomerOrderPlacement.id)
        .filter(
            CustomerOrderPlacement.customer_order_id.in_(ids),
            CustomerOrderLine.status == "active",
        )
        .group_by(CustomerOrderPlacement.customer_order_id)
        .all()
    )
    line_stats = {int(oid): (int(cnt or 0), int(qty or 0)) for oid, cnt, qty in line_rows}
    customers = {c.id: c for c in db.query(Customer).filter(Customer.id.in_(cids)).all()}
    city_ids = [c.city_id for c in customers.values() if c.city_id]
    cities = {c.id: c for c in db.query(City).filter(City.id.in_(city_ids)).all()} if city_ids else {}
    sources = _sources_for_received_many(db, ids)
    out: list[CustomerOrderSummary] = []
    for order in orders:
        cust = customers.get(order.customer_id)
        city = cities.get(cust.city_id) if cust and cust.city_id else None
        line_count, total = line_stats.get(order.id, (0, 0))
        display_date = order.updated_at
        out.append(
            CustomerOrderSummary(
                id=order.id,
                customer_id=order.customer_id,
                customer_name=cust.business_name if cust else str(order.customer_id),
                bucket=order.bucket,
                placement_count=int(placement_counts.get(order.id) or 0),
                line_count=line_count,
                total_quantity=total,
                updated_at=display_date,
                display_date=display_date,
                sources=sources.get(order.id, []) if order.bucket == "received" else [],
                party_number=getattr(cust, "party_number", None) if cust else None,
                marker_1=getattr(cust, "marker_1", None) if cust else None,
                marker_2=getattr(cust, "marker_2", None) if cust else None,
                payment_type=getattr(cust, "payment_type", None) if cust else None,
                city_name=city.name if city else None,
            )
        )
    return out

def _summary(db: Session, order: CustomerOrder) -> CustomerOrderSummary:
    placements = db.query(CustomerOrderPlacement).filter(
        CustomerOrderPlacement.customer_order_id == order.id, CustomerOrderPlacement.deleted_at.is_(None)
    ).count()
    lines = (
        db.query(CustomerOrderLine)
        .join(CustomerOrderPlacement, CustomerOrderLine.placement_id == CustomerOrderPlacement.id)
        .filter(CustomerOrderPlacement.customer_order_id == order.id, CustomerOrderLine.status == "active")
        .all()
    )
    total = 0
    if order.bucket == "open":
        open_lines = db.query(CustomerOpenLine).filter(
            CustomerOpenLine.customer_id == order.customer_id, CustomerOpenLine.status == "open"
        ).all()
        total = sum(ln.quantity_open for ln in open_lines)
    else:
        total = sum(ln.quantity for ln in lines)
    sources = _sources_for_received(db, order.id) if order.bucket == "received" else []
    cust = db.get(Customer, order.customer_id)
    city = db.get(City, cust.city_id) if cust and cust.city_id else None
    display_date = order.updated_at
    return CustomerOrderSummary(
        id=order.id,
        customer_id=order.customer_id,
        customer_name=cust.business_name if cust else str(order.customer_id),
        bucket=order.bucket,
        placement_count=placements,
        line_count=len(lines),
        total_quantity=total,
        updated_at=display_date,
        display_date=display_date,
        sources=sources,
        party_number=getattr(cust, "party_number", None) if cust else None,
        marker_1=getattr(cust, "marker_1", None) if cust else None,
        marker_2=getattr(cust, "marker_2", None) if cust else None,
        payment_type=getattr(cust, "payment_type", None) if cust else None,
        city_name=city.name if city else None,
    )

@router.get("", response_model=List[CustomerOrderSummary])
def list_customer_orders(
    bucket: str = Query("open", pattern="^(summary|received|open|billed|cancelled|closed)$"),
    day: str = Query("all", pattern="^(all|today)$"),
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("customer_orders.read")),
):
    """Same stages for Today and Past. `day=today` = IST calendar day; `day=all` = full history."""
    # Legacy alias: summary → open + today
    if bucket == "summary":
        bucket = "open"
        day = "today"

    day_start = day_end = None
    if day == "today":
        day_start, day_end = ist_day_bounds_utc(today_ist())

    product_match_cids = _customer_ids_matching_product_search(db, search, bucket=bucket)

    def _filter_by_product(rows: list) -> list:
        if product_match_cids is None:
            return rows
        return [r for r in rows if int(getattr(r, "customer_id", 0) or 0) in product_match_cids]

    if bucket == "open":
        rows = (
            db.query(
                CustomerOpenLine.customer_id,
                func.coalesce(func.sum(CustomerOpenLine.quantity_open), 0),
                func.count(CustomerOpenLine.id),
                func.max(CustomerOpenLine.updated_at),
            )
            .filter(CustomerOpenLine.status == "open", CustomerOpenLine.quantity_open > 0)
            .group_by(CustomerOpenLine.customer_id)
            .all()
        )
        # Like "received": day=today shows only customers whose Confirmed backlog was
        # touched today (a new confirmation, or more qty merged into an existing open
        # line today) — CustomerOpenLine.updated_at bumps on every such write. day=all
        # still shows full history, so nothing is ever lost — it just moves from Today
        # to Past, exactly like "New" does.
        if day_start is not None:
            rows = [r for r in rows if r[3] and day_start <= r[3].astimezone(timezone.utc) < day_end]
        if product_match_cids is not None:
            rows = [r for r in rows if int(r[0]) in product_match_cids]
        cids = [int(r[0]) for r in rows]
        if not cids:
            return []

        # Batch every per-customer lookup below — this used to run up to 4 queries PER
        # CUSTOMER (received order, earliest placement, customer row, sources), which
        # noticeably hung the UI once dozens of customers had a confirmed-but-unbilled
        # order sitting in this backlog bucket.
        received_rows = (
            db.query(CustomerOrder)
            .filter(CustomerOrder.customer_id.in_(cids), CustomerOrder.bucket == "received", CustomerOrder.is_open.is_(True))
            .all()
        )
        received_by_cid = {r.customer_id: r for r in received_rows}
        received_ids = [r.id for r in received_rows]

        sources_by_order_id = _sources_for_received_many(db, received_ids)
        customers_by_id = {c.id: c for c in db.query(Customer).filter(Customer.id.in_(cids)).all()}
        city_ids = {c.city_id for c in customers_by_id.values() if c.city_id}
        cities = {c.id: c.name for c in (db.query(City).filter(City.id.in_(city_ids)).all() if city_ids else [])}
        touched_by_cid = {int(r[0]): r[3] for r in rows}
        placed_by_cid: dict[int, object] = {}
        if received_ids:
            order_cid = {o.id: o.customer_id for o in received_rows}
            for oid, placed in (
                db.query(CustomerOrderPlacement.customer_order_id, func.max(CustomerOrderPlacement.placed_at))
                .filter(
                    CustomerOrderPlacement.customer_order_id.in_(received_ids),
                    CustomerOrderPlacement.deleted_at.is_(None),
                )
                .group_by(CustomerOrderPlacement.customer_order_id)
                .all()
            ):
                cid_for_order = order_cid.get(oid)
                if cid_for_order is not None:
                    placed_by_cid[cid_for_order] = placed

        out: list[CustomerOrderSummary] = []
        for customer_id, total_qty, line_count, _touched in rows:
            cid = int(customer_id)
            received = received_by_cid.get(cid)
            cust_obj = customers_by_id.get(cid)
            touched = touched_by_cid.get(cid) or (received.updated_at if received else datetime.now(timezone.utc))
            out.append(
                CustomerOrderSummary(
                    id=received.id if received else 0,
                    customer_id=cid,
                    customer_name=cust_obj.business_name if cust_obj else str(cid),
                    bucket="open",
                    placement_count=0,
                    line_count=int(line_count or 0),
                    total_quantity=int(total_qty or 0),
                    updated_at=touched,
                    display_date=placed_by_cid.get(cid) or touched,
                    sources=sources_by_order_id.get(received.id, []) if received else [],
                    party_number=getattr(cust_obj, "party_number", None) if cust_obj else None,
                    marker_1=getattr(cust_obj, "marker_1", None) if cust_obj else None,
                    marker_2=getattr(cust_obj, "marker_2", None) if cust_obj else None,
                    payment_type=getattr(cust_obj, "payment_type", None) if cust_obj else None,
                    city_name=cities.get(cust_obj.city_id) if cust_obj and cust_obj.city_id else None,
                )
            )
        out.sort(key=lambda x: _sort_business_date(x.display_date), reverse=True)
        return out

    if bucket == "received":
        rows = (
            db.query(CustomerOrder, func.max(CustomerOrderPlacement.placed_at))
            .join(CustomerOrderPlacement, CustomerOrderPlacement.customer_order_id == CustomerOrder.id)
            .filter(
                CustomerOrder.is_open.is_(True),
                CustomerOrder.bucket == "received",
                CustomerOrderPlacement.deleted_at.is_(None),
            )
            .group_by(CustomerOrder.id)
            .all()
        )
        if day_start is not None:
            rows = [
                row for row in rows
                if row[1] and day_start <= row[1].astimezone(timezone.utc) < day_end
            ]
        rows.sort(key=lambda row: _sort_business_date(row[1]), reverse=True)
        orders = [order for order, _display in rows]
        # A line already on a bill is not a new order. Hide it once nothing is left to confirm.
        unbilled_by_order: dict[int, tuple[int, int]] = {}
        if orders:
            unbilled_rows = (
                db.query(
                    CustomerOrderPlacement.customer_order_id,
                    func.count(CustomerOrderLine.id),
                    func.coalesce(func.sum(CustomerOrderLine.quantity - CustomerOrderLine.quantity_billed), 0),
                )
                .join(CustomerOrderLine, CustomerOrderLine.placement_id == CustomerOrderPlacement.id)
                .filter(
                    CustomerOrderPlacement.customer_order_id.in_([o.id for o in orders]),
                    CustomerOrderPlacement.deleted_at.is_(None),
                    CustomerOrderLine.status == "active",
                    CustomerOrderLine.quantity > CustomerOrderLine.quantity_billed,
                )
                .group_by(CustomerOrderPlacement.customer_order_id)
                .all()
            )
            unbilled_by_order = {
                int(oid): (int(cnt or 0), int(qty or 0)) for oid, cnt, qty in unbilled_rows
            }
            orders = [o for o in orders if unbilled_by_order.get(o.id, (0, 0))[1] > 0]
        out = _summaries_batch(db, orders)
        for summary in out:
            stats = unbilled_by_order.get(summary.id)
            if stats:
                summary.line_count, summary.total_quantity = stats
        by_id = {order.id: display for order, display in rows}
        for summary in out:
            display_date = by_id.get(summary.id) or summary.updated_at
            summary.updated_at = display_date
            summary.display_date = display_date
        return _filter_by_product(out)

    if bucket == "billed":
        bill_q = (
            db.query(
                CustomerBill.customer_id,
                func.count(CustomerBill.id),
                func.max(CustomerBill.bill_date),
                func.max(CustomerBill.created_at),
            )
            .filter(
                CustomerBill.cancelled_at.is_(None),
                CustomerBill.closed_at.is_(None),
                CustomerBill.deleted_at.is_(None),
            )
        )
        if day_start is not None:
            bill_q = bill_q.filter(CustomerBill.bill_date == today_ist())
        bill_rows = []
        for cid, cnt, bill_date, created in bill_q.group_by(CustomerBill.customer_id).all():
            display = bill_date if bill_date is not None else created
            bill_rows.append((int(cid), int(cnt or 0), display or today_ist()))
        bill_rows.sort(key=lambda row: _sort_business_date(row[2]), reverse=True)
        # Batch the customer-name lookup — was one query PER customer (N+1), which
        # noticeably hung the UI once dozens of customers had unclosed bills sitting
        # here (this bucket is auto-opened right after every new bill save).
        bill_cids = [int(cid) for cid, _, _ in bill_rows]
        customers_by_id = {
            c.id: c for c in db.query(Customer).filter(Customer.id.in_(bill_cids)).all()
        } if bill_cids else {}
        city_ids = {c.city_id for c in customers_by_id.values() if c.city_id}
        cities = {c.id: c.name for c in (db.query(City).filter(City.id.in_(city_ids)).all() if city_ids else [])}
        out = []
        for cid, cnt, display_date in bill_rows:
            cust_obj = customers_by_id.get(int(cid))
            out.append(
                CustomerOrderSummary(
                    id=0,
                    customer_id=int(cid),
                    customer_name=cust_obj.business_name if cust_obj else f"Customer #{int(cid)}",
                    bucket="billed",
                    placement_count=int(cnt or 0),
                    bill_count=int(cnt or 0),
                    line_count=0,
                    total_quantity=0,
                    updated_at=display_date or today_ist(),
                    display_date=display_date or today_ist(),
                    sources=[],
                    party_number=getattr(cust_obj, "party_number", None) if cust_obj else None,
                    marker_1=getattr(cust_obj, "marker_1", None) if cust_obj else None,
                    marker_2=getattr(cust_obj, "marker_2", None) if cust_obj else None,
                    payment_type=getattr(cust_obj, "payment_type", None) if cust_obj else None,
                    city_name=cities.get(cust_obj.city_id) if cust_obj and cust_obj.city_id else None,
                )
            )
        return _filter_by_product(out)

    orders = (
        db.query(CustomerOrder)
        .filter(CustomerOrder.is_open.is_(True), CustomerOrder.bucket == bucket)
        .order_by(CustomerOrder.updated_at.asc())
        .all()
    )
    if day_start is not None:
        orders = [
            o for o in orders
            if o.updated_at and day_start <= o.updated_at.astimezone(timezone.utc) < day_end
        ]
    return _filter_by_product(_summaries_batch(db, orders))

