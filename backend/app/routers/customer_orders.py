from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import get_current_customer, require_admin
from app.integrations.whatsapp.client import (
    send_order_confirmation,
    send_shipment_confirmation,
    upload_media,
)
from app.services.order_items_pdf import build_order_items_pdf
from app.models.catalog_product import CatalogProduct
from app.models.customer import Customer
from app.models.customer_order import CustomerOrder
from app.models.stock_balance import StockBalance
from app.schemas.customer_order import (
    CustomerOrderAdminCreate,
    CustomerOrderAdminPatch,
    CustomerOrderAdminPublic,
    CustomerOrderCreate,
    CustomerOrderLineIn,
    CustomerOrderLinePublic,
    CustomerOrderPublic,
    OfflineOrderCreate,
)
from app.services.catalog_storage import presigned_url
from app.services.stock_levels import stock_status_label

shop_order_router = APIRouter(prefix="/shop", tags=["shop"])
admin_customer_order_router = APIRouter(prefix="/customer-orders", tags=["customer-orders"])

CO_STATUSES = frozenset({"open", "closed", "confirmed", "billed", "shipped", "cancelled"})


def _avail(db: Session, catalog_product_id: int) -> tuple[int, int]:
    bal = db.get(StockBalance, catalog_product_id)
    if bal is None:
        return 0, 0
    return int(bal.quantity), int(bal.low_stock_threshold or 0)


def _merge_lines(lines: List[CustomerOrderLineIn]) -> dict[int, int]:
    m: dict[int, int] = {}
    for ln in lines:
        m[ln.catalog_product_id] = m.get(ln.catalog_product_id, 0) + ln.quantity
    return m


def _build_items_customer(db: Session, quantities: dict[int, int]) -> tuple[list[dict], Decimal]:
    items: list[dict] = []
    total = Decimal("0")
    for cid in sorted(quantities.keys()):
        qty = quantities[cid]
        if qty < 1:
            continue
        p = db.get(CatalogProduct, cid)
        if p is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Unknown product id {cid}")
        q_avail, th = _avail(db, cid)
        label = stock_status_label(q_avail, th)
        if label == "out_of_stock" or q_avail <= 0:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"Product {p.our_product_id} is not available to order (out of stock)",
            )
        if qty > q_avail:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"Insufficient stock for {p.our_product_id}: requested {qty}, available {q_avail}",
            )
        up = Decimal(str(p.selling_price))
        lt = (up * qty).quantize(Decimal("0.01"))
        total += lt
        items.append(
            {
                "catalog_product_id": cid,
                "our_product_id": p.our_product_id,
                "name": p.name,
                "quantity": qty,
                "unit_price": float(up),
                "line_total": float(lt),
            }
        )
    if not items:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="No valid order lines")
    return items, total


def _build_items_admin(
    db: Session,
    quantities: dict[int, int],
    price_overrides: dict[int, float] | None = None,
) -> tuple[list[dict], Decimal]:
    items: list[dict] = []
    total = Decimal("0")
    overrides = price_overrides or {}
    for cid in sorted(quantities.keys()):
        qty = quantities[cid]
        if qty < 1:
            continue
        p = db.get(CatalogProduct, cid)
        if p is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Unknown product id {cid}")
        if cid in overrides:
            up = Decimal(str(overrides[cid]))
        else:
            up = Decimal(str(p.selling_price))
        lt = (up * qty).quantize(Decimal("0.01"))
        total += lt
        items.append(
            {
                "catalog_product_id": cid,
                "our_product_id": p.our_product_id,
                "name": p.name,
                "quantity": qty,
                "unit_price": float(up),
                "line_total": float(lt),
            }
        )
    if not items:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="No valid order lines")
    return items, total


def _items_to_public(raw: object) -> List[CustomerOrderLinePublic]:
    out: List[CustomerOrderLinePublic] = []
    if not isinstance(raw, list):
        return out
    for x in raw:
        if not isinstance(x, dict):
            continue
        try:
            cid = int(x["catalog_product_id"])
            q = int(x["quantity"])
        except (KeyError, TypeError, ValueError):
            continue
        out.append(
            CustomerOrderLinePublic(
                catalog_product_id=cid,
                our_product_id=str(x.get("our_product_id") or ""),
                name=str(x.get("name") or ""),
                quantity=max(1, q),
                unit_price=str(x.get("unit_price", "0")),
                line_total=str(x.get("line_total", "0")),
            )
        )
    return out


