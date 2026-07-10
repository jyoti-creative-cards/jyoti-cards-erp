from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import AuthContext, require_permission
from app.models.catalog_product import CatalogProduct
from app.models.customer import Customer
from app.models.customer_bill import CustomerBill, CustomerBillLine
from app.models.customer_order import CustomerOpenLine, CustomerOrder, CustomerOrderLine, CustomerOrderPlacement
from app.schemas.customer_order import (
    CancelRequest,
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

from app.services.activity import log_from_auth
from app.services.customer_bill_math import compute_bill_totals
from app.services.customer_bill_process import (
    cancel_open_line,
    close_bill_line,
    get_process_lines,
    process_customer_bill,
    process_offline_customer_order,
)
from app.services.doc_gen import generate_customer_bill_document, generate_customer_order_document
from app.services.storage import presigned_url, storage_configured

router = APIRouter(prefix="/customer-orders", tags=["customer-orders"])


def _customer_name(db: Session, customer_id: int) -> str:
    c = db.get(Customer, customer_id)
    return c.business_name if c else f"Customer #{customer_id}"


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
    return CustomerOrderSummary(
        id=order.id,
        customer_id=order.customer_id,
        customer_name=_customer_name(db, order.customer_id),
        bucket=order.bucket,
        placement_count=placements,
        line_count=len(lines),
        total_quantity=total,
        updated_at=order.updated_at,
    )


@router.get("", response_model=List[CustomerOrderSummary])
def list_customer_orders(
    bucket: str = Query("summary", pattern="^(summary|received|open|billed|cancelled|closed)$"),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.read")),
):
    if bucket == "summary":
        customer_ids = set()
        for row in db.query(CustomerOrder.customer_id).filter(CustomerOrder.is_open.is_(True)).distinct().all():
            customer_ids.add(row[0])
        open_rows = (
            db.query(CustomerOpenLine.customer_id)
            .filter(CustomerOpenLine.status == "open", CustomerOpenLine.quantity_open > 0)
            .distinct()
            .all()
        )
        for row in open_rows:
            customer_ids.add(row[0])
        out: list[CustomerOrderSummary] = []
        for cid in sorted(customer_ids):
            customer = db.get(Customer, cid)
            if not customer:
                continue
            received = db.query(CustomerOrder).filter(CustomerOrder.customer_id == cid, CustomerOrder.bucket == "received", CustomerOrder.is_open.is_(True)).first()
            placements = 0
            if received:
                placements = db.query(CustomerOrderPlacement).filter(CustomerOrderPlacement.customer_order_id == received.id).count()
            open_qty = (
                db.query(func.coalesce(func.sum(CustomerOpenLine.quantity_open), 0))
                .filter(CustomerOpenLine.customer_id == cid, CustomerOpenLine.status == "open")
                .scalar()
            ) or 0
            open_lines = (
                db.query(func.count(CustomerOpenLine.id))
                .filter(CustomerOpenLine.customer_id == cid, CustomerOpenLine.status == "open", CustomerOpenLine.quantity_open > 0)
                .scalar()
            ) or 0
            billed = db.query(CustomerOrder).filter(CustomerOrder.customer_id == cid, CustomerOrder.bucket == "billed", CustomerOrder.is_open.is_(True)).first()
            updated = datetime.now(timezone.utc)
            if billed:
                updated = billed.updated_at
            elif received:
                updated = received.updated_at
            out.append(
                CustomerOrderSummary(
                    id=received.id if received else (billed.id if billed else 0),
                    customer_id=cid,
                    customer_name=customer.business_name,
                    bucket="summary",
                    placement_count=int(placements),
                    line_count=int(open_lines),
                    total_quantity=int(open_qty),
                    updated_at=updated,
                )
            )
        out.sort(key=lambda x: x.customer_name.lower())
        return out

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
        out: list[CustomerOrderSummary] = []
        for customer_id, total_qty, line_count in rows:
            received = (
                db.query(CustomerOrder)
                .filter(CustomerOrder.customer_id == customer_id, CustomerOrder.bucket == "received", CustomerOrder.is_open.is_(True))
                .first()
            )
            out.append(
                CustomerOrderSummary(
                    id=received.id if received else 0,
                    customer_id=int(customer_id),
                    customer_name=_customer_name(db, int(customer_id)),
                    bucket="open",
                    placement_count=0,
                    line_count=int(line_count or 0),
                    total_quantity=int(total_qty or 0),
                    updated_at=datetime.now(timezone.utc),
                )
            )
        out.sort(key=lambda x: x.customer_name.lower())
        return out

    orders = (
        db.query(CustomerOrder)
        .filter(CustomerOrder.is_open.is_(True), CustomerOrder.bucket == bucket)
        .order_by(CustomerOrder.updated_at.desc())
        .all()
    )
    return [_summary(db, o) for o in orders]


@router.get("/customer/{customer_id}", response_model=CustomerOrderDetail)
def get_customer_order_detail(
    customer_id: int,
    bucket: str = Query("received", pattern="^(received|open|billed|cancelled|closed)$"),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.read")),
):
    customer = db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(404, "customer not found")

    if bucket == "open":
        open_lines = (
            db.query(CustomerOpenLine)
            .filter(CustomerOpenLine.customer_id == customer_id, CustomerOpenLine.status == "open", CustomerOpenLine.quantity_open > 0)
            .order_by(CustomerOpenLine.our_product_id.asc())
            .all()
        )
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
    pl_out: list[CustomerPlacementOut] = []
    for p in placements:
        lines = db.query(CustomerOrderLine).filter(CustomerOrderLine.placement_id == p.id).order_by(CustomerOrderLine.id.asc()).all()
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
                    )
                    for ln in lines
                ],
            )
        )
    bills_out: list[CustomerBillOut] = []
    if bucket == "billed":
        bills = (
            db.query(CustomerBill)
            .filter(CustomerBill.customer_id == customer_id)
            .order_by(CustomerBill.created_at.desc())
            .all()
        )
        for b in bills:
            blines = db.query(CustomerBillLine).filter(CustomerBillLine.bill_id == b.id).order_by(CustomerBillLine.id.asc()).all()
            bills_out.append(
                CustomerBillOut(
                    id=b.id,
                    bill_number=b.bill_number,
                    grand_total=format(b.grand_total, "f"),
                    narration=b.narration,
                    created_at=b.created_at,
                    lines=[
                        CustomerBillLineOut(
                            id=ln.id,
                            bill_id=b.id,
                            bill_number=b.bill_number,
                            our_product_id=ln.our_product_id,
                            quantity_shipped=ln.quantity_shipped,
                            unit_price=format(ln.unit_price, "f"),
                            line_total=format(ln.line_total, "f"),
                            status=ln.status,
                            close_reason=ln.close_reason,
                        )
                        for ln in blines
                    ],
                )
            )
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
    auth: AuthContext = Depends(require_permission("vendor_orders.read")),
):
    customer = db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(404, "customer not found")
    ctx = get_process_lines(db, customer_id)
    lines_out = []
    for ln in ctx["lines"]:
        prod = db.get(CatalogProduct, ln["catalog_product_id"])
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
                image_urls=presigned_urls(prod.image_keys or []) if prod else [],
            )
        )
    return ProcessContextOut(
        customer_id=customer_id,
        customer_name=customer.business_name,
        lines=lines_out,
        default_narration=ctx.get("default_narration") or "",
    )


