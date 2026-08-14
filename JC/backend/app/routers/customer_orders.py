from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

_BIZ_TZ = ZoneInfo("Asia/Kolkata")


def _local_day_bounds_utc(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Start/end of business 'today' in Asia/Kolkata, as UTC datetimes."""
    local_now = (now or datetime.now(timezone.utc)).astimezone(_BIZ_TZ)
    start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)

from app.db.session import get_db
from app.deps import AuthContext, require_permission
from app.models.catalog_product import CatalogProduct
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

router = APIRouter(prefix="/customer-orders", tags=["customer-orders"])


def _customer_name(db: Session, customer_id: int) -> str:
    c = db.get(Customer, customer_id)
    return c.business_name if c else f"Customer #{customer_id}"


def _line_net_rate(bill: CustomerBill, ln: CustomerBillLine) -> str | None:
    totals = bill.totals_json if isinstance(bill.totals_json, dict) else {}
    cid = int(ln.catalog_product_id)
    for row in totals.get("lines") or []:
        if not isinstance(row, dict):
            continue
        if int(row.get("catalog_product_id") or 0) != cid:
            continue
        if row.get("net_rate"):
            return str(row["net_rate"])
        if row.get("effective_price"):
            return str(row["effective_price"])
    qty = int(ln.quantity_shipped or 0)
    if qty > 0 and ln.line_total is not None:
        return format((Decimal(str(ln.line_total)) / Decimal(qty)).quantize(Decimal("0.01")), "f")
    return None


def serialize_customer_bill(
    db: Session,
    bill: CustomerBill,
    blines: list,
    addon_by_cid: dict,
) -> CustomerBillOut:
    agent_name = None
    if bill.freight_agent_id:
        agent = db.get(FreightAgent, bill.freight_agent_id)
        agent_name = agent.name if agent else None
    mode = bill.transport_mode or ("bus" if bill.freight_agent_id else "self_pickup")
    return CustomerBillOut(
        id=bill.id,
        bill_number=bill.bill_number,
        grand_total=format(bill.grand_total, "f"),
        narration=bill.narration,
        customer_id=bill.customer_id,
        gst_enabled=bool(bill.gst_enabled),
        gst_rate_percent=format(bill.gst_rate_percent or 0, "f"),
        discount_percent=format(bill.discount_percent, "f") if bill.discount_percent is not None else None,
        freight_agent_id=bill.freight_agent_id,
        freight_charges=format(bill.freight_charges, "f") if bill.freight_charges is not None else None,
        packaging_charges=format(bill.packaging_charges, "f") if bill.packaging_charges is not None else None,
        additional_charges=bill.additional_charges,
        bill_series_id=bill.bill_series_id,
        bill_date=bill.bill_date,
        created_at=bill.created_at,
        transport_mode=mode,
        transport_receipt_number=bill.transport_receipt_number,
        freight_agent_name=agent_name,
        cancelled_at=bill.cancelled_at,
        lines=[
            CustomerBillLineOut(
                id=ln.id,
                bill_id=bill.id,
                bill_number=bill.bill_number,
                catalog_product_id=ln.catalog_product_id,
                our_product_id=ln.our_product_id,
                quantity_shipped=ln.quantity_shipped,
                unit_price=format(ln.unit_price, "f"),
                line_total=format(ln.line_total, "f"),
                discount_percent=format(ln.discount_percent, "f") if ln.discount_percent is not None else None,
                net_rate=_line_net_rate(bill, ln),
                status=ln.status,
                close_reason=ln.close_reason,
                addons=addon_by_cid.get(int(ln.catalog_product_id), []),
            )
            for ln in blines
        ],
    )


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
        .filter(CustomerOrderPlacement.customer_order_id == received_order_id)
        .all()
    )
    found: set[str] = set()
    for (note,) in notes:
        found.add(_placement_source(note))
    return sorted(found)


def _summary(db: Session, order: CustomerOrder) -> CustomerOrderSummary:
    placements = db.query(CustomerOrderPlacement).filter(CustomerOrderPlacement.customer_order_id == order.id).count()
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
    return CustomerOrderSummary(
        id=order.id,
        customer_id=order.customer_id,
        customer_name=_customer_name(db, order.customer_id),
        bucket=order.bucket,
        placement_count=placements,
        line_count=len(lines),
        total_quantity=total,
        updated_at=order.updated_at,
        sources=sources,
    )


@router.get("", response_model=List[CustomerOrderSummary])
def list_customer_orders(
    bucket: str = Query("open", pattern="^(summary|received|open|billed|cancelled|closed)$"),
    day: str = Query("all", pattern="^(all|today)$"),
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
        day_start, day_end = _local_day_bounds_utc()

    def _cids_with_placement_today() -> set[int]:
        assert day_start is not None and day_end is not None
        rows = (
            db.query(CustomerOrder.customer_id)
            .join(CustomerOrderPlacement, CustomerOrderPlacement.customer_order_id == CustomerOrder.id)
            .filter(
                CustomerOrder.is_open.is_(True),
                CustomerOrder.bucket == "received",
                CustomerOrderPlacement.status == "received",
                CustomerOrderPlacement.placed_at >= day_start,
                CustomerOrderPlacement.placed_at < day_end,
            )
            .distinct()
            .all()
        )
        return {int(r[0]) for r in rows}

    def _cids_open_created_today() -> set[int]:
        assert day_start is not None and day_end is not None
        rows = (
            db.query(CustomerOpenLine.customer_id)
            .filter(
                CustomerOpenLine.status == "open",
                CustomerOpenLine.quantity_open > 0,
                CustomerOpenLine.created_at >= day_start,
                CustomerOpenLine.created_at < day_end,
            )
            .distinct()
            .all()
        )
        return {int(r[0]) for r in rows}

    if bucket == "open":
        rows = (
            db.query(
                CustomerOpenLine.customer_id,
                func.coalesce(func.sum(CustomerOpenLine.quantity_open), 0),
                func.count(CustomerOpenLine.id),
            )
            .filter(CustomerOpenLine.status == "open", CustomerOpenLine.quantity_open > 0)
            .group_by(CustomerOpenLine.customer_id)
            .all()
        )
        today_cids = None  # type: Optional[set[int]]
        if day_start is not None:
            today_cids = _cids_with_placement_today() | _cids_open_created_today()
        out: list[CustomerOrderSummary] = []
        for customer_id, total_qty, line_count in rows:
            cid = int(customer_id)
            if today_cids is not None and cid not in today_cids:
                continue
            received = (
                db.query(CustomerOrder)
                .filter(CustomerOrder.customer_id == cid, CustomerOrder.bucket == "received", CustomerOrder.is_open.is_(True))
                .first()
            )
            earliest = None
            if received:
                pq = db.query(func.min(CustomerOrderPlacement.placed_at)).filter(
                    CustomerOrderPlacement.customer_order_id == received.id,
                    CustomerOrderPlacement.status == "received",
                )
                if day_start is not None:
                    pq = pq.filter(
                        CustomerOrderPlacement.placed_at >= day_start,
                        CustomerOrderPlacement.placed_at < day_end,
                    )
                earliest = pq.scalar()
            out.append(
                CustomerOrderSummary(
                    id=received.id if received else 0,
                    customer_id=cid,
                    customer_name=_customer_name(db, cid),
                    bucket="open",
                    placement_count=0,
                    line_count=int(line_count or 0),
                    total_quantity=int(total_qty or 0),
                    updated_at=earliest or (received.updated_at if received else datetime.now(timezone.utc)),
                    sources=_sources_for_received(db, received.id if received else None),
                )
            )
        out.sort(key=lambda x: x.updated_at or datetime.min.replace(tzinfo=timezone.utc))
        return out

    if bucket == "received":
        if day_start is not None:
            today_cids = _cids_with_placement_today()
            if not today_cids:
                return []
            orders = (
                db.query(CustomerOrder)
                .filter(
                    CustomerOrder.is_open.is_(True),
                    CustomerOrder.bucket == "received",
                    CustomerOrder.customer_id.in_(today_cids),
                )
                .order_by(CustomerOrder.updated_at.asc())
                .all()
            )
            return [_summary(db, o) for o in orders]
        orders = (
            db.query(CustomerOrder)
            .filter(CustomerOrder.is_open.is_(True), CustomerOrder.bucket == "received")
            .order_by(CustomerOrder.updated_at.asc())
            .all()
        )
        return [_summary(db, o) for o in orders]

    if bucket == "billed":
        # Always derive from active bills — cancelled bills/orders must not linger in Billed
        q = db.query(
            CustomerBill.customer_id,
            func.count(CustomerBill.id),
            func.min(CustomerBill.created_at),
        ).filter(CustomerBill.cancelled_at.is_(None))
        if day_start is not None:
            q = q.filter(
                CustomerBill.created_at >= day_start,
                CustomerBill.created_at < day_end,
            )
        bill_rows = q.group_by(CustomerBill.customer_id).all()
        out = []
        for cid, cnt, earliest in bill_rows:
            out.append(
                CustomerOrderSummary(
                    id=0,
                    customer_id=int(cid),
                    customer_name=_customer_name(db, int(cid)),
                    bucket="billed",
                    placement_count=int(cnt or 0),
                    line_count=0,
                    total_quantity=0,
                    updated_at=earliest or datetime.now(timezone.utc),
                    sources=[],
                )
            )
        out.sort(key=lambda x: x.updated_at or datetime.min.replace(tzinfo=timezone.utc))
        return out

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
    return [_summary(db, o) for o in orders]


@router.get("/customer/{customer_id}", response_model=CustomerOrderDetail)
def get_customer_order_detail(
    customer_id: int,
    bucket: str = Query("received", pattern="^(received|open|billed|cancelled|closed)$"),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("customer_orders.read")),
):
    customer = db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(404, "customer not found")

    if bucket == "open":
        from app.services.catalog_addons import addon_snapshots_map

        open_lines = (
            db.query(CustomerOpenLine)
            .filter(CustomerOpenLine.customer_id == customer_id, CustomerOpenLine.status == "open", CustomerOpenLine.quantity_open > 0)
            .order_by(CustomerOpenLine.our_product_id.asc())
            .all()
        )
        addon_map = addon_snapshots_map(
            db, [r.catalog_product_id for r in open_lines], with_images=False
        ) if open_lines else {}
        lines_out: list[CustomerOpenLineOut] = []
        for row in open_lines:
            prod = db.get(CatalogProduct, row.catalog_product_id)
            lines_out.append(
                CustomerOpenLineOut(
                    id=row.id,
                    catalog_product_id=row.catalog_product_id,
                    our_product_id=row.our_product_id,
                    quantity_received=row.quantity_received,
                    quantity_open=row.quantity_open,
                    quantity_billed=row.quantity_billed,
                    unit_price=format(row.unit_price, "f"),
                    status=row.status,
                    cancel_reason=row.cancel_reason,
                    image_urls=presigned_urls(prod.image_keys or []) if prod else [],
                    addons=addon_map.get(int(row.catalog_product_id), []),
                )
            )
        received = db.query(CustomerOrder).filter(
            CustomerOrder.customer_id == customer_id, CustomerOrder.bucket == "received", CustomerOrder.is_open.is_(True)
        ).first()
        return CustomerOrderDetail(
            id=received.id if received else 0,
            customer_id=customer_id,
            customer_name=customer.business_name,
            bucket="open",
            open_lines=lines_out,
        )

    order = (
        db.query(CustomerOrder)
        .filter(CustomerOrder.customer_id == customer_id, CustomerOrder.bucket == bucket, CustomerOrder.is_open.is_(True))
        .first()
    )
    if not order:
        return CustomerOrderDetail(id=0, customer_id=customer_id, customer_name=customer.business_name, bucket=bucket)

    placements = (
        db.query(CustomerOrderPlacement)
        .filter(CustomerOrderPlacement.customer_order_id == order.id)
        .order_by(CustomerOrderPlacement.placed_at.asc())
        .all()
    )
    from app.services.catalog_addons import addon_snapshots_map

    all_line_cids: list[int] = []
    placement_lines: list[tuple] = []
    for p in placements:
        lines = db.query(CustomerOrderLine).filter(CustomerOrderLine.placement_id == p.id).order_by(CustomerOrderLine.id.asc()).all()
        placement_lines.append((p, lines))
        for ln in lines:
            if not ln.addons_json:
                all_line_cids.append(int(ln.catalog_product_id))
    live_addons = addon_snapshots_map(db, all_line_cids, with_images=False) if all_line_cids else {}
    pl_out: list[CustomerPlacementOut] = []
    for p, lines in placement_lines:
        pl_out.append(
            CustomerPlacementOut(
                id=p.id,
                status=p.status,
                customer_notes=p.customer_notes,
                cancel_reason=p.cancel_reason,
                placed_at=p.placed_at,
                lines=[
                    CustomerOrderLineOut(
                        id=ln.id,
                        catalog_product_id=ln.catalog_product_id,
                        our_product_id=ln.our_product_id,
                        quantity=ln.quantity,
                        quantity_billed=ln.quantity_billed,
                        unit_price=format(ln.unit_price, "f"),
                        status=ln.status,
                        cancel_reason=ln.cancel_reason,
                        addons=list(ln.addons_json or live_addons.get(int(ln.catalog_product_id), [])),
                    )
                    for ln in lines
                ],
            )
        )
    bills_out: list[CustomerBillOut] = []
    if bucket == "billed":
        from app.services.catalog_addons import addon_snapshots_map

        bills = (
            db.query(CustomerBill)
            .filter(CustomerBill.customer_id == customer_id, CustomerBill.cancelled_at.is_(None))
            .order_by(CustomerBill.created_at.desc())
            .all()
        )
        for b in bills:
            blines = db.query(CustomerBillLine).filter(CustomerBillLine.bill_id == b.id).order_by(CustomerBillLine.id.asc()).all()
            addon_by_cid: dict[int, list] = {}
            totals_lines = (b.totals_json or {}).get("lines") if isinstance(b.totals_json, dict) else None
            if isinstance(totals_lines, list):
                for tl in totals_lines:
                    if isinstance(tl, dict) and tl.get("catalog_product_id") and tl.get("addons"):
                        addon_by_cid[int(tl["catalog_product_id"])] = list(tl["addons"])
            missing = [ln.catalog_product_id for ln in blines if ln.catalog_product_id not in addon_by_cid]
            if missing:
                addon_by_cid.update(addon_snapshots_map(db, missing, with_images=False))
            bills_out.append(serialize_customer_bill(db, b, blines, addon_by_cid))
    return CustomerOrderDetail(
        id=order.id,
        customer_id=customer_id,
        customer_name=customer.business_name,
        bucket=bucket,
        placements=pl_out,
        bills=bills_out,
    )


@router.get("/customer/{customer_id}/process-context", response_model=ProcessContextOut)
def get_process_context(
    customer_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("customer_orders.read")),
):
    customer = db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(404, "customer not found")
    ctx = get_process_lines(db, customer_id)
    product_ids = [ln["catalog_product_id"] for ln in ctx["lines"]]
    products = {
        p.id: p
        for p in (
            db.query(CatalogProduct).filter(CatalogProduct.id.in_(product_ids)).all() if product_ids else []
        )
    }
    lines_out = []
    for ln in ctx["lines"]:
        prod = products.get(ln["catalog_product_id"])
        keys = (prod.image_keys or [])[:1] if prod else []
        lines_out.append(
            ProcessLineOut(
                open_line_id=ln["open_line_id"],
                catalog_product_id=ln["catalog_product_id"],
                our_product_id=ln["our_product_id"],
                unit_price=ln["unit_price"],
                quantity_placed=ln["quantity_placed"],
                quantity_open=ln["quantity_open"],
                quantity_billed=ln["quantity_billed"],
                quantity_on_hand=ln["quantity_on_hand"],
                image_urls=presigned_urls(keys),
                addons=ln.get("addons") or [],
            )
        )
    return ProcessContextOut(
        customer_id=customer_id,
        customer_name=customer.business_name,
        lines=lines_out,
        default_narration=ctx.get("default_narration") or "",
        credit=ctx.get("credit"),
    )


@router.post("/customer/{customer_id}/process/preview")
def preview_process_bill(
    customer_id: int,
    body: ProcessBillIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("customer_orders.read")),
):
    open_map = {
        r.catalog_product_id: r
        for r in db.query(CustomerOpenLine).filter(CustomerOpenLine.customer_id == customer_id, CustomerOpenLine.status == "open").all()
    }
    bill_items = []
    item_overrides = []
    use_overall = body.overall_discount_percent is not None and body.overall_discount_percent > 0
    for ln in body.lines:
        if ln.quantity_to_ship <= 0:
            continue
        row = open_map.get(ln.catalog_product_id)
        if not row:
            raise HTTPException(400, f"invalid product {ln.catalog_product_id}")
        if ln.quantity_to_ship > row.quantity_open:
            raise HTTPException(400, f"cannot ship more than open for {row.our_product_id}")
        bill_items.append({
            "catalog_product_id": ln.catalog_product_id,
            "our_product_id": row.our_product_id,
            "quantity": ln.quantity_to_ship,
            "unit_price": str(row.unit_price),
        })
        if not use_overall:
            ov: dict = {"catalog_product_id": ln.catalog_product_id}
            if ln.net_rate is not None:
                ov["override_price"] = ln.net_rate
            if ln.discount_percent is not None:
                ov["discount_percent"] = ln.discount_percent
            if "override_price" in ov or "discount_percent" in ov:
                item_overrides.append(ov)
    if not bill_items:
        raise HTTPException(400, "enter quantity to ship on at least one line")
    extra = [{"name": c.name, "amount": c.amount} for c in body.additional_charges] if body.additional_charges else None
    assert_discount_xor(body.overall_discount_percent, [ln.model_dump() for ln in body.lines])
    t = normalize_transport(
        transport_mode=body.transport_mode,
        freight_agent_id=body.freight_agent_id,
        freight_charges=body.freight_charges,
        transport_receipt_number=body.transport_receipt_number,
    )
    agent_name = None
    if t["freight_agent_id"]:
        agent = db.get(FreightAgent, t["freight_agent_id"])
        agent_name = agent.name if agent else None
    totals = compute_bill_totals(
        bill_items,
        gst_enabled=body.gst_enabled,
        gst_rate_percent=Decimal(str(body.gst_rate_percent)),
        discount_percent=Decimal(str(body.overall_discount_percent)) if use_overall else None,
        freight_charges=t["freight_charges"],
        packaging_charges=Decimal(body.packaging_charges) if body.packaging_charges else None,
        item_overrides=item_overrides if not use_overall else None,
        additional_charges=extra,
    )
    totals = stamp_transport_on_totals(totals, t, agent_name=agent_name)
    from app.services.credit_limit import credit_status

    grand = Decimal(str(totals.get("rounded_grand_total") or totals.get("grand_total") or 0))
    totals["credit"] = credit_status(db, customer_id, pending_bill=grand)
    return totals


@router.post("/customer/{customer_id}/process", status_code=201)
def submit_process_bill(
    customer_id: int,
    body: ProcessBillIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("customer_orders.write")),
):
    customer = db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(404, "customer not found")
    extra = [{"name": c.name, "amount": c.amount} for c in body.additional_charges] if body.additional_charges else None
    bill = process_customer_bill(
        db,
        customer_id=customer_id,
        customer_name=customer.business_name,
        lines_in=[ln.model_dump() for ln in body.lines],
        overall_discount_percent=Decimal(str(body.overall_discount_percent)) if body.overall_discount_percent else None,
        gst_enabled=body.gst_enabled,
        gst_rate_percent=Decimal(str(body.gst_rate_percent)),
        freight_agent_id=body.freight_agent_id,
        freight_charges=Decimal(body.freight_charges) if body.freight_charges else None,
        packaging_charges=Decimal(body.packaging_charges) if body.packaging_charges else None,
        additional_charges=extra,
        bill_series_id=body.bill_series_id,
        narration=body.narration,
        actor_type=auth.actor_type,
        actor_id=auth.actor_id,
        actor_name=auth.actor_name,
        force_credit_override=bool(body.force_credit_override),
        bill_date=body.bill_date,
        bill_number=body.bill_number,
        transport_mode=body.transport_mode,
        transport_receipt_number=body.transport_receipt_number,
        freight_charges_raw=body.freight_charges,
    )
    log_from_auth(db, auth, action="bill", entity_type="customer_order", entity_id=bill.id, entity_label=customer.business_name, detail=f"Bill {bill.bill_number}")
    # Defer PDF — generate on first document download so bill submit stays fast
    db.commit()
    response_cache.invalidate("stock:")
    response_cache.invalidate("shop:")
    response_cache.invalidate("catalog:")
    return {
        "ok": True,
        "bill_id": bill.id,
        "bill_number": bill.bill_number,
        "grand_total": format(bill.grand_total, "f"),
        "document_url": None,
        "document_key": bill.document_key,
        "transport_mode": bill.transport_mode,
        "freight_agent_id": bill.freight_agent_id,
        "freight_charges": format(bill.freight_charges, "f") if bill.freight_charges is not None else None,
    }


@router.post("/open-lines/{line_id}/cancel")
def cancel_open_line_endpoint(
    line_id: int,
    body: CancelRequest,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("customer_orders.write")),
):
    row = db.get(CustomerOpenLine, line_id)
    if not row:
        raise HTTPException(404, "line not found")
    customer = db.get(Customer, row.customer_id)
    cancel_open_line(db, line_id, body.reason, customer.business_name if customer else "")
    log_from_auth(db, auth, action="cancel", entity_type="customer_order", entity_id=row.customer_id, entity_label=customer.business_name if customer else "", detail=body.reason[:200])
    db.commit()
    response_cache.invalidate("stock:")
    response_cache.invalidate("shop:")
    response_cache.invalidate("catalog:")
    return {"ok": True}


@router.patch("/open-lines/{line_id}")
def edit_open_line_endpoint(
    line_id: int,
    body: EditQtyIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("customer_orders.write")),
):
    row = db.get(CustomerOpenLine, line_id)
    if not row:
        raise HTTPException(404, "line not found")
    customer = db.get(Customer, row.customer_id)
    try:
        edit_customer_open_qty(db, line_id, body.quantity, customer.business_name if customer else "")
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    log_from_auth(
        db, auth, action="edit_open", entity_type="customer_order",
        entity_id=row.customer_id, entity_label=customer.business_name if customer else "",
        detail=f"{row.our_product_id} → {body.quantity}",
    )
    db.commit()
    return {"ok": True, "quantity_open": body.quantity}


@router.patch("/lines/{line_id}")
def edit_placement_line_endpoint(
    line_id: int,
    body: EditQtyIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("customer_orders.write")),
):
    line = db.get(CustomerOrderLine, line_id)
    if not line:
        raise HTTPException(404, "line not found")
    placement = db.get(CustomerOrderPlacement, line.placement_id)
    order = db.get(CustomerOrder, placement.customer_order_id) if placement else None
    customer = db.get(Customer, order.customer_id) if order else None
    try:
        edit_customer_placement_line_qty(db, line_id, body.quantity, customer.business_name if customer else "")
        if body.quantity == 0:
            line.status = "cancelled"
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    log_from_auth(
        db, auth, action="edit_received", entity_type="customer_order",
        entity_id=order.customer_id if order else line_id,
        entity_label=customer.business_name if customer else "",
        detail=f"{line.our_product_id} → {body.quantity}",
    )
    db.commit()
    return {"ok": True, "quantity": body.quantity}


@router.delete("/lines/{line_id}")
def delete_placement_line_endpoint(
    line_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("customer_orders.write")),
):
    line = db.get(CustomerOrderLine, line_id)
    if not line:
        raise HTTPException(404, "line not found")
    placement = db.get(CustomerOrderPlacement, line.placement_id)
    order = db.get(CustomerOrder, placement.customer_order_id) if placement else None
    customer = db.get(Customer, order.customer_id) if order else None
    try:
        edit_customer_placement_line_qty(db, line_id, 0, customer.business_name if customer else "")
        line.status = "cancelled"
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    log_from_auth(
        db, auth, action="delete_line", entity_type="customer_order",
        entity_id=order.customer_id if order else line_id,
        entity_label=customer.business_name if customer else "",
        detail=f"removed {line.our_product_id}",
    )
    db.commit()
    return {"ok": True}


@router.put("/placements/{placement_id}")
def replace_placement_endpoint(
    placement_id: int,
    body: OfflineCustomerOrderIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("customer_orders.write")),
):
    placement = db.get(CustomerOrderPlacement, placement_id)
    if not placement:
        raise HTTPException(404, "placement not found")
    order = db.get(CustomerOrder, placement.customer_order_id)
    customer = db.get(Customer, order.customer_id) if order else None
    if not customer or customer.deleted_at:
        raise HTTPException(404, "customer not found")
    try:
        replace_received_placement(
            db,
            placement_id=placement_id,
            lines=[{"catalog_product_id": ln.catalog_product_id, "quantity": ln.quantity} for ln in body.lines],
            customer_notes=(body.narration or "").strip() or None,
            customer_name=customer.business_name,
            allow_negative_stock=True,  # admin offline edit may oversell
        )
    except ValueError as e:
        db.rollback()
        raise HTTPException(400, str(e)) from e
    log_from_auth(
        db, auth, action="replace_placement", entity_type="customer_order",
        entity_id=customer.id, entity_label=customer.business_name,
        detail=f"placement #{placement_id} · {len(body.lines)} line(s)",
    )
    db.commit()
    return {"ok": True, "placement_id": placement_id}


@router.post("/placements/{placement_id}/cancel")
def cancel_placement_endpoint(
    placement_id: int,
    body: CancelRequest,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("customer_orders.write")),
):
    placement = db.get(CustomerOrderPlacement, placement_id)
    if not placement:
        raise HTTPException(404, "placement not found")
    order = db.get(CustomerOrder, placement.customer_order_id)
    customer = db.get(Customer, order.customer_id) if order else None
    if not customer or customer.deleted_at:
        raise HTTPException(404, "customer not found")
    try:
        cancel_customer_placement(
            db,
            placement_id=placement_id,
            reason=body.reason,
            customer_name=customer.business_name,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    lines = (
        db.query(CustomerOrderLine)
        .filter(CustomerOrderLine.placement_id == placement_id)
        .all()
    )
    line_summary = ", ".join(f"{ln.our_product_id}×{ln.quantity}" for ln in lines[:12])
    log_from_auth(
        db,
        auth,
        action="cancel",
        entity_type="customer_order",
        entity_id=customer.id,
        entity_label=customer.business_name,
        detail=f"cancelled placement #{placement_id}: {line_summary} — {body.reason[:120]}",
    )
    db.commit()
    response_cache.invalidate("stock:")
    response_cache.invalidate("shop:")
    response_cache.invalidate("catalog:")
    return {"ok": True, "placement_id": placement_id}


@router.post("/bill-lines/{line_id}/close")
def close_bill_line_endpoint(
    line_id: int,
    body: CancelRequest,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("customer_orders.write")),
):
    line = db.get(CustomerBillLine, line_id)
    if not line:
        raise HTTPException(404, "bill line not found")
    bill = db.get(CustomerBill, line.bill_id)
    customer = db.get(Customer, bill.customer_id) if bill else None
    close_bill_line(db, line_id, body.reason)
    log_from_auth(
        db,
        auth,
        action="close",
        entity_type="customer_order",
        entity_id=line.id,
        entity_label=customer.business_name if customer else "",
        detail=f"{line.our_product_id} — {body.reason[:200]}",
    )
    db.commit()
    return {"ok": True}


@router.get("/bills/{bill_id}", response_model=CustomerBillOut)
def get_bill_detail(
    bill_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("customer_orders.read")),
):
    bill = db.get(CustomerBill, bill_id)
    if not bill:
        raise HTTPException(404, "bill not found")
    blines = (
        db.query(CustomerBillLine)
        .filter(CustomerBillLine.bill_id == bill.id)
        .order_by(CustomerBillLine.id.asc())
        .all()
    )
    from app.services.catalog_addons import addon_snapshots_map

    addon_by_cid = addon_snapshots_map(db, [ln.catalog_product_id for ln in blines], with_images=False)
    return serialize_customer_bill(db, bill, blines, addon_by_cid)


@router.post("/bills/{bill_id}/cancel")
def cancel_bill_endpoint(
    bill_id: int,
    body: CancelRequest,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("customer_orders.write")),
):
    bill = db.get(CustomerBill, bill_id)
    if not bill:
        raise HTTPException(404, "bill not found")
    customer = db.get(Customer, bill.customer_id)
    try:
        cancelled = cancel_customer_bill(
            db,
            bill_id=bill_id,
            reason=body.reason,
            actor_name=auth.actor_name,
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    log_from_auth(
        db, auth, action="cancel_bill", entity_type="customer_order",
        entity_id=cancelled.id, entity_label=customer.business_name if customer else "",
        detail=f"Bill {cancelled.bill_number} cancelled — {body.reason[:120]}",
    )
    db.commit()
    response_cache.invalidate("stock:")
    response_cache.invalidate("shop:")
    response_cache.invalidate("catalog:")
    return {"ok": True, "bill_id": cancelled.id, "bill_number": cancelled.bill_number}


@router.put("/bills/{bill_id}")
def update_bill_endpoint(
    bill_id: int,
    body: EditBillIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("customer_orders.write")),
):
    bill = db.get(CustomerBill, bill_id)
    if not bill:
        raise HTTPException(404, "bill not found")
    if bill.cancelled_at:
        raise HTTPException(400, "bill cancelled")
    customer = db.get(Customer, bill.customer_id)
    extra = [{"name": c.name, "amount": c.amount} for c in body.additional_charges] if body.additional_charges else None
    try:
        updated = edit_customer_bill(
            db,
            bill_id=bill_id,
            lines_in=[ln.model_dump() for ln in body.lines],
            overall_discount_percent=Decimal(str(body.overall_discount_percent)) if body.overall_discount_percent else None,
            gst_enabled=body.gst_enabled,
            gst_rate_percent=Decimal(str(body.gst_rate_percent)),
            freight_agent_id=body.freight_agent_id,
            freight_charges=Decimal(body.freight_charges) if body.freight_charges else None,
            packaging_charges=Decimal(body.packaging_charges) if body.packaging_charges else None,
            additional_charges=extra,
            narration=body.narration,
            actor_type=auth.actor_type,
            actor_id=auth.actor_id,
            actor_name=auth.actor_name,
            force_credit_override=bool(body.force_credit_override),
            bill_number=body.bill_number,
            transport_mode=body.transport_mode,
            transport_receipt_number=body.transport_receipt_number,
            freight_charges_raw=body.freight_charges,
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    log_from_auth(
        db, auth, action="edit_bill", entity_type="customer_order",
        entity_id=updated.id, entity_label=customer.business_name if customer else "",
        detail=f"Bill {updated.bill_number} edited · {len(body.lines)} line(s) · ₹{updated.grand_total}",
    )
    db.commit()
    response_cache.invalidate("stock:")
    response_cache.invalidate("shop:")
    response_cache.invalidate("catalog:")
    return {
        "ok": True,
        "bill_id": updated.id,
        "bill_number": updated.bill_number,
        "grand_total": format(updated.grand_total, "f"),
    }


@router.patch("/bills/{bill_id}/number")
def patch_bill_number(
    bill_id: int,
    body: PatchBillNumberIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("customer_orders.write")),
):
    """TEMP: allow correcting a bill number without rewriting lines."""
    bill = db.get(CustomerBill, bill_id)
    if not bill:
        raise HTTPException(404, "bill not found")
    if bill.cancelled_at:
        raise HTTPException(400, "cannot edit — bill cancelled")
    new_num = (body.bill_number or "").strip()
    if not new_num:
        raise HTTPException(400, "bill number required")
    clash = (
        db.query(CustomerBill)
        .filter(
            CustomerBill.bill_number == new_num,
            CustomerBill.id != bill.id,
            CustomerBill.cancelled_at.is_(None),
        )
        .first()
    )
    if clash:
        raise HTTPException(400, f"bill number {new_num} already used on another open bill")
    old = bill.bill_number
    bill.bill_number = new_num
    bill.document_key = None
    customer = db.get(Customer, bill.customer_id)
    log_from_auth(
        db, auth, action="edit_bill_number", entity_type="customer_order",
        entity_id=bill.id, entity_label=customer.business_name if customer else "",
        detail=f"{old} → {new_num}",
    )
    db.commit()
    return {"ok": True, "bill_id": bill.id, "bill_number": bill.bill_number}


@router.get("/bills/{bill_id}/document")
def get_bill_document(
    bill_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("customer_orders.read")),
):
    bill = db.get(CustomerBill, bill_id)
    if not bill:
        raise HTTPException(404, "bill not found")
    if storage_configured():
        try:
            generate_customer_bill_document(db, bill.id)
            db.commit()
        except Exception:
            db.rollback()
    if not bill.document_key:
        raise HTTPException(404, "document not available")
    url = presigned_url(bill.document_key)
    if not url:
        raise HTTPException(503, "storage not available")
    return {"document_url": url, "document_key": bill.document_key, "bill_number": bill.bill_number}


@router.get("/closeable", response_model=List[CloseableItemOut])
def list_closeable_bill_lines(
    customer_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("customer_orders.read")),
):
    q = (
        db.query(CustomerBillLine, CustomerBill, Customer)
        .join(CustomerBill, CustomerBillLine.bill_id == CustomerBill.id)
        .join(Customer, CustomerBill.customer_id == Customer.id)
        .filter(CustomerBillLine.status == "billed")
    )
    if customer_id is not None:
        q = q.filter(CustomerBill.customer_id == customer_id)
    rows = q.order_by(CustomerBill.created_at.desc()).all()
    return [
        CloseableItemOut(
            id=line.id,
            item_type="bill_line",
            label=f"{line.our_product_id} × {line.quantity_shipped}",
            sublabel=f"Bill {bill.bill_number}",
            customer_id=customer.id,
            customer_name=customer.business_name,
            quantity=line.quantity_shipped,
            amount=format(line.line_total, "f"),
        )
        for line, bill, customer in rows
    ]


@router.post("/close-batch")
def close_batch_bill_lines(
    body: CloseBatchIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("customer_orders.write")),
):
    closed = 0
    labels: list[str] = []
    for lid in body.bill_line_ids:
        try:
            line = db.get(CustomerBillLine, lid)
            close_bill_line(db, lid, body.reason)
            closed += 1
            if line:
                labels.append(line.our_product_id)
        except HTTPException:
            continue
    if closed:
        log_from_auth(
            db,
            auth,
            action="close",
            entity_type="customer_order",
            entity_id=None,
            entity_label=None,
            detail=f"closed {closed} bill lines: {', '.join(labels[:10])}",
        )
    db.commit()
    return {"ok": True, "closed": closed}


@router.post("/customer/{customer_id}/offline/preview")
def preview_offline_order(
    customer_id: int,
    body: OfflineCustomerOrderIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("customer_orders.read")),
):
    """Preview lines + est. total before placing into received (no bill yet)."""
    customer = db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(404, "customer not found")
    from app.models.stock import StockBalance

    lines_out = []
    stock_warnings = []
    subtotal = Decimal("0")
    for ln in body.lines:
        if int(ln.quantity or 0) <= 0:
            continue
        prod = db.get(CatalogProduct, int(ln.catalog_product_id))
        if not prod:
            continue
        qty = int(ln.quantity)
        unit = Decimal(str(prod.selling_price or 0))
        line_total = (unit * qty).quantize(Decimal("0.01"))
        subtotal += line_total
        bal = db.query(StockBalance).filter(StockBalance.catalog_product_id == prod.id).first()
        on_hand = int(bal.quantity_on_hand or 0) if bal else 0
        short = on_hand < qty
        if short:
            stock_warnings.append({
                "catalog_product_id": prod.id,
                "our_product_id": prod.our_product_id,
                "quantity": qty,
                "on_hand": on_hand,
                "message": f"{prod.our_product_id}: need {qty}, have {on_hand} — will go negative",
            })
        lines_out.append({
            "catalog_product_id": prod.id,
            "our_product_id": prod.our_product_id,
            "quantity": qty,
            "unit_price": format(unit, "f"),
            "line_total": format(line_total, "f"),
            "on_hand": on_hand,
            "out_of_stock": short,
        })
    if not lines_out:
        raise HTTPException(400, "enter quantity on at least one line")
    return {
        "customer_id": customer_id,
        "customer_name": customer.business_name,
        "lines": lines_out,
        "subtotal": format(subtotal, "f"),
        "stock_warnings": stock_warnings,
        "narration": body.narration,
        "note": "Order goes to Received. Bill later via Process Order.",
    }


@router.post("/customer/{customer_id}/offline", status_code=201)
def create_offline_customer_order(
    customer_id: int,
    body: OfflineCustomerOrderIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("customer_orders.write")),
):
    """Place order into Received — same path as customer portal order."""
    customer = db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(404, "customer not found")
    try:
        placement = create_received_placement(
            db,
            customer_id=customer_id,
            customer_name=customer.business_name,
            lines=[{"catalog_product_id": ln.catalog_product_id, "quantity": ln.quantity} for ln in body.lines],
            customer_notes=(body.narration or "").strip() or "Order placed by admin (phone)",
            placed_on=body.placed_on,
            allow_negative_stock=True,  # offline admin may oversell; portal stays strict
        )
    except ValueError as e:
        db.rollback()
        raise HTTPException(400, str(e)) from e

    # Defer PDF — sync S3/PDF was hanging the Save button for 30–90s
    log_from_auth(
        db, auth, action="offline_order", entity_type="customer_order",
        entity_id=placement.id, entity_label=customer.business_name,
        detail=f"Received placement #{placement.id}",
    )
    db.commit()
    return {
        "ok": True,
        "placement_id": placement.id,
        "bucket": "received",
        "order_document_url": None,
        "message": "Order placed in Received — process to bill when ready",
    }