def _fmt_amount(v) -> str:
    """Format a Decimal/float as a 2-decimal string, e.g. '8000.00'."""
    try:
        return f"{float(v):.2f}"
    except (TypeError, ValueError):
        return "0.00"


def _order_to_public(row: CustomerOrder) -> CustomerOrderPublic:
    lines = _items_to_public(row.items)
    return CustomerOrderPublic(
        id=row.id,
        customer_id=row.customer_id,
        status=row.status,
        items=lines,
        total_amount=_fmt_amount(row.total_amount),
        notes=row.notes,
        customer_notes=row.customer_notes,
        shipment_receipt=row.shipment_receipt,
        shipment_contact=row.shipment_contact,
        shipment_notes=row.shipment_notes,
        customer_confirmed_delivery_at=row.customer_confirmed_delivery_at,
        invoice_date=row.invoice_date,
        invoice_no=row.invoice_no,
        receipt_note_no=row.receipt_note_no,
        versions=row.versions if isinstance(row.versions, list) else None,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _admin_public(db: Session, row: CustomerOrder) -> CustomerOrderAdminPublic:
    base = _order_to_public(row)
    cust = db.get(Customer, row.customer_id)
    return CustomerOrderAdminPublic(
        **base.model_dump(),
        customer_name=(cust.name if cust else "") or "",
        customer_phone=(cust.phone if cust else "") or "",
    )


def _wa_summary(items: list[dict]) -> str:
    parts: List[str] = []
    for x in items:
        if not isinstance(x, dict):
            continue
        sku = str(x.get("our_product_id") or "?")
        q = int(x.get("quantity") or 0)
        parts.append(f"{sku} × {q}")
    return "; ".join(parts)[:1024]


def _total_units(items: List[dict]) -> int:
    s = 0
    for x in items:
        if not isinstance(x, dict):
            continue
        try:
            s += int(x.get("quantity") or 0)
        except (TypeError, ValueError):
            pass
    return s


@shop_order_router.post(
    "/orders",
    response_model=CustomerOrderPublic,
    status_code=status.HTTP_201_CREATED,
)
def create_customer_order(
    body: CustomerOrderCreate,
    db: Session = Depends(get_db),
    customer: Customer = Depends(get_current_customer),
) -> CustomerOrderPublic:
    merged = _merge_lines(body.lines)
    items, total = _build_items_customer(db, merged)

    # Credit limit check
    if customer.credit_limit is not None and not customer.credit_override:
        from app.models.ar_invoice import ARInvoice
        from app.services.accounting import amount_paid_on_ar
        open_invs = db.query(ARInvoice).filter(ARInvoice.customer_id == customer.id, ARInvoice.status != "paid").all()
        outstanding = sum(max(Decimal(str(inv.amount)) - amount_paid_on_ar(db, inv), Decimal("0")) for inv in open_invs)
        if (outstanding + total) > Decimal(str(customer.credit_limit)):
            raise HTTPException(
                status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Credit limit exceeded. Limit: {customer.credit_limit}, Outstanding: {outstanding}, Order: {total}",
            )

    # Deduct stock immediately on confirm
    for cid, qty in merged.items():
        bal = db.get(StockBalance, cid)
        if bal is None or int(bal.quantity) < qty:
            p = db.get(CatalogProduct, cid)
            pid = p.our_product_id if p else str(cid)
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"Insufficient stock for {pid}",
            )
        bal.quantity = int(bal.quantity) - qty
        db.add(bal)

    # Auto-merge: if customer already has an open order, fold new items in
    from sqlalchemy import and_
    existing = (
        db.query(CustomerOrder)
        .filter(
            and_(
                CustomerOrder.customer_id == customer.id,
                CustomerOrder.status.in_(["open", "confirmed"]),
                CustomerOrder.deleted_at.is_(None),
            )
        )
        .order_by(CustomerOrder.created_at.asc())
        .first()
    )

    if existing is not None:
        from sqlalchemy.orm.attributes import flag_modified
        ex_items: list = existing.items if isinstance(existing.items, list) else []
        ex_by_cid: dict[int, dict] = {
            int(it.get("catalog_product_id", 0)): it
            for it in ex_items
            if isinstance(it, dict) and it.get("catalog_product_id")
        }
        for new_item in items:
            if not isinstance(new_item, dict):
                continue
            cid = int(new_item.get("catalog_product_id", 0))
            if cid in ex_by_cid:
                old = ex_by_cid[cid]
                new_qty = int(old.get("quantity", 0)) + int(new_item.get("quantity", 0))
                unit = float(old.get("unit_price", new_item.get("unit_price", 0)))
                old["quantity"] = new_qty
                old["line_total"] = round(unit * new_qty, 2)
            else:
                ex_by_cid[cid] = new_item
        existing.items = list(ex_by_cid.values())
        existing.total_amount = Decimal(str(sum(float(it.get("line_total", 0)) for it in existing.items)))
        flag_modified(existing, "items")
        db.add(existing)
        db.commit()
        db.refresh(existing)
        row = existing
    else:
        row = CustomerOrder(
            customer_id=customer.id,
            status="open",
            items=items,
            total_amount=total,
            notes=None,
            customer_notes=(body.customer_notes or "").strip() or None,
        )
        db.add(row)
        db.commit()
        db.refresh(row)

    try:
        qty_total = sum(int(x.get("quantity") or 0) for x in items if isinstance(x, dict))
        amount_str = format(row.total_amount, "f")
        note_str = (body.customer_notes or "").strip() or "—"

        # Build image URLs for all items
        image_urls: dict = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            cid = int(item.get("catalog_product_id", 0))
            cat_prod = db.get(CatalogProduct, cid) if cid else None
            if cat_prod:
                keys = cat_prod.image_keys if isinstance(cat_prod.image_keys, list) else []
                if keys:
                    image_urls[cid] = presigned_url(keys[0], expires=3600)

        # Build PDF with all item images
        pdf_bytes = build_order_items_pdf(items, image_urls, row.id, customer.name or "Customer")
        pdf_media_id = upload_media(pdf_bytes, "application/pdf", f"Order_{row.id}.pdf")

        if pdf_media_id:
            portal_suffix = str(row.id)
            result = send_order_confirmation(
                phone=customer.phone,
                customer_name=customer.name or "Customer",
                order_id=row.id,
                items_summary=_wa_summary(items),
                quantity=qty_total,
                amount=amount_str,
                note=note_str,
                pdf_media_id=pdf_media_id,
                order_url_suffix=portal_suffix,
            )
            print(f"WA order_confirmation #{row.id}: {result}")
        else:
            print(f"WA order_confirmation #{row.id}: PDF upload failed, skipping WA")
    except Exception as ex:
        import traceback
        print("WhatsApp order_confirmation send failed:", ex)
        traceback.print_exc()

    return _order_to_public(row)


