from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import require_admin
from app.models.catalog_product import CatalogProduct
from app.models.customer import Customer
from app.models.customer_bill import CustomerBill
from app.models.customer_order import CustomerOrder
from app.schemas.customer_bill import CustomerBillGenerate, CustomerBillPublic
from app.services.catalog_storage import delete_keys, presigned_url, storage_configured, upload_bytes
from app.integrations.whatsapp.client import send_order_billed, upload_media
from app.services.accounting import ensure_ar_for_customer_bill, order_line_summary
from app.services.customer_bill_math import compute_bill_totals
from app.services.customer_bill_pdf import render_customer_bill_pdf, render_copies_pdf
from app.models.bill_series import BillSeries

router = APIRouter(prefix="/customer-bills", tags=["customer-bills"])

_DOC_PREFIX = "customer_bills"


def _to_public(row: CustomerBill) -> CustomerBillPublic:
    doc_url = presigned_url(row.document_key) if row.document_key else None
    tot = row.totals if isinstance(row.totals, dict) else {}
    return CustomerBillPublic(
        id=row.id,
        customer_order_id=row.customer_order_id,
        gst_enabled=bool(row.gst_enabled),
        gst_rate_percent=str(row.gst_rate_percent or "0"),
        discount_percent=str(row.discount_percent) if row.discount_percent is not None else None,
        totals=tot,
        document_key=row.document_key,
        document_url=doc_url,
        bill_no=row.bill_no,
        bill_series_id=row.bill_series_id,
        narration=row.narration,
        bill_status=row.bill_status or "active",
        cancelled_by=row.cancelled_by,
        cancelled_reason=row.cancelled_reason,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _get_item_image_urls(db: Session, items: list[dict]) -> dict[int, str | None]:
    """Return {catalog_product_id: presigned_url} for items that have images."""
    result: dict[int, str | None] = {}
    for item in items:
        cid = item.get("catalog_product_id")
        if not cid:
            continue
        if cid in result:
            continue
        prod = db.get(CatalogProduct, int(cid))
        if prod and isinstance(prod.image_keys, list) and prod.image_keys:
            result[cid] = presigned_url(prod.image_keys[0], expires=604800)
        else:
            result[cid] = None
    return result


@router.get("", response_model=list[CustomerBillPublic], dependencies=[Depends(require_admin)])
def list_customer_bills(db: Session = Depends(get_db)) -> list[CustomerBillPublic]:
    rows = db.query(CustomerBill).order_by(CustomerBill.id.desc()).limit(500).all()
    return [_to_public(r) for r in rows]


@router.get("/{bill_id}", response_model=CustomerBillPublic, dependencies=[Depends(require_admin)])
def get_customer_bill(bill_id: int, db: Session = Depends(get_db)) -> CustomerBillPublic:
    row = db.get(CustomerBill, bill_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="customer bill not found")
    return _to_public(row)


@router.post("/generate", response_model=CustomerBillPublic, dependencies=[Depends(require_admin)])
def generate_customer_bill(body: CustomerBillGenerate, db: Session = Depends(get_db)) -> CustomerBillPublic:
    from sqlalchemy.orm.attributes import flag_modified

    from datetime import timezone as _tz, timedelta as _td
    order = db.get(CustomerOrder, body.customer_order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="order not found")
    allowed_statuses = {"open", "confirmed", "billed"}
    if (order.status or "").strip().lower() not in allowed_statuses:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"customer bill can be generated when order status is open/confirmed/billed (got: {order.status})",
        )

    # Duplicate bill check: same customer, same day, same item set
    if not body.force_duplicate:
        _ist_offset = _td(hours=5, minutes=30)
        _now_ist = __import__("datetime").datetime.now(_tz.utc) + _ist_offset
        _today_start = _now_ist.replace(hour=0, minute=0, second=0, microsecond=0) - _ist_offset
        _today_end = _now_ist.replace(hour=23, minute=59, second=59, microsecond=999999) - _ist_offset
        # Get all active bills for orders of the same customer today
        _same_day_bills = (
            db.query(CustomerBill)
            .join(CustomerOrder, CustomerOrder.id == CustomerBill.customer_order_id)
            .filter(
                CustomerOrder.customer_id == order.customer_id,
                CustomerBill.bill_status == "active",
                CustomerBill.created_at >= _today_start,
                CustomerBill.created_at <= _today_end,
                CustomerBill.customer_order_id != order.id,  # different order
            ).all()
        )
        _this_items = sorted([(int(it.get("catalog_product_id", 0)), int(it.get("quantity", 0))) for it in (order.items if isinstance(order.items, list) else []) if isinstance(it, dict)])
        for _b in _same_day_bills:
            _b_order = db.get(CustomerOrder, _b.customer_order_id)
            if _b_order:
                _b_items = sorted([(int(it.get("catalog_product_id", 0)), int(it.get("quantity", 0))) for it in (_b_order.items if isinstance(_b_order.items, list) else []) if isinstance(it, dict)])
                if _b_items == _this_items:
                    raise HTTPException(
                        status.HTTP_409_CONFLICT,
                        detail={"duplicate": True, "message": f"Duplicate bill detected — same customer and items already billed today (Bill #{_b.bill_no or _b.id}).", "existing_id": _b.id},
                    )

    raw_items = order.items if isinstance(order.items, list) else []
    all_order_items = [x for x in raw_items if isinstance(x, dict)]

    # Partial billing: if bill_items specified, use only those quantities
    if body.bill_items:
        bill_qty_map: dict[int, int] = {}
        for bi in body.bill_items:
            cid = int(bi.get("catalog_product_id", 0))
            qty = int(bi.get("quantity", 0))
            if cid > 0 and qty > 0:
                bill_qty_map[cid] = bill_qty_map.get(cid, 0) + qty

        # Build items for this bill (only requested quantities)
        items = []
        for it in all_order_items:
            cid = int(it.get("catalog_product_id", 0))
            if cid in bill_qty_map:
                bq = bill_qty_map[cid]
                available = int(it.get("quantity", 0)) - int(it.get("qty_billed", 0))
                if bq > available:
                    raise HTTPException(
                        status.HTTP_400_BAD_REQUEST,
                        detail=f"Bill qty {bq} exceeds unbilled qty {available} for product {cid}",
                    )
                new_it = dict(it)
                new_it["quantity"] = bq
                new_it["line_total"] = float(it.get("unit_price", 0)) * bq
                items.append(new_it)

        # Update order items: add qty_billed tracking
        updated_order_items = []
        for it in all_order_items:
            cid = int(it.get("catalog_product_id", 0))
            new_it = dict(it)
            if cid in bill_qty_map:
                new_it["qty_billed"] = int(it.get("qty_billed", 0)) + bill_qty_map[cid]
            updated_order_items.append(new_it)
        order.items = updated_order_items
        flag_modified(order, "items")

        # Recalculate order total (remaining unbilled)
        order.total_amount = Decimal(str(sum(
            float(it.get("unit_price", 0)) * max(0, int(it.get("quantity", 0)) - int(it.get("qty_billed", 0)))
            for it in updated_order_items
        )))
    else:
        # Bill all remaining (unbilled) items
        items = []
        for it in all_order_items:
            qty_total = int(it.get("quantity", 0))
            qty_billed = int(it.get("qty_billed", 0))
            remaining = max(0, qty_total - qty_billed)
            if remaining <= 0:
                continue
            new_it = dict(it)
            new_it["quantity"] = remaining
            new_it["line_total"] = float(it.get("unit_price", 0)) * remaining
            items.append(new_it)

        # Mark all items as fully billed (preserve original total_amount)
        for it in all_order_items:
            it["qty_billed"] = int(it.get("quantity", 0))
        order.items = all_order_items
        flag_modified(order, "items")

    gst_rate = Decimal(str(body.gst_rate_percent))
    if gst_rate < 0:
        gst_rate = Decimal("0")
    disc = body.discount_percent
    freight = body.freight_charges
    packaging = body.packaging_charges

    # Apply rate_type override
    rate_type = (body.rate_type or "order").strip().lower()
    if rate_type in ("net", "regular"):
        overridden_items = []
        for it in items:
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
            overridden_items.append(it)
        items = overridden_items

    totals = compute_bill_totals(
        items,
        gst_enabled=body.gst_enabled,
        gst_rate_percent=gst_rate,
        discount_percent=disc,
        freight_charges=freight,
        packaging_charges=packaging,
        item_overrides=body.item_overrides,
        additional_charges=body.additional_charges,
    )

    cust = db.get(Customer, order.customer_id)
    name = (cust.name if cust else "") or ""
    company = (cust.company_name if cust else None) or None
    display_name = company or name

    if not storage_configured():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="S3 storage not configured — cannot store PDF",
        )

    # Gather product image URLs for PDF
    item_image_urls = _get_item_image_urls(db, items)

    existing = db.query(CustomerBill).filter(
        CustomerBill.customer_order_id == order.id,
        CustomerBill.bill_status != "cancelled",
    ).first()
    old_keys: list[str] = []

    # Resolve bill_no from series if requested
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

    narration_val = (body.narration or "").strip() or None

    if existing is not None:
        if existing.document_key:
            old_keys.append(existing.document_key)
        existing.gst_enabled = body.gst_enabled
        existing.gst_rate_percent = gst_rate
        existing.discount_percent = disc
        existing.totals = totals
        existing.document_key = None
        if narration_val is not None:
            existing.narration = narration_val
        if new_bill_no is not None:
            existing.bill_no = new_bill_no
            existing.bill_series_id = body.bill_series_id
        db.add(existing)
        row = existing
    else:
        row = CustomerBill(
            customer_order_id=order.id,
            gst_enabled=body.gst_enabled,
            gst_rate_percent=gst_rate,
            discount_percent=disc,
            totals=totals,
            document_key=None,
            bill_no=new_bill_no,
            bill_series_id=body.bill_series_id,
            narration=narration_val,
        )
        db.add(row)

    db.commit()
    db.refresh(row)

    delete_keys(old_keys)

    # Compute credit limit info for PDF footer
    credit_limit_val: float | None = float(cust.credit_limit) if (cust and cust.credit_limit is not None) else None
    from app.services.accounting import get_customer_outstanding
    try:
        outstanding_val = float(get_customer_outstanding(db, order.customer_id))
    except Exception:
        outstanding_val = 0.0

    key = f"{_DOC_PREFIX}/{uuid.uuid4().hex}.pdf"
    pdf_bytes = render_customer_bill_pdf(
        bill_id=row.id,
        order_id=order.id,
        customer_name=display_name,
        customer_company=company,
        totals=totals,
        customer_notes=order.customer_notes or None,
        narration=row.narration or None,
        item_image_urls=item_image_urls,
        order_created_at=order.created_at,
        credit_limit=credit_limit_val,
        outstanding=outstanding_val,
    )
    upload_bytes(key, pdf_bytes, "application/pdf")
    row.document_key = key
    db.add(row)
    # Update order status: if all items billed → billed; else keep open (partial)
    all_billed = all(
        int(it.get("qty_billed", 0)) >= int(it.get("quantity", 0))
        for it in (order.items if isinstance(order.items, list) else [])
        if isinstance(it, dict)
    )
    order.status = "billed" if all_billed else "open"
    db.add(order)
    db.commit()
    db.refresh(row)

    tot = row.totals if isinstance(row.totals, dict) else {}
    try:
        ensure_ar_for_customer_bill(db, bill=row, order=order, totals=tot)
        db.commit()
    except ValueError as e:
        db.rollback()
        msg = str(e)
        if msg.startswith("Cannot post:"):
            raise HTTPException(status.HTTP_409_CONFLICT, detail=msg) from e
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=msg) from e
    db.refresh(row)

    # Send bill PDF via WA order_billed template
    if cust and (cust.phone or "").strip():
        try:
            bill_media_id = upload_media(pdf_bytes, "application/pdf", f"Bill_{order.id}.pdf")
            if bill_media_id:
                result = send_order_billed(
                    phone=cust.phone,
                    customer_name=name or "Customer",
                    order_id=order.id,
                    amount=str(tot.get("grand_total") or "0"),
                    note=(order.customer_notes or "—"),
                    pdf_media_id=bill_media_id,
                    order_url_suffix=str(order.id),
                )
                print(f"WA order_billed #{order.id}: {result}")
            else:
                print(f"WA order_billed #{order.id}: PDF upload failed")
        except Exception as e:
            import traceback
            print(f"WA order_billed failed #{order.id}: {e}")
            traceback.print_exc()

    try:
        from app.services.audit import log_action as _log
        _log(db, "CREATE", "customer_bill", row.id,
             f"Bill {row.bill_no or row.id} generated for Order #{order.id}. Total: {tot.get('grand_total','?')}")
        db.commit()
    except Exception as _audit_ex:
        print(f"Audit log failed (non-fatal): {_audit_ex}")
        db.rollback()

    return _to_public(row)


