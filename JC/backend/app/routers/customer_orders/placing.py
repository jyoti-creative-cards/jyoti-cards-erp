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

@router.get("/placements/{placement_id}", response_model=CustomerPlacementOut)
def get_placement_detail(
    placement_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("customer_orders.read")),
):
    placement = db.get(CustomerOrderPlacement, placement_id)
    if not placement:
        raise HTTPException(404, "order not found")
    lines = (
        db.query(CustomerOrderLine)
        .filter(CustomerOrderLine.placement_id == placement.id)
        .order_by(CustomerOrderLine.id.asc())
        .all()
    )
    view = present(db, "customer_order", placement)
    card_names = {
        int(cl["catalog_product_id"]): cl.get("our_product_id")
        for cl in (view.get("lines") or [])
        if isinstance(cl, dict) and cl.get("catalog_product_id")
    }
    return CustomerPlacementOut(
        id=placement.id,
        status=view.get("status") or placement.status,
        customer_notes=placement.customer_notes,
        cancel_reason=placement.cancel_reason,
        placed_at=placement.placed_at,
        display_date=view.get("display_date") or placement.placed_at,
        display_name=view.get("display_name") or f"Order #{placement.id}",
        deleted_at=placement.deleted_at,
        deleted_reason=placement.deleted_reason,
        lines=[
            CustomerOrderLineOut(
                id=ln.id,
                catalog_product_id=ln.catalog_product_id,
                our_product_id=card_names.get(int(ln.catalog_product_id)) or ln.our_product_id,
                quantity=ln.quantity,
                quantity_billed=ln.quantity_billed,
                unit_price=format(ln.unit_price, "f"),
                status=ln.status,
                cancel_reason=ln.cancel_reason,
                addons=[],
            )
            for ln in lines
        ],
    )

@router.post("/placements/{placement_id}/void", dependencies=[Depends(require_admin)])
def void_placement_endpoint(
    placement_id: int,
    body: VoidIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    result = void_customer_placement(db, auth, placement_id, body.reason)
    response_cache.invalidate("stock:")
    response_cache.invalidate("shop:")
    return result

@router.post("/customer/{customer_id}/confirm", dependencies=[Depends(require_permission("customer_orders.write"))])
def confirm_customer_order(
    customer_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("customer_orders.write")),
):
    """Move a customer's received (New) order to the confirmed (open) bucket."""
    from app.services.customer_order_flow import confirm_received_order

    customer = db.get(Customer, customer_id)
    if not customer or customer.deleted_at:
        raise HTTPException(404, "customer not found")
    confirmed = confirm_received_order(db, customer_id)
    if not confirmed:
        raise HTTPException(400, "no pending received order to confirm")
    log_from_auth(
        db, auth,
        action="confirm",
        entity_type="customer_order",
        entity_id=customer_id,
        entity_label=customer.business_name,
        detail="Confirmed received order → open",
    )
    db.commit()
    return {"ok": True, "customer_id": customer_id}

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

    wanted = []
    for ln in body.lines:
        if int(ln.quantity or 0) <= 0:
            continue
        wanted.append((int(ln.catalog_product_id), int(ln.quantity)))
    product_ids = list({cid for cid, _ in wanted})
    products = {
        p.id: p
        for p in db.query(CatalogProduct).filter(CatalogProduct.id.in_(product_ids)).all()
    } if product_ids else {}
    balances = {
        int(b.catalog_product_id): int(b.quantity_on_hand or 0)
        for b in db.query(StockBalance).filter(StockBalance.catalog_product_id.in_(product_ids)).all()
    } if product_ids else {}
    lines_out = []
    stock_warnings = []
    subtotal = Decimal("0")
    for cid, qty in wanted:
        prod = products.get(cid)
        if not prod:
            continue
        unit = Decimal(str(prod.selling_price or 0))
        line_total = (unit * qty).quantize(Decimal("0.01"))
        subtotal += line_total
        on_hand = balances.get(prod.id, 0)
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
        "note": "Offline order goes straight to Confirmed. Bill it from there.",
    }

@router.post("/customer/{customer_id}/offline", status_code=201)
def create_offline_customer_order(
    customer_id: int,
    body: OfflineCustomerOrderIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("customer_orders.write")),
):
    """Staff order for the customer. Skip New and land in Confirmed."""
    from app.services.customer_order_flow import promote_placement_to_confirmed

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
            order_source="offline",
            placed_by_name="Admin" if auth.actor_type == "admin" else (auth.actor_name or "Staff"),
        )
        promote_placement_to_confirmed(db, placement)
    except ValueError as e:
        db.rollback()
        raise HTTPException(400, str(e)) from e

    # Defer PDF — sync S3/PDF was hanging the Save button for 30–90s
    log_from_auth(
        db, auth, action="offline_order", entity_type="customer_order",
        entity_id=placement.id, entity_label=customer.business_name,
        detail=f"Confirmed placement #{placement.id}",
    )
    db.commit()
    return {
        "ok": True,
        "placement_id": placement.id,
        "bucket": "open",
        "order_document_url": None,
        "message": "Order placed in Confirmed — bill when ready",
    }