@shop_order_router.get("/orders", response_model=List[CustomerOrderPublic])
def list_my_orders(
    db: Session = Depends(get_db),
    customer: Customer = Depends(get_current_customer),
    status_filter: Optional[str] = Query(None, alias="status"),
) -> List[CustomerOrderPublic]:
    q = db.query(CustomerOrder).filter(CustomerOrder.customer_id == customer.id)
    sf = (status_filter or "").strip().lower()
    if sf and sf != "all":
        if sf not in CO_STATUSES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid status filter")
        q = q.filter(CustomerOrder.status == sf)
    rows = q.order_by(CustomerOrder.id.desc()).limit(500).all()
    return [_order_to_public(r) for r in rows]


@shop_order_router.get("/orders/{order_id}", response_model=CustomerOrderPublic)
def get_my_order(
    order_id: int,
    db: Session = Depends(get_db),
    customer: Customer = Depends(get_current_customer),
) -> CustomerOrderPublic:
    row = db.get(CustomerOrder, order_id)
    if row is None or row.customer_id != customer.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="order not found")
    return _order_to_public(row)


@shop_order_router.post("/orders/{order_id}/confirm-delivery", response_model=CustomerOrderPublic)
def confirm_delivery_received(
    order_id: int,
    db: Session = Depends(get_db),
    customer: Customer = Depends(get_current_customer),
) -> CustomerOrderPublic:
    row = db.get(CustomerOrder, order_id)
    if row is None or row.customer_id != customer.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="order not found")
    st = (row.status or "").strip().lower()
    if st not in ("shipped", "delivered"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="You can confirm receipt only after the order is shipped.",
        )
    row.customer_confirmed_delivery_at = datetime.now(timezone.utc)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _order_to_public(row)