@router.post("/customer/{customer_id}/process/preview")
def preview_process_bill(
    customer_id: int,
    body: ProcessBillIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.read")),
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
        if not use_overall and ln.discount_percent is not None:
            item_overrides.append({"catalog_product_id": ln.catalog_product_id, "discount_percent": ln.discount_percent})
    if not bill_items:
        raise HTTPException(400, "enter quantity to ship on at least one line")
    extra = [{"name": c.name, "amount": c.amount} for c in body.additional_charges] if body.additional_charges else None
    return compute_bill_totals(
        bill_items,
        gst_enabled=body.gst_enabled,
        gst_rate_percent=Decimal(str(body.gst_rate_percent)),
        discount_percent=Decimal(str(body.overall_discount_percent)) if use_overall else None,
        freight_charges=Decimal(body.freight_charges) if body.freight_charges else None,
        packaging_charges=Decimal(body.packaging_charges) if body.packaging_charges else None,
        item_overrides=item_overrides if not use_overall else None,
        additional_charges=extra,
    )


@router.post("/customer/{customer_id}/process", status_code=201)
def submit_process_bill(
    customer_id: int,
    body: ProcessBillIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.write")),
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
    )
    log_from_auth(db, auth, action="bill", entity_type="customer_order", entity_id=bill.id, entity_label=customer.business_name, detail=f"Bill {bill.bill_number}")
    doc_url = None
    if storage_configured():
        try:
            key = generate_customer_bill_document(db, bill.id)
            doc_url = presigned_url(key) if key else None
        except Exception:
            pass
    db.commit()
    return {"ok": True, "bill_id": bill.id, "bill_number": bill.bill_number, "grand_total": format(bill.grand_total, "f"), "document_url": doc_url, "document_key": bill.document_key}


@router.post("/open-lines/{line_id}/cancel")
def cancel_open_line_endpoint(
    line_id: int,
    body: CancelRequest,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.write")),
):
    row = db.get(CustomerOpenLine, line_id)
    if not row:
        raise HTTPException(404, "line not found")
    customer = db.get(Customer, row.customer_id)
    cancel_open_line(db, line_id, body.reason, customer.business_name if customer else "")
    log_from_auth(db, auth, action="cancel", entity_type="customer_order", entity_id=row.customer_id, entity_label=customer.business_name if customer else "", detail=body.reason[:200])
    db.commit()
    return {"ok": True}


@router.post("/bill-lines/{line_id}/close")
def close_bill_line_endpoint(
    line_id: int,
    body: CancelRequest,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.write")),
):
    close_bill_line(db, line_id, body.reason)
    db.commit()
    return {"ok": True}


@router.get("/bills/{bill_id}/document")
def get_bill_document(
    bill_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.read")),
):
    bill = db.get(CustomerBill, bill_id)
    if not bill:
        raise HTTPException(404, "bill not found")
    if not bill.document_key and storage_configured():
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
    auth: AuthContext = Depends(require_permission("vendor_orders.read")),
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
    auth: AuthContext = Depends(require_permission("vendor_orders.write")),
):
    closed = 0
    for lid in body.bill_line_ids:
        try:
            close_bill_line(db, lid, body.reason)
            closed += 1
        except HTTPException:
            continue
    db.commit()
    return {"ok": True, "closed": closed}