from fastapi.responses import RedirectResponse


@router.get("/order/{order_id}/history", response_model=list[CustomerBillPublic], dependencies=[Depends(require_admin)])
def get_order_bill_history(order_id: int, db: Session = Depends(get_db)) -> list[CustomerBillPublic]:
    """Return all bills (active + cancelled) for an order, newest first."""
    rows = (
        db.query(CustomerBill)
        .filter(CustomerBill.customer_order_id == order_id)
        .order_by(CustomerBill.id.desc())
        .all()
    )
    return [_to_public(r) for r in rows]


@router.get("/{bill_id}/download", dependencies=[Depends(require_admin)])
def download_bill(bill_id: int, db: Session = Depends(get_db)):
    """Redirect to presigned PDF download URL."""
    row = db.get(CustomerBill, bill_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="bill not found")
    if not row.document_key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="no PDF on file for this bill")
    url = presigned_url(row.document_key, expires=300)
    if not url:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="storage not configured")
    return RedirectResponse(url=url, status_code=302)


@router.get("/{bill_id}/print", dependencies=[Depends(require_admin)])
def print_bill(
    bill_id: int,
    db: Session = Depends(get_db),
    copies: int = Query(default=1, ge=1, le=4, description="Number of copies (1-4)"),
) -> Response:
    """Return a multi-copy PDF inline (for browser print dialog).
    Each copy is labeled ORIGINAL / DUPLICATE / TRIPLICATE / QUADRUPLICATE.
    """
    row = db.get(CustomerBill, bill_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="bill not found")
    order = db.get(CustomerOrder, row.customer_order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="order not found")
    cust = db.get(Customer, order.customer_id)
    display_name = (cust.name if cust else "Customer")
    company = (cust.company_name or None) if cust else None

    # Resolve item image URLs
    item_image_urls: dict = {}
    if isinstance(order.items, list):
        for item in order.items:
            if isinstance(item, dict) and item.get("catalog_product_id"):
                cid = int(item["catalog_product_id"])
                prod = db.get(__import__("app.models.catalog_product", fromlist=["CatalogProduct"]).CatalogProduct, cid)
                if prod and isinstance(prod.image_keys, list) and prod.image_keys:
                    url = presigned_url(prod.image_keys[0], expires=600)
                    if url:
                        item_image_urls[cid] = url

    from datetime import datetime as _dt, timezone as _tz2
    totals = row.totals if isinstance(row.totals, dict) else {}

    # If stored totals have no lines (or lines lack rate_inclusive), regenerate from order items
    stored_lines = totals.get("lines", [])
    needs_regen = (
        not stored_lines or
        all(not (ln.get("rate_inclusive") or ln.get("unit_price")) for ln in stored_lines if isinstance(ln, dict))
    )
    if needs_regen and isinstance(order.items, list) and order.items:
        from app.services.customer_bill_math import compute_bill_totals as _cbt
        from decimal import Decimal as _Dec2
        fresh = _cbt(
            order.items,
            gst_enabled=bool(row.gst_enabled),
            gst_rate_percent=row.gst_rate_percent or _Dec2("0"),
            discount_percent=row.discount_percent,
            freight_charges=None,
            packaging_charges=None,
            additional_charges=totals.get("additional_charges"),
        )
        totals = {**totals, "lines": fresh["lines"]}

    printed_now = _dt.now(_tz2.utc)
    pdf_bytes = render_copies_pdf(
        copies=copies,
        with_labels=True,
        bill_id=row.id,
        order_id=order.id,
        customer_name=display_name,
        customer_company=company,
        totals=totals,
        generated_at=row.created_at,
        printed_at=printed_now,
        narration=row.narration or None,
        item_image_urls=item_image_urls,
        order_created_at=order.created_at,
    )
    try:
        from app.services.audit import log_action as _log2
        _log2(db, "PRINT", "customer_bill", row.id,
              f"Bill {row.bill_no or row.id} printed ({copies} cop{'y' if copies==1 else 'ies'})")
        db.commit()
    except Exception as _audit_ex:
        print(f"Audit log failed (non-fatal): {_audit_ex}")
        db.rollback()

    filename = f"Bill_{row.bill_no or row.id}_x{copies}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=\"{filename}\""},
    )