@admin_customer_order_router.post("", response_model=CustomerOrderAdminPublic, status_code=201, dependencies=[Depends(require_admin)])
def admin_create_customer_order(
    body: CustomerOrderAdminCreate,
    db: Session = Depends(get_db),
) -> CustomerOrderAdminPublic:
    """Admin creates a manual / walk-in order on behalf of a customer (no WA notification)."""
    customer = db.get(Customer, body.customer_id)
    if not customer:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="customer not found")

    price_overrides = {ln.catalog_product_id: ln.unit_price for ln in body.items if ln.unit_price is not None}
    merged = _merge_lines(body.items)
    items, total = _build_items_admin(db, merged, price_overrides or None)

    # Credit check
    if customer.credit_limit is not None and not customer.credit_override:
        from app.models.ar_invoice import ARInvoice
        from app.services.accounting import amount_paid_on_ar
        open_invs = db.query(ARInvoice).filter(ARInvoice.customer_id == customer.id, ARInvoice.status != "paid").all()
        outstanding = sum(max(Decimal(str(inv.amount)) - amount_paid_on_ar(db, inv), Decimal("0")) for inv in open_invs)
        if (outstanding + total) > Decimal(str(customer.credit_limit)):
            raise HTTPException(
                status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Credit limit exceeded. Limit: {customer.credit_limit}, Outstanding: {outstanding}, Order: {total}",
            )

    # Deduct stock
    for cid, qty in merged.items():
        bal = db.get(StockBalance, cid)
        if bal is None or int(bal.quantity) < qty:
            p = db.get(CatalogProduct, cid)
            pid = p.our_product_id if p else str(cid)
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"Insufficient stock for {pid}")
        bal.quantity = int(bal.quantity) - qty
        db.add(bal)

    row = CustomerOrder(
        customer_id=body.customer_id,
        status="open",
        items=items,
        total_amount=total,
        notes=(body.notes or "").strip() or None,
        customer_notes=(body.customer_notes or "").strip() or None,
        invoice_date=body.invoice_date,
        invoice_no=(body.invoice_no or "").strip() or None,
        receipt_note_no=(body.receipt_note_no or "").strip() or None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _admin_public(db, row)


@admin_customer_order_router.get("", response_model=List[CustomerOrderAdminPublic], dependencies=[Depends(require_admin)])
def admin_list_customer_orders(
    db: Session = Depends(get_db),
    status_filter: Optional[str] = Query(None, alias="status"),
    customer_id: Optional[int] = Query(None, ge=1),
) -> List[CustomerOrderAdminPublic]:
    q = db.query(CustomerOrder).order_by(CustomerOrder.id.desc())
    sf = (status_filter or "").strip().lower()
    if sf:
        if sf not in CO_STATUSES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid status filter")
        q = q.filter(CustomerOrder.status == sf)
    if customer_id is not None:
        q = q.filter(CustomerOrder.customer_id == customer_id)
    rows = q.limit(400).all()
    return [_admin_public(db, r) for r in rows]


@admin_customer_order_router.get("/{order_id}", response_model=CustomerOrderAdminPublic, dependencies=[Depends(require_admin)])
def admin_get_customer_order(order_id: int, db: Session = Depends(get_db)) -> CustomerOrderAdminPublic:
    row = db.get(CustomerOrder, order_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="order not found")
    return _admin_public(db, row)


@admin_customer_order_router.patch("/{order_id}", response_model=CustomerOrderAdminPublic, dependencies=[Depends(require_admin)])
def admin_patch_customer_order(
    order_id: int,
    body: CustomerOrderAdminPatch,
    db: Session = Depends(get_db),
) -> CustomerOrderAdminPublic:
    row = db.get(CustomerOrder, order_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="order not found")

    prev_status = row.status

    if body.shipment_receipt is not None:
        row.shipment_receipt = body.shipment_receipt.strip() or None
    if body.shipment_contact is not None:
        row.shipment_contact = body.shipment_contact.strip() or None
    if body.shipment_notes is not None:
        row.shipment_notes = body.shipment_notes.strip() or None

    if body.status is not None:
        st = body.status.strip().lower()
        if st not in CO_STATUSES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"invalid status; allowed: {', '.join(sorted(CO_STATUSES))}")
        row.status = st

    if body.notes is not None:
        row.notes = body.notes.strip() or None

    if body.customer_notes is not None:
        row.customer_notes = body.customer_notes.strip() or None

    if body.items is not None:
        merged = _merge_lines(body.items)
        items, total = _build_items_admin(db, merged)
        row.items = items
        row.total_amount = total

    if body.invoice_date is not None:
        row.invoice_date = body.invoice_date
    if body.invoice_no is not None:
        row.invoice_no = (body.invoice_no or "").strip() or None
    if body.receipt_note_no is not None:
        row.receipt_note_no = (body.receipt_note_no or "").strip() or None

    # Shipped is now optional — no longer enforced as a required step

    db.add(row)
    db.commit()
    db.refresh(row)

    cust = db.get(Customer, row.customer_id)
    raw_items = row.items if isinstance(row.items, list) else []
    item_dicts = [x for x in raw_items if isinstance(x, dict)]

    if cust:
        try:
            if row.status == "shipped" and prev_status != "shipped":
                send_shipment_confirmation(
                    phone=cust.phone,
                    customer_name=cust.name or "Customer",
                    receipt=row.shipment_receipt or "—",
                    contact=row.shipment_contact or "—",
                    service=row.shipment_notes or "—",
                    notes=row.shipment_notes or "—",
                    tracking_url_suffix=str(order_id),
                )
        except Exception as ex:
            print("WhatsApp shipment_confirmation send failed:", ex)

    return _admin_public(db, row)


