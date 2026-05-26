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
)
from app.services.catalog_storage import presigned_url
from app.services.stock_levels import stock_status_label

shop_order_router = APIRouter(prefix="/shop", tags=["shop"])
admin_customer_order_router = APIRouter(prefix="/customer-orders", tags=["customer-orders"])

CO_STATUSES = frozenset({"confirmed", "billed", "shipped", "cancelled"})


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
        lt = (up * qty).quantize(Decimal("0.0001"))
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


def _build_items_admin(db: Session, quantities: dict[int, int]) -> tuple[list[dict], Decimal]:
    items: list[dict] = []
    total = Decimal("0")
    for cid in sorted(quantities.keys()):
        qty = quantities[cid]
        if qty < 1:
            continue
        p = db.get(CatalogProduct, cid)
        if p is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Unknown product id {cid}")
        up = Decimal(str(p.selling_price))
        lt = (up * qty).quantize(Decimal("0.0001"))
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


def _order_to_public(row: CustomerOrder) -> CustomerOrderPublic:
    lines = _items_to_public(row.items)
    return CustomerOrderPublic(
        id=row.id,
        customer_id=row.customer_id,
        status=row.status,
        items=lines,
        total_amount=format(row.total_amount, "f"),
        notes=row.notes,
        customer_notes=row.customer_notes,
        shipment_receipt=row.shipment_receipt,
        shipment_contact=row.shipment_contact,
        shipment_notes=row.shipment_notes,
        customer_confirmed_delivery_at=row.customer_confirmed_delivery_at,
        invoice_date=row.invoice_date,
        invoice_no=row.invoice_no,
        receipt_note_no=row.receipt_note_no,
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

    row = CustomerOrder(
        customer_id=customer.id,
        status="confirmed",
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

    merged = _merge_lines(body.items)
    items, total = _build_items_admin(db, merged)

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
        status="confirmed",
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

    if row.status == "shipped":
        if not row.shipment_receipt:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="shipment_receipt (AWB/receipt number) is required when status is shipped",
            )

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
