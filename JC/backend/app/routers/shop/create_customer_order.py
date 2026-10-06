from __future__ import annotations
"""Split from app/routers/shop.py."""

import logging
import re
import unicodedata
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_db
from app.deps import get_current_customer
from app.integrations.whatsapp.client import send_document, send_text, upload_media
from app.models.catalog_alternative import CatalogAlternative
from app.models.catalog_product import CatalogProduct
from app.models.customer import Customer
from app.models.customer_bill import CustomerBill, CustomerBillLine
from app.models.customer_order import CustomerOrder, CustomerOrderLine, CustomerOrderPlacement
from app.models.stock import StockBalance
from app.models.city import City
from app.models.route import Route
from app.schemas.shop import (
    CustomerOrderCreate,
    PortalPlacementPublic,
    ShopAccountMoney,
    ShopAccountProfile,
    ShopAccountPublic,
    ShopAlternativePublic,
    ShopAddonPublic,
    ShopLedgerEntryPublic,
    ShopOrderHistoryLine,
    ShopOrderHistoryPublic,
    ShopProductPublic,
    ShopSuggestionPublic,
)
from app.services import response_cache
from app.services.activity import log_activity
from app.services.ar_ledger import build_ar_ledger, customer_ar_totals
from app.services.catalog_addons import addon_snapshots_for_product, addon_snapshots_map
from app.services.credit_limit import credit_status
from app.services.customer_order_flow import append_or_create_portal_placement
from app.services.doc_gen import generate_customer_bill_document, generate_customer_order_document
from app.services.document_present import present
from app.services.storage import download_bytes, presigned_url, storage_configured
from app.services.stock_levels import stock_status_label

logger = logging.getLogger("jc.shop")

from app.routers.shop.router import router

@router.post("/orders", status_code=status.HTTP_201_CREATED)
def create_customer_order(
    body: CustomerOrderCreate,
    db: Session = Depends(get_db),
    customer: Customer = Depends(get_current_customer),
):
    prod = db.get(CatalogProduct, body.catalog_product_id)
    if not prod or not prod.is_active or prod.deleted_at:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="product not found")

    if body.quantity < 50 or body.quantity % 50 != 0:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Quantity must be a multiple of 50",
        )

    bal = db.query(StockBalance).filter(StockBalance.catalog_product_id == prod.id).first()
    qty = int(bal.quantity_on_hand) if bal else 0
    th = int(bal.low_stock_threshold or 5) if bal else 5
    status_lbl = stock_status_label(qty, th)
    if status_lbl == "out_of_stock":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="product is out of stock")
    if body.quantity > qty:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Insufficient inventory. Please call godown to book order.",
        )

    from app.services.pricing import effective_selling_price

    unit_price = effective_selling_price(prod.buying_price, prod.selling_price) or Decimal("0")
    if unit_price <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Sell price not set for this product. Please contact godown.")
    addons = addon_snapshots_for_product(db, prod.id)
    merged = False
    try:
        placement, merged = append_or_create_portal_placement(
            db,
            customer_id=customer.id,
            customer_name=customer.business_name,
            catalog_product_id=prod.id,
            quantity=body.quantity,
            unit_price=unit_price,
            customer_notes=(body.customer_notes or "").strip() or None,
            addons_json=addons,
        )
        if merged:
            placement.document_key = None
        log_activity(
            db,
            actor_type="customer",
            actor_id=customer.id,
            actor_name=customer.business_name,
            action="create" if not merged else "update",
            entity_type="customer_order",
            entity_id=placement.id,
            entity_label=customer.business_name,
            detail=f"{prod.our_product_id} × {body.quantity}",
        )
        db.commit()
        from app.services.doc_jobs import enqueue_order_pdf
        enqueue_order_pdf(placement.id)
        response_cache.invalidate("shop:")
        response_cache.invalidate("stock:")
    except ValueError as e:
        db.rollback()
        msg = str(e)
        if "insufficient" in msg.lower():
            # Keep SKU detail when present (e.g. "insufficient stock for 7424 (need 100, have 0)")
            detail = msg if "for " in msg.lower() else "Insufficient inventory. Please call godown to book order."
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=detail) from e
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=msg) from e
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Order could not be saved. Please try again.") from e

    _notify_order_whatsapp(
        customer=customer,
        prod=prod,
        quantity=body.quantity,
        unit_price=unit_price,
        placement_id=placement.id,
        merged=merged,
        document_key=None,
    )

    msg = (
        "Added to your order. Keep searching to add more items."
        if merged
        else "Your order has been submitted. Keep searching to add more items."
    )
    return {
        "ok": True,
        "placement_id": placement.id,
        "merged": merged,
        "our_product_id": prod.our_product_id,
        "quantity": body.quantity,
        "unit_price": format(unit_price, "f"),
        "line_total": format(unit_price * body.quantity, "f"),
        "message": msg,
        "document_key": None,
        "document_url": None,
        "whatsapp_sent": True,
    }

def _notify_order_whatsapp(
    *,
    customer: Customer,
    prod: CatalogProduct,
    quantity: int,
    unit_price: Decimal,
    placement_id: int,
    merged: bool,
    document_key: str | None,
) -> None:
    """Best-effort WhatsApp to customer + staff. Never raises."""
    try:
        total = (unit_price * quantity).quantize(Decimal("0.01"))
        verb = "updated" if merged else "placed"
        portal = (get_settings().customer_portal_url or "https://jyoticards.vercel.app").rstrip("/")
        cust_body = (
            f"Jyoti Creative Cards\n"
            f"Order {verb}: {prod.our_product_id} × {quantity}\n"
            f"Amount: ₹{format(total, 'f')}\n"
            f"Order #{placement_id}\n"
            f"Open: {portal}"
        )
        send_text(customer.phone, cust_body)

        if document_key and storage_configured():
            data = download_bytes(document_key)
            if data:
                up = upload_media(data, f"order-{placement_id}.pdf")
                if up.get("ok") and up.get("media_id"):
                    send_document(
                        customer.phone,
                        media_id=up["media_id"],
                        filename=f"order-{placement_id}.pdf",
                        caption=f"Order #{placement_id} — {prod.our_product_id} × {quantity}",
                    )

        staff_msg = (
            f"New dealer order\n"
            f"{customer.business_name} ({customer.phone})\n"
            f"{prod.our_product_id} × {quantity} = ₹{format(total, 'f')}\n"
            f"Order #{placement_id}"
            + (" (added to open order)" if merged else "")
        )
        for phone in _staff_notify_phones():
            send_text(phone, staff_msg)
    except Exception:
        logger.exception("WhatsApp order notify failed placement=%s", placement_id)

def _staff_notify_phones() -> list[str]:
    raw = (get_settings().whatsapp_staff_notify_phones or "").strip()
    if not raw:
        return []
    return [p.strip() for p in re.split(r"[,;\s]+", raw) if p.strip()]