from pydantic import BaseModel as _BaseModel
from datetime import timezone as _tz


def _snapshot_order(row: CustomerOrder, event: str, bill_id: int | None = None) -> dict:
    """Return a version snapshot of the current order state."""
    return {
        "version": len(row.versions or []) + 1,
        "timestamp": datetime.now(_tz.utc).isoformat(),
        "event": event,
        "items": list(row.items) if isinstance(row.items, list) else [],
        "total_amount": _fmt_amount(row.total_amount),
        "status": row.status,
        "bill_id": bill_id,
    }


@admin_customer_order_router.post(
    "/offline",
    response_model=dict,
    status_code=201,
    dependencies=[Depends(require_admin)],
)
def admin_offline_order(body: OfflineOrderCreate, db: Session = Depends(get_db)) -> dict:
    """Create an order AND immediately generate a bill in a single step (offline/walk-in)."""
    from decimal import Decimal as _Dec
    from app.models.bill_series import BillSeries
    from app.models.customer_bill import CustomerBill
    from app.services.catalog_storage import storage_configured, upload_bytes
    from app.services.customer_bill_math import compute_bill_totals
    from app.services.customer_bill_pdf import render_customer_bill_pdf
    from app.services.accounting import ensure_ar_for_customer_bill
    import uuid as _uuid

    customer = db.get(Customer, body.customer_id)
    if not customer:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="customer not found")

    price_overrides = {ln.catalog_product_id: ln.unit_price for ln in body.items if ln.unit_price is not None}
    merged = _merge_lines(body.items)
    items, total = _build_items_admin(db, merged, price_overrides or None)

    # Deduct stock
    for cid, qty in merged.items():
        bal = db.get(StockBalance, cid)
        if bal is None or int(bal.quantity) < qty:
            p = db.get(CatalogProduct, cid)
            pid = p.our_product_id if p else str(cid)
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"Insufficient stock for {pid}")
        bal.quantity = int(bal.quantity) - qty
        db.add(bal)

    # Create order
    order = CustomerOrder(
        customer_id=body.customer_id,
        status="open",
        items=items,
        total_amount=total,
        notes=(body.notes or "").strip() or None,
        customer_notes=(body.customer_notes or "").strip() or None,
    )
    db.add(order)
    db.flush()

    # Generate bill immediately
    gst_rate = _Dec(str(body.gst_rate_percent or 0))
    rate_type = (body.rate_type or "order").strip().lower()
    bill_items = list(items)

    if rate_type in ("net", "regular"):
        overridden: list[dict] = []
        for it in bill_items:
            cid = it.get("catalog_product_id")
            prod = db.get(CatalogProduct, int(cid)) if cid else None
            new_price = None
            if prod and rate_type == "net":
                new_price = float(prod.buying_price or 0)
            elif prod and rate_type == "regular":
                new_price = float(prod.selling_price or 0)
            if new_price is not None:
                it = dict(it)
                it["unit_price"] = str(new_price)
            overridden.append(it)
        bill_items = overridden

    totals = compute_bill_totals(
        bill_items,
        gst_enabled=body.gst_enabled,
        gst_rate_percent=gst_rate,
        discount_percent=_Dec(str(body.discount_percent)) if body.discount_percent is not None else None,
        freight_charges=_Dec(str(body.freight_charges)) if body.freight_charges is not None else None,
        packaging_charges=_Dec(str(body.packaging_charges)) if body.packaging_charges is not None else None,
    )

    new_bill_no: str | None = None
    if body.bill_series_id is not None:
        series = db.get(BillSeries, body.bill_series_id)
        if series is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="bill series not found")
        if series.current_num >= series.end_num:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="bill series exhausted")
        next_num = series.current_num + 1 if series.current_num >= series.start_num else series.start_num
        series.current_num = next_num
        db.add(series)
        new_bill_no = f"{series.prefix}{next_num}"

    bill_row = CustomerBill(
        customer_order_id=order.id,
        gst_enabled=body.gst_enabled,
        gst_rate_percent=gst_rate,
        discount_percent=_Dec(str(body.discount_percent)) if body.discount_percent is not None else None,
        totals=totals,
        document_key=None,
        bill_no=new_bill_no,
        bill_series_id=body.bill_series_id,
    )
    db.add(bill_row)
    db.flush()

    # Mark order as closed (fully billed in one shot)
    order.status = "closed"
    for it in order.items if isinstance(order.items, list) else []:
        if isinstance(it, dict):
            it["qty_billed"] = it.get("quantity", 0)
    from sqlalchemy.orm.attributes import flag_modified as _fm
    _fm(order, "items")
    db.add(order)

    db.commit()
    db.refresh(order)
    db.refresh(bill_row)

    # Generate PDF
    cust_name = customer.name or ""
    company = customer.company_name or None
    display_name = company or cust_name
    doc_url = None
    if storage_configured():
        try:
            pdf_bytes = render_customer_bill_pdf(
                bill_id=bill_row.id,
                order_id=order.id,
                customer_name=display_name,
                customer_company=company,
                totals=totals,
                customer_notes=order.customer_notes or None,
                item_image_urls={},
                order_created_at=order.created_at,
            )
            key = f"customer_bills/{_uuid.uuid4().hex}.pdf"
            upload_bytes(key, pdf_bytes, "application/pdf")
            bill_row.document_key = key
            db.add(bill_row)
            db.commit()
            db.refresh(bill_row)
            from app.services.catalog_storage import presigned_url as _ps
            doc_url = _ps(key)
        except Exception as ex:
            print(f"Offline bill PDF failed: {ex}")

    # AR entry
    try:
        ensure_ar_for_customer_bill(db, bill=bill_row, order=order, totals=totals)
        db.commit()
    except Exception as ex:
        print(f"Offline bill AR failed: {ex}")

    from app.services.catalog_storage import presigned_url as _ps2
    bill_doc_url = _ps2(bill_row.document_key) if bill_row.document_key else None
    return {
        "order": _admin_public(db, order).model_dump(),
        "bill": {
            "id": bill_row.id,
            "bill_no": bill_row.bill_no,
            "totals": totals,
            "document_url": bill_doc_url,
        },
    }