def _offline_body_dict(body: OfflineCustomerOrderIn) -> dict:
    extra = [{"name": c.name, "amount": c.amount} for c in body.additional_charges if c.name.strip() and c.amount.strip()]
    return {
        "lines": [{"catalog_product_id": ln.catalog_product_id, "quantity": ln.quantity, "discount_percent": ln.discount_percent} for ln in body.lines],
        "overall_discount_percent": body.overall_discount_percent,
        "gst_enabled": body.gst_enabled,
        "gst_rate_percent": body.gst_rate_percent,
        "additional_charges": extra,
        "bill_series_id": body.bill_series_id,
        "narration": body.narration,
    }


@router.post("/customer/{customer_id}/offline/preview")
def preview_offline_order(
    customer_id: int,
    body: OfflineCustomerOrderIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.read")),
):
    customer = db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(404, "customer not found")
    d = _offline_body_dict(body)
    bill_items = []
    item_overrides = []
    use_overall = d["overall_discount_percent"] is not None and d["overall_discount_percent"] > 0
    for ln in d["lines"]:
        if int(ln.get("quantity") or 0) <= 0:
            continue
        prod = db.get(CatalogProduct, int(ln["catalog_product_id"]))
        if not prod:
            continue
        bill_items.append({
            "catalog_product_id": prod.id,
            "our_product_id": prod.our_product_id,
            "name": prod.our_product_id,
            "quantity": int(ln["quantity"]),
            "unit_price": format(prod.selling_price or 0, "f"),
        })
        if not use_overall and ln.get("discount_percent") is not None:
            item_overrides.append({"catalog_product_id": prod.id, "discount_percent": ln["discount_percent"]})
    if not bill_items:
        raise HTTPException(400, "enter quantity on at least one line")
    return compute_bill_totals(
        bill_items,
        gst_enabled=d["gst_enabled"],
        gst_rate_percent=Decimal(str(d["gst_rate_percent"])),
        discount_percent=Decimal(str(d["overall_discount_percent"])) if use_overall else None,
        item_overrides=item_overrides if not use_overall else None,
        additional_charges=d["additional_charges"],
    )


@router.post("/customer/{customer_id}/offline", status_code=201)
def create_offline_customer_order(
    customer_id: int,
    body: OfflineCustomerOrderIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.write")),
):
    customer = db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(404, "customer not found")
    d = _offline_body_dict(body)
    bill, placement = process_offline_customer_order(
        db,
        customer_id=customer_id,
        customer_name=customer.business_name,
        lines_in=d["lines"],
        overall_discount_percent=Decimal(str(d["overall_discount_percent"])) if d["overall_discount_percent"] else None,
        gst_enabled=d["gst_enabled"],
        gst_rate_percent=Decimal(str(d["gst_rate_percent"])),
        additional_charges=d["additional_charges"],
        bill_series_id=d["bill_series_id"],
        narration=d["narration"],
        actor_type=auth.actor_type,
        actor_id=auth.actor_id,
        actor_name=auth.actor_name,
    )
    log_from_auth(db, auth, action="offline_order", entity_type="customer_order", entity_id=placement.id, entity_label=customer.business_name, detail=f"Bill {bill.bill_number}")
    bill_doc_url = None
    order_doc_url = None
    if storage_configured():
        try:
            bkey = generate_customer_bill_document(db, bill.id)
            bill_doc_url = presigned_url(bkey) if bkey else None
            okey = generate_customer_order_document(db, placement.id)
            order_doc_url = presigned_url(okey) if okey else None
        except Exception:
            pass
    db.commit()
    return {
        "ok": True,
        "bill_id": bill.id,
        "bill_number": bill.bill_number,
        "placement_id": placement.id,
        "grand_total": format(bill.grand_total, "f"),
        "bill_document_url": bill_doc_url,
        "order_document_url": order_doc_url,
    }
