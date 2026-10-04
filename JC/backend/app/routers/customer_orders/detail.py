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
    products_by_id: dict | None = None,
    agent_names: dict | None = None,
) -> CustomerBillOut:
    if agent_names is not None:
        agent_name = agent_names.get(bill.freight_agent_id) if bill.freight_agent_id else None
    elif bill.freight_agent_id:
        agent = db.get(FreightAgent, bill.freight_agent_id)
        agent_name = agent.name if agent else None
    else:
        agent_name = None
    mode = bill.transport_mode or ("bus" if bill.freight_agent_id else "self_pickup")
    bline_cids = [int(ln.catalog_product_id) for ln in blines if ln.catalog_product_id]
    if products_by_id is None:
        products_by_id = {
            p.id: p
            for p in (db.query(CatalogProduct).filter(CatalogProduct.id.in_(bline_cids)).all() if bline_cids else [])
        }
    names = {int(pid): prod.our_product_id for pid, prod in products_by_id.items()}
    marking_by_cid = {int(pid): prod.marking for pid, prod in products_by_id.items()}
    if bill.deleted_at:
        bill_status = "voided"
    elif bill.cancelled_at:
        bill_status = "cancelled"
    elif bill.closed_at:
        bill_status = "closed"
    else:
        bill_status = "open"
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
        display_date=bill.bill_date or bill.created_at,
        display_name=f"Bill {bill.bill_number}" if bill.bill_number else f"Bill #{bill.id}",
        status=bill_status,
        transport_mode=mode,
        transport_receipt_number=bill.transport_receipt_number,
        freight_agent_name=agent_name,
        cancelled_at=bill.cancelled_at,
        cancel_reason=bill.cancel_reason,
        deleted_at=bill.deleted_at,
        deleted_reason=bill.deleted_reason,
        lines=[
            CustomerBillLineOut(
                id=ln.id,
                bill_id=bill.id,
                bill_number=bill.bill_number,
                catalog_product_id=ln.catalog_product_id,
                our_product_id=names.get(int(ln.catalog_product_id)) or ln.our_product_id,
                quantity_shipped=ln.quantity_shipped,
                unit_price=format(ln.unit_price, "f"),
                line_total=format(ln.line_total, "f"),
                discount_percent=format(ln.discount_percent, "f") if ln.discount_percent is not None else None,
                net_rate=_line_net_rate(bill, ln),
                status=ln.status,
                close_reason=ln.close_reason,
                addons=addon_by_cid.get(int(ln.catalog_product_id), []),
                marking=marking_by_cid.get(int(ln.catalog_product_id)),
            )
            for ln in blines
        ],
    )

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
        product_ids = [r.catalog_product_id for r in open_lines]
        products = {
            p.id: p
            for p in (
                db.query(CatalogProduct).filter(CatalogProduct.id.in_(product_ids)).all()
                if product_ids else []
            )
        }
        lines_out: list[CustomerOpenLineOut] = []
        for row in open_lines:
            prod = products.get(row.catalog_product_id)
            first_key = ((prod.image_keys or [])[:1] if prod else [])
            lines_out.append(
                CustomerOpenLineOut(
                    id=row.id,
                    catalog_product_id=row.catalog_product_id,
                    our_product_id=prod.our_product_id if prod else row.our_product_id,
                    quantity_received=row.quantity_received,
                    quantity_open=row.quantity_open,
                    quantity_billed=row.quantity_billed,
                    unit_price=format(row.unit_price, "f"),
                    status=row.status,
                    cancel_reason=row.cancel_reason,
                    image_urls=presigned_urls(first_key) if first_key else [],
                    addons=addon_map.get(int(row.catalog_product_id), []),
                    marking=prod.marking if prod else None,
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
        .filter(CustomerOrderPlacement.customer_order_id == order.id, CustomerOrderPlacement.deleted_at.is_(None))
        .order_by(CustomerOrderPlacement.placed_at.asc())
        .all()
    )
    from app.services.catalog_addons import addon_snapshots_map

    all_line_cids: list[int] = []
    missing_addon_cids: list[int] = []
    placement_ids = [p.id for p in placements]
    lines_by_placement: dict[int, list] = defaultdict(list)
    if placement_ids:
        for ln in (
            db.query(CustomerOrderLine)
            .filter(CustomerOrderLine.placement_id.in_(placement_ids))
            .order_by(CustomerOrderLine.id.asc())
            .all()
        ):
            lines_by_placement[ln.placement_id].append(ln)
            all_line_cids.append(int(ln.catalog_product_id))
            if not ln.addons_json:
                missing_addon_cids.append(int(ln.catalog_product_id))
    live_addons = addon_snapshots_map(db, missing_addon_cids, with_images=False) if missing_addon_cids else {}
    from app.services.document_present import live_product_names

    names = live_product_names(db, all_line_cids)
    marking_by_cid = {
        p.id: p.marking
        for p in (db.query(CatalogProduct).filter(CatalogProduct.id.in_(all_line_cids)).all() if all_line_cids else [])
    }
    pl_out: list[CustomerPlacementOut] = []
    for p in placements:
        lines = lines_by_placement.get(p.id, [])
        pl_out.append(
            CustomerPlacementOut(
                id=p.id,
                status=p.status,
                customer_notes=p.customer_notes,
                cancel_reason=p.cancel_reason,
                placed_at=p.placed_at,
                display_date=p.placed_at,
                display_name=f"Order #{p.id}",
                deleted_at=p.deleted_at,
                deleted_reason=p.deleted_reason,
                lines=[
                    CustomerOrderLineOut(
                        id=ln.id,
                        catalog_product_id=ln.catalog_product_id,
                        our_product_id=names.get(int(ln.catalog_product_id)) or ln.our_product_id,
                        quantity=ln.quantity,
                        quantity_billed=ln.quantity_billed,
                        unit_price=format(ln.unit_price, "f"),
                        status=ln.status,
                        cancel_reason=ln.cancel_reason,
                        addons=list(ln.addons_json or live_addons.get(int(ln.catalog_product_id), [])),
                        marking=marking_by_cid.get(int(ln.catalog_product_id)),
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
            .filter(
                CustomerBill.customer_id == customer_id,
                CustomerBill.cancelled_at.is_(None),
                CustomerBill.closed_at.is_(None),
            )
            .order_by(CustomerBill.created_at.desc())
            .all()
        )
        bill_ids = [b.id for b in bills]
        all_blines = (
            db.query(CustomerBillLine)
            .filter(CustomerBillLine.bill_id.in_(bill_ids))
            .order_by(CustomerBillLine.id.asc())
            .all()
            if bill_ids else []
        )
        lines_by_bill: dict[int, list] = defaultdict(list)
        for ln in all_blines:
            lines_by_bill[ln.bill_id].append(ln)
        prepared = []
        missing_ids: list[int] = []
        for b in bills:
            blines = lines_by_bill.get(b.id, [])
            addon_by_cid: dict[int, list] = {}
            totals_lines = (b.totals_json or {}).get("lines") if isinstance(b.totals_json, dict) else None
            if isinstance(totals_lines, list):
                for tl in totals_lines:
                    if isinstance(tl, dict) and tl.get("catalog_product_id") and tl.get("addons"):
                        addon_by_cid[int(tl["catalog_product_id"])] = list(tl["addons"])
            missing = [ln.catalog_product_id for ln in blines if int(ln.catalog_product_id) not in addon_by_cid]
            missing_ids.extend(int(x) for x in missing)
            prepared.append((b, blines, addon_by_cid, missing))
        live_addons_billed = addon_snapshots_map(db, missing_ids, with_images=False) if missing_ids else {}
        product_ids = list({int(ln.catalog_product_id) for ln in all_blines if ln.catalog_product_id})
        products_by_id = {
            p.id: p
            for p in (db.query(CatalogProduct).filter(CatalogProduct.id.in_(product_ids)).all() if product_ids else [])
        }
        agent_ids = list({b.freight_agent_id for b in bills if b.freight_agent_id})
        agent_names = {
            a.id: a.name
            for a in (db.query(FreightAgent).filter(FreightAgent.id.in_(agent_ids)).all() if agent_ids else [])
        }
        for b, blines, addon_by_cid, missing in prepared:
            for cid in missing:
                addon_by_cid.setdefault(int(cid), list(live_addons_billed.get(int(cid), [])))
            bills_out.append(serialize_customer_bill(
                db, b, blines, addon_by_cid, products_by_id=products_by_id, agent_names=agent_names,
            ))
    return CustomerOrderDetail(
        id=order.id,
        customer_id=customer_id,
        customer_name=customer.business_name,
        bucket=bucket,
        placements=pl_out,
        bills=bills_out,
    )

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