@admin_customer_order_router.patch(
    "/{order_id}/edit-items",
    response_model=CustomerOrderAdminPublic,
    dependencies=[Depends(require_admin)],
)
def admin_edit_order_items(
    order_id: int,
    body: CustomerOrderAdminPatch,
    db: Session = Depends(get_db),
) -> CustomerOrderAdminPublic:
    """Edit order items with version history. If order has a bill, regenerates it."""
    from sqlalchemy.orm.attributes import flag_modified as _fm
    from app.models.customer_bill import CustomerBill
    from app.services.catalog_storage import storage_configured, upload_bytes
    from app.services.customer_bill_math import compute_bill_totals
    from app.services.customer_bill_pdf import render_customer_bill_pdf
    from app.services.accounting import ensure_ar_for_customer_bill
    import uuid as _uuid
    from decimal import Decimal as _Dec

    row = db.get(CustomerOrder, order_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="order not found")

    # Find existing bill
    existing_bill = db.query(CustomerBill).filter(
        CustomerBill.customer_order_id == order_id,
        CustomerBill.bill_status != "cancelled",
    ).first()

    # Save snapshot before edit
    snap = _snapshot_order(row, event="edited_with_bill" if existing_bill else "edited", bill_id=existing_bill.id if existing_bill else None)
    versions = list(row.versions) if isinstance(row.versions, list) else []
    versions.append(snap)
    row.versions = versions
    _fm(row, "versions")

    # Update items
    if body.items is not None:
        price_overrides = {ln.catalog_product_id: ln.unit_price for ln in body.items if ln.unit_price is not None}
        merged = _merge_lines(body.items)
        items, total = _build_items_admin(db, merged, price_overrides or None)
        # Preserve qty_billed from old items
        old_billed = {it["catalog_product_id"]: it.get("qty_billed", 0) for it in (row.items or []) if isinstance(it, dict)}
        for it in items:
            cid = it["catalog_product_id"]
            if cid in old_billed:
                it["qty_billed"] = old_billed[cid]
        row.items = items
        _fm(row, "items")
        row.total_amount = total

    if body.notes is not None:
        row.notes = body.notes.strip() or None
    if body.customer_notes is not None:
        row.customer_notes = body.customer_notes.strip() or None
    if body.status is not None:
        row.status = body.status.strip().lower()

    db.add(row)
    db.flush()

    # If bill exists and items changed: cancel old bill, create new active bill
    if existing_bill and body.items is not None:
        from app.models.customer_bill import CustomerBill as _CBill

        # Cancel the old bill
        existing_bill.bill_status = "cancelled"
        existing_bill.cancelled_by = "edit"
        existing_bill.cancelled_reason = f"Replaced by new bill on order edit (was bill #{existing_bill.id})"
        db.add(existing_bill)
        db.flush()

        # Build totals for new bill
        bill_items = [it for it in (row.items or []) if isinstance(it, dict)]
        gst_rate = existing_bill.gst_rate_percent or _Dec("0")
        totals = compute_bill_totals(
            bill_items,
            gst_enabled=bool(existing_bill.gst_enabled),
            gst_rate_percent=gst_rate,
            discount_percent=existing_bill.discount_percent,
            freight_charges=None,
            packaging_charges=None,
        )

        # Create new active bill (new row, unique=False on customer_order_id can have duplicates now)
        new_bill = _CBill(
            customer_order_id=row.id,
            gst_enabled=existing_bill.gst_enabled,
            gst_rate_percent=gst_rate,
            discount_percent=existing_bill.discount_percent,
            totals=totals,
            bill_no=existing_bill.bill_no,  # keep same bill number
            bill_series_id=existing_bill.bill_series_id,
            narration=existing_bill.narration,
            bill_status="active",
        )
        db.add(new_bill)
        db.flush()

        if storage_configured():
            try:
                cust = db.get(Customer, row.customer_id)
                cust_name = cust.name if cust else ""
                company = cust.company_name if cust else None
                pdf_bytes = render_customer_bill_pdf(
                    bill_id=new_bill.id,
                    order_id=row.id,
                    customer_name=company or cust_name,
                    customer_company=company,
                    totals=totals,
                    customer_notes=row.customer_notes or None,
                    narration=new_bill.narration,
                    item_image_urls={},
                    order_created_at=row.created_at,
                )
                key = f"customer_bills/{_uuid.uuid4().hex}.pdf"
                upload_bytes(key, pdf_bytes, "application/pdf")
                new_bill.document_key = key
                db.add(new_bill)
            except Exception as ex:
                print(f"Edit-items bill PDF failed: {ex}")

        try:
            ensure_ar_for_customer_bill(db, bill=new_bill, order=row, totals=totals)
        except Exception as ex:
            print(f"Edit-items AR failed: {ex}")

    db.commit()
    db.refresh(row)
    return _admin_public(db, row)


