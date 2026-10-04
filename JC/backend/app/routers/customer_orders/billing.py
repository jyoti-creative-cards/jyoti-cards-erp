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
from app.services.document_present import present
from app.services import response_cache
from app.services.storage import presigned_url, storage_configured
from app.schemas.stock import VoidIn
from app.services.void_service import void_customer_bill, void_customer_placement

from app.routers.customer_orders.router import router

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
                marking=prod.marking if prod else None,
            )
        )
    city = db.get(City, customer.city_id) if customer.city_id else None
    return ProcessContextOut(
        customer_id=customer_id,
        customer_name=customer.business_name,
        lines=lines_out,
        default_narration=ctx.get("default_narration") or "",
        credit=ctx.get("credit"),
        party_number=getattr(customer, "party_number", None),
        marker_1=getattr(customer, "marker_1", None),
        marker_2=getattr(customer, "marker_2", None),
        payment_type=getattr(customer, "payment_type", None),
        city_name=city.name if city else None,
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
    response_cache.invalidate("ledger")
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

@router.post("/bills/{bill_id}/void", dependencies=[Depends(require_admin)])
def void_bill_endpoint(
    bill_id: int,
    body: VoidIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    result = void_customer_bill(db, auth, bill_id, body.reason)
    response_cache.invalidate("stock:")
    response_cache.invalidate("shop:")
    response_cache.invalidate("catalog:")
    return result

@router.post("/bills/{bill_id}/edit-preview")
def preview_edit_bill_endpoint(
    bill_id: int,
    body: EditBillIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("customer_orders.read")),
):
    """Read-only: same totals math PUT /bills/{id} will actually save (incl. GST +
    additional charges) — lets the edit-bill review screen show a real number instead
    of a divergent client-side estimate that silently dropped GST/extra charges."""
    from app.services.customer_bill_process import preview_edit_customer_bill

    extra = [{"name": c.name, "amount": c.amount} for c in body.additional_charges] if body.additional_charges else None
    totals = preview_edit_customer_bill(
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
        transport_mode=body.transport_mode,
        transport_receipt_number=body.transport_receipt_number,
        freight_charges_raw=body.freight_charges,
    )
    db.rollback()  # this endpoint must never persist — _prepare_edit_bill_totals only reads
    return totals

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
    response_cache.invalidate("ledger")
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

    # If the corrected number falls inside an active series' range, bump that
    # series' cursor forward so the *next* auto-allocated number doesn't collide
    # with this manually-set one and jam billing for everyone else on the series.
    from app.models.bill_series import BillSeries

    for series in db.query(BillSeries).filter(BillSeries.is_active.is_(True)).all():
        prefix = series.prefix or ""
        if prefix and not new_num.startswith(prefix):
            continue
        suffix = new_num[len(prefix):]
        if not suffix.isdigit():
            continue
        num = int(suffix)
        if series.start_num <= num <= series.end_num and num > series.current_num:
            series.current_num = num

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
        except Exception as exc:
            db.rollback()
            import logging
            logging.getLogger(__name__).exception("bill PDF generate failed for %s", bill_id)
            raise HTTPException(500, f"document generation failed: {exc}") from exc
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

