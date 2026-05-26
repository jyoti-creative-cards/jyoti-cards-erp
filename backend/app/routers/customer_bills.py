from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
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
from app.services.customer_bill_pdf import render_customer_bill_pdf

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
    order = db.get(CustomerOrder, body.customer_order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="order not found")
    if (order.status or "").strip().lower() not in ("confirmed", "billed"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="customer bill can be generated when order status is confirmed or billed",
        )

    raw_items = order.items if isinstance(order.items, list) else []
    items = [x for x in raw_items if isinstance(x, dict)]

    gst_rate = Decimal(str(body.gst_rate_percent))
    if gst_rate < 0:
        gst_rate = Decimal("0")
    disc = body.discount_percent
    freight = body.freight_charges
    packaging = body.packaging_charges

    totals = compute_bill_totals(
        items,
        gst_enabled=body.gst_enabled,
        gst_rate_percent=gst_rate,
        discount_percent=disc,
        freight_charges=freight,
        packaging_charges=packaging,
    )

    cust = db.get(Customer, order.customer_id)
    name = (cust.name if cust else "") or ""
    company = (cust.company_name if cust else None) or None

    if not storage_configured():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="S3 storage not configured — cannot store PDF",
        )

    # Gather product image URLs for PDF
    item_image_urls = _get_item_image_urls(db, items)

    existing = db.query(CustomerBill).filter(CustomerBill.customer_order_id == order.id).first()
    old_keys: list[str] = []
    if existing is not None:
        if existing.document_key:
            old_keys.append(existing.document_key)
        existing.gst_enabled = body.gst_enabled
        existing.gst_rate_percent = gst_rate
        existing.discount_percent = disc
        existing.totals = totals
        existing.document_key = None
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
        )
        db.add(row)

    db.commit()
    db.refresh(row)

    delete_keys(old_keys)

    key = f"{_DOC_PREFIX}/{uuid.uuid4().hex}.pdf"
    pdf_bytes = render_customer_bill_pdf(
        bill_id=row.id,
        order_id=order.id,
        customer_name=name,
        customer_company=company,
        totals=totals,
        customer_notes=order.customer_notes or None,
        item_image_urls=item_image_urls,
        order_created_at=order.created_at,
    )
    upload_bytes(key, pdf_bytes, "application/pdf")
    row.document_key = key
    db.add(row)
    # Advance order to "billed" status
    if (order.status or "").strip().lower() == "confirmed":
        order.status = "billed"
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

    return _to_public(row)


from fastapi.responses import RedirectResponse


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