@admin_customer_order_router.delete("/{order_id}/permanent", dependencies=[Depends(require_admin)])
def permanently_delete_customer_order(order_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(CustomerOrder, order_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="order not found")
    db.delete(row)
    db.commit()
    return {"ok": True, "id": order_id, "permanently_deleted": True}


@admin_customer_order_router.delete("/{order_id}", dependencies=[Depends(require_admin)])
def soft_delete_customer_order(order_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(CustomerOrder, order_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="order not found")
    row.deleted_at = datetime.now(timezone.utc)
    row.status = "cancelled"
    db.add(row)
    db.commit()
    return {"ok": True, "id": order_id, "deleted": True}


@admin_customer_order_router.post("/{order_id}/restore", dependencies=[Depends(require_admin)])
def restore_customer_order(order_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(CustomerOrder, order_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="order not found")
    row.deleted_at = None
    db.add(row)
    db.commit()
    return {"ok": True, "id": order_id, "restored": True}


class MergeOrdersBody(_BaseModel):
    customer_id: int
    order_ids: List[int]
    notes: Optional[str] = None


@admin_customer_order_router.post("/merge", response_model=CustomerOrderAdminPublic, dependencies=[Depends(require_admin)])
def merge_customer_orders(body: MergeOrdersBody, db: Session = Depends(get_db)) -> CustomerOrderAdminPublic:
    if len(body.order_ids) < 2:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="provide at least 2 order_ids to merge")

    orders = []
    for oid in body.order_ids:
        o = db.get(CustomerOrder, oid)
        if o is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"order {oid} not found")
        if o.customer_id != body.customer_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"order {oid} does not belong to customer {body.customer_id}")
        if (o.status or "").strip().lower() != "confirmed":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"order {oid} must be in 'confirmed' status to merge (got '{o.status}')")
        orders.append(o)

    merged_quantities: dict[int, dict] = {}
    for o in orders:
        for item in (o.items if isinstance(o.items, list) else []):
            if not isinstance(item, dict):
                continue
            try:
                cid = int(item["catalog_product_id"])
                qty = int(item["quantity"])
            except (KeyError, TypeError, ValueError):
                continue
            if cid in merged_quantities:
                merged_quantities[cid]["quantity"] += qty
                merged_quantities[cid]["line_total"] = float(
                    Decimal(str(merged_quantities[cid]["unit_price"])) * merged_quantities[cid]["quantity"]
                )
            else:
                merged_quantities[cid] = {**item, "quantity": qty}

    merged_items = list(merged_quantities.values())
    total = sum(Decimal(str(i.get("line_total", 0))) for i in merged_items)

    new_order = CustomerOrder(
        customer_id=body.customer_id,
        status="confirmed",
        items=merged_items,
        total_amount=total,
        notes=(body.notes or "").strip() or None,
    )
    db.add(new_order)

    for o in orders:
        o.status = "cancelled"
        db.add(o)

    db.commit()
    db.refresh(new_order)
    return _admin_public(db, new_order)
