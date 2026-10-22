from __future__ import annotations
"""Split from app/routers/shop.py."""

import logging
import re
import sys
import threading
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
from app.integrations.whatsapp.client import send_text
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
from app.services.stock_levels import stock_status_label

logger = logging.getLogger("jc.shop")

from app.routers.shop.router import router

@router.post("/orders", status_code=status.HTTP_201_CREATED)
def create_customer_order(
    body: CustomerOrderCreate,
    db: Session = Depends(get_db),
    customer: Customer = Depends(get_current_customer),
):
    requested = body.order_lines()
    if not requested:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Add at least one item")

    from app.services.pricing import effective_selling_price
    from app.routers.shop.list_order_history import PORTAL_YEAR_GROUP

    prepared = []
    for catalog_product_id, quantity in requested:
        prod = db.get(CatalogProduct, catalog_product_id)
        if not prod or not prod.is_active or prod.deleted_at or (prod.year_group or "").strip() != PORTAL_YEAR_GROUP:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="product not found")
        bal = db.query(StockBalance).filter(StockBalance.catalog_product_id == prod.id).first()
        on_hand = int(bal.quantity_on_hand) if bal else 0
        th = int(bal.low_stock_threshold or 5) if bal else 5
        if stock_status_label(on_hand, th) == "out_of_stock":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"{prod.our_product_id} is out of stock")
        if quantity > on_hand:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"Insufficient inventory for {prod.our_product_id}. Please call godown to book order.",
            )
        unit_price = effective_selling_price(prod.buying_price, prod.selling_price) or Decimal("0")
        if unit_price <= 0:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"Sell price not set for {prod.our_product_id}. Please contact godown.",
            )
        prepared.append((prod, quantity, unit_price, addon_snapshots_for_product(db, prod.id)))

    notes = (body.customer_notes or "").strip() or None
    merged = False
    placement = None
    try:
        for prod, quantity, unit_price, addons in prepared:
            placement, line_merged = append_or_create_portal_placement(
                db,
                customer_id=customer.id,
                customer_name=customer.business_name,
                catalog_product_id=prod.id,
                quantity=quantity,
                unit_price=unit_price,
                customer_notes=notes,
                addons_json=addons,
            )
            merged = merged or line_merged
        if placement is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Add at least one item")
        if merged:
            placement.document_key = None
        detail = ", ".join(f"{prod.our_product_id} × {quantity}" for prod, quantity, _price, _addons in prepared)
        log_activity(
            db,
            actor_type="customer",
            actor_id=customer.id,
            actor_name=customer.business_name,
            action="create" if not merged else "update",
            entity_type="customer_order",
            entity_id=placement.id,
            entity_label=customer.business_name,
            detail=detail,
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

    if "pytest" not in sys.modules:
        summary = ", ".join(f"{prod.our_product_id} × {quantity}" for prod, quantity, _price, _addons in prepared)
        amount = sum((price * qty for _prod, qty, price, _addons in prepared), Decimal("0"))
        threading.Thread(
            target=_notify_order_whatsapp,
            kwargs={
                "customer_name": customer.business_name,
                "customer_phone": customer.phone,
                "summary": summary,
                "total": amount,
                "placement_id": placement.id,
                "merged": merged,
            },
            daemon=True,
            name=f"wa-portal-order-{placement.id}",
        ).start()

    first_prod, first_qty, first_price, _addons = prepared[0]
    line_total = sum((price * qty for _prod, qty, price, _addons in prepared), Decimal("0"))
    msg = (
        "Added to your order. Keep searching to add more items."
        if merged
        else "Your order has been submitted. Keep searching to add more items."
    )
    return {
        "ok": True,
        "id": placement.id,
        "placement_id": placement.id,
        "merged": merged,
        "our_product_id": first_prod.our_product_id if len(prepared) == 1 else f"{len(prepared)} items",
        "quantity": first_qty if len(prepared) == 1 else sum(qty for _p, qty, _u, _a in prepared),
        "unit_price": format(first_price, "f") if len(prepared) == 1 else "0",
        "line_total": format(line_total, "f"),
        "message": msg,
        "document_key": None,
        "document_url": None,
        "whatsapp_sent": True,
    }

def _notify_order_whatsapp(
    *,
    customer_name: str,
    customer_phone: str,
    summary: str,
    total: Decimal,
    placement_id: int,
    merged: bool,
) -> None:
    """Best-effort WhatsApp to customer + staff. Never raises. No PDF."""
    try:
        amount = Decimal(total).quantize(Decimal("0.01"))
        verb = "updated" if merged else "placed"
        portal = (get_settings().customer_portal_url or "https://jyoticards.vercel.app").rstrip("/")
        cust_body = (
            f"Jyoti Creative Cards\n"
            f"Order {verb}: {summary}\n"
            f"Amount: ₹{format(amount, 'f')}\n"
            f"Order #{placement_id}\n"
            f"Open: {portal}"
        )
        send_text(customer_phone, cust_body)

        staff_msg = (
            f"New dealer order\n"
            f"{customer_name} ({customer_phone})\n"
            f"{summary} = ₹{format(amount, 'f')}\n"
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

