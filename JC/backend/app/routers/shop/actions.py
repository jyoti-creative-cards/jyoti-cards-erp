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

@router.get("/orders/{placement_id}/document")
def get_order_document(
    placement_id: int,
    db: Session = Depends(get_db),
    customer: Customer = Depends(get_current_customer),
):
    placement = db.get(CustomerOrderPlacement, placement_id)
    if not placement:
        raise HTTPException(404, "order not found")
    order = db.get(CustomerOrder, placement.customer_order_id)
    if not order or order.customer_id != customer.id:
        raise HTTPException(404, "order not found")
    if storage_configured():
        try:
            generate_customer_order_document(db, placement.id)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("order PDF regen failed placement=%s", placement_id)
            placement = db.get(CustomerOrderPlacement, placement_id)
            if not placement or not placement.document_key:
                raise HTTPException(500, "document generation failed")
    if not placement.document_key:
        raise HTTPException(404, "document not available")
    url = presigned_url(placement.document_key)
    if not url:
        raise HTTPException(503, "storage not available")
    return {"document_url": url, "document_key": placement.document_key}

@router.get("/bills/{bill_id}/document")
def get_bill_document(
    bill_id: int,
    db: Session = Depends(get_db),
    customer: Customer = Depends(get_current_customer),
):
    bill = db.get(CustomerBill, bill_id)
    if not bill or bill.customer_id != customer.id:
        raise HTTPException(404, "bill not found")
    if storage_configured():
        try:
            generate_customer_bill_document(db, bill.id)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("bill PDF regen failed bill=%s", bill_id)
            raise HTTPException(500, "document generation failed")
        if not bill.document_key:
            raise HTTPException(404, "document not available")
    url = presigned_url(bill.document_key)
    if not url:
        raise HTTPException(503, "storage not available")
    return {"document_url": url, "document_key": bill.document_key, "bill_number": bill.bill_number}

@router.get("/account", response_model=ShopAccountPublic)
def shop_account(
    db: Session = Depends(get_db),
    customer: Customer = Depends(get_current_customer),
):
    """Dealer money + profile in one call. AR is source of truth for pending/paid/limit."""
    city_name = None
    route_name = None
    if customer.city_id:
        city = db.get(City, customer.city_id)
        city_name = city.name if city else None
    if customer.route_id:
        route = db.get(Route, customer.route_id)
        route_name = route.name if route else None

    totals = customer_ar_totals(db, customer.id)
    credit = credit_status(db, customer.id)
    ledger_raw = build_ar_ledger(db, customer.id)
    label_map = {
        "bill": "Bill",
        "payment": "Payment",
        "credit_note": "Credit",
        "opening_balance": "Opening",
    }
    ledger: list[ShopLedgerEntryPublic] = []
    for e in reversed(ledger_raw):  # newest first for dealer
        created = e.get("created_at")
        date_s = e.get("value_date") or (created.date().isoformat() if hasattr(created, "date") else str(created or "")[:10])
        et = e.get("entry_type") or "bill"
        ledger.append(
            ShopLedgerEntryPublic(
                id=int(e["id"]),
                entry_type=et,
                label=label_map.get(et, et.replace("_", " ").title()),
                amount=str(e.get("amount") or "0"),
                signed_amount=str(e.get("signed_amount") or "0"),
                running_balance=str(e.get("running_balance") or "0"),
                description=e.get("description"),
                bill_id=e.get("bill_id"),
                payment_ref=e.get("payment_ref"),
                date=date_s,
            )
        )

    return ShopAccountPublic(
        profile=ShopAccountProfile(
            id=customer.id,
            business_name=customer.business_name,
            person_name=customer.person_name,
            phone=customer.phone,
            secondary_phone=customer.secondary_phone,
            address=customer.address,
            city_name=city_name,
            route_name=route_name,
            gst_number=customer.gst_number,
        ),
        money=ShopAccountMoney(
            pending=format(totals["outstanding"], "f"),
            paid=format(totals["payment_total"], "f"),
            billed=format(totals["bill_total"], "f"),
            credit_notes=format(totals["credit_total"], "f"),
            opening=format(totals["opening_total"], "f"),
            credit_limit=credit.get("credit_limit"),
            remaining_limit=credit.get("left"),
            unlimited=bool(credit.get("unlimited")),
        ),
        ledger=ledger,
    )

