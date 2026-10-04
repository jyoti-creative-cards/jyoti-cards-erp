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
from app.services.storage import download_bytes, storage_configured
from app.services.stock_levels import stock_status_label

logger = logging.getLogger("jc.shop")

from app.routers.shop.router import router

@router.get("/orders/history", response_model=List[ShopOrderHistoryPublic])
def list_order_history(
    db: Session = Depends(get_db),
    customer: Customer = Depends(get_current_customer),
):
    """All orders this dealer placed (any bucket) — dealer-facing statuses only."""
    order_ids = [
        r.id
        for r in db.query(CustomerOrder.id).filter(CustomerOrder.customer_id == customer.id).all()
    ]
    if not order_ids:
        return []
    placements = (
        db.query(CustomerOrderPlacement)
        .filter(CustomerOrderPlacement.customer_order_id.in_(order_ids), CustomerOrderPlacement.deleted_at.is_(None))
        .order_by(CustomerOrderPlacement.placed_at.desc())
        .all()
    )
    out: list[ShopOrderHistoryPublic] = []
    for p in placements:
        lines = (
            db.query(CustomerOrderLine)
            .filter(CustomerOrderLine.placement_id == p.id, CustomerOrderLine.status.in_(["active", "billed"]))
            .all()
        )
        if not lines:
            continue
        hist_lines: list[ShopOrderHistoryLine] = []
        total = Decimal("0")
        ship_sum = 0
        qty_sum = 0
        for ln in lines:
            shipped = int(ln.quantity_billed or 0)
            qty = int(ln.quantity or 0)
            ship_sum += shipped
            qty_sum += qty
            bill = _find_bill_for_line(db, customer.id, ln.catalog_product_id, p.placed_at) if shipped > 0 else None
            if bill:
                view = present(db, "customer_bill", bill)
            else:
                view = present(db, "customer_order", p)
            card_ln = _card_line_for_product(view, ln.catalog_product_id)
            our_product_id = str(card_ln.get("our_product_id") or ln.our_product_id or "")
            image_url = _image_url_from_keys(card_ln.get("image_keys") or [])
            category = card_ln.get("category")
            line_total = (ln.unit_price * ln.quantity).quantize(Decimal("0.01"))
            total += line_total
            hist_lines.append(
                ShopOrderHistoryLine(
                    catalog_product_id=ln.catalog_product_id,
                    our_product_id=our_product_id,
                    image_url=image_url,
                    quantity=qty,
                    quantity_shipped=shipped,
                    unit_price=format(ln.unit_price, "f"),
                    line_total=format(line_total, "f"),
                    category=category,
                    bill_id=bill.id if bill else None,
                    bill_number=bill.bill_number if bill else None,
                    has_bill_document=bool(bill and (bill.document_key or True)),
                )
            )
        out.append(
            ShopOrderHistoryPublic(
                id=p.id,
                placed_at=p.placed_at.isoformat(),
                status=_dealer_status(qty_sum, ship_sum),
                customer_notes=p.customer_notes,
                total_amount=format(total, "f"),
                has_order_document=bool(p.document_key),
                lines=hist_lines,
            )
        )
    return out

@router.get("/orders", response_model=List[PortalPlacementPublic])
def list_my_orders(
    db: Session = Depends(get_db),
    customer: Customer = Depends(get_current_customer),
):
    """Open-order lines (compat). Prefer /shop/orders/history for full history."""
    received = (
        db.query(CustomerOrder)
        .filter(CustomerOrder.customer_id == customer.id, CustomerOrder.bucket == "received", CustomerOrder.is_open.is_(True))
        .first()
    )
    out: list[PortalPlacementPublic] = []
    if not received:
        return out

    placements = (
        db.query(CustomerOrderPlacement)
        .filter(
            CustomerOrderPlacement.customer_order_id == received.id,
            CustomerOrderPlacement.status == "received",
            CustomerOrderPlacement.deleted_at.is_(None),
        )
        .order_by(CustomerOrderPlacement.placed_at.desc())
        .all()
    )
    for p in placements:
        lines = (
            db.query(CustomerOrderLine)
            .filter(CustomerOrderLine.placement_id == p.id, CustomerOrderLine.status.in_(["active", "billed"]))
            .all()
        )
        for ln in lines:
            shipped = int(ln.quantity_billed or 0)
            qty = int(ln.quantity or 0)
            dealer_st = _dealer_status(qty, shipped)
            prod = db.get(CatalogProduct, ln.catalog_product_id)
            image_url = _image_url(prod) if prod else ""
            bill = None
            if shipped > 0:
                bill = _find_bill_for_line(db, customer.id, ln.catalog_product_id, p.placed_at)
            line_total = (ln.unit_price * ln.quantity).quantize(Decimal("0.01"))
            out.append(
                PortalPlacementPublic(
                    id=p.id,
                    line_id=ln.id,
                    catalog_product_id=ln.catalog_product_id,
                    our_product_id=prod.our_product_id if prod else ln.our_product_id,
                    image_url=image_url,
                    quantity=qty,
                    quantity_shipped=shipped,
                    unit_price=format(ln.unit_price, "f"),
                    line_total=format(line_total, "f"),
                    status=_legacy_status(dealer_st),
                    customer_notes=p.customer_notes,
                    placed_at=p.placed_at.isoformat(),
                    bill_id=bill.id if bill else None,
                    bill_number=bill.bill_number if bill else None,
                    has_bill_document=bool(bill and bill.document_key) or bool(bill),
                    has_order_document=bool(p.document_key),
                    category=prod.category if prod else None,
                    series=prod.series if prod else None,
                    unit=prod.unit if prod else None,
                )
            )
    return out

def _alternatives_batch(db: Session, parent_ids: list[int], stock: dict[int, tuple[int, int]]) -> dict[int, List[ShopAlternativePublic]]:
    if not parent_ids:
        return {}
    rows = db.query(CatalogAlternative).filter(CatalogAlternative.product_id.in_(parent_ids)).all()
    alt_ids = {r.alternative_product_id for r in rows}
    alts = {
        a.id: a
        for a in db.query(CatalogProduct).filter(
            CatalogProduct.id.in_(alt_ids),
            CatalogProduct.is_active.is_(True),
            CatalogProduct.deleted_at.is_(None),
        ).all()
    } if alt_ids else {}
    missing_stock = [aid for aid in alt_ids if aid not in stock]
    if missing_stock:
        stock.update(_stock_map(db, missing_stock))
    grouped: dict[int, List[ShopAlternativePublic]] = {pid: [] for pid in parent_ids}
    for row in rows:
        alt_prod = alts.get(row.alternative_product_id)
        if not alt_prod:
            continue
        qty, th = stock.get(alt_prod.id, (0, 5))
        lbl = _portal_stock_status(qty, th)
        if lbl == "out_of_stock":
            continue
        grouped.setdefault(row.product_id, []).append(
            ShopAlternativePublic(
                catalog_product_id=alt_prod.id,
                our_product_id=alt_prod.our_product_id,
                image_url=_image_url(alt_prod),
                stock_status=lbl,
                selling_price=_sell_price(alt_prod),
                category=alt_prod.category,
            )
        )
    return grouped

@router.get("/products/search", response_model=List[ShopProductPublic])
def product_search(
    q: str = Query(..., min_length=1, max_length=200),
    db: Session = Depends(get_db),
    _customer: Customer = Depends(get_current_customer),
):
    raw = _norm_q(q)
    if not raw:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="search text empty")
    cache_key = f"shop:search:{raw.lower()}"
    cached = response_cache.get(cache_key)
    if cached is not None:
        return cached

    rows = _query_products(db, raw, 20)
    ids = [p.id for p in rows]
    stock = _stock_map(db, ids)
    addon_map = addon_snapshots_map(db, ids)
    need_alts = [
        p.id for p in rows
        if stock_status_label(*stock.get(p.id, (0, 5))) == "out_of_stock"
    ]
    alt_map = _alternatives_batch(db, need_alts, stock)
    out = [
        _to_shop_product(
            p,
            qty=stock.get(p.id, (0, 5))[0],
            th=stock.get(p.id, (0, 5))[1],
            addons=addon_map.get(p.id) or [],
            alts=alt_map.get(p.id) or [],
        )
        for p in rows
    ]
    payload = [x.model_dump() for x in out]
    response_cache.set(cache_key, payload, 12.0)
    return out

def _to_shop_product(
    p: CatalogProduct,
    *,
    qty: int,
    th: int,
    addons: list[dict],
    alts: List[ShopAlternativePublic],
) -> ShopProductPublic:
    raw_lbl = stock_status_label(qty, th)
    lbl = _portal_stock_status(qty, th)
    return ShopProductPublic(
        catalog_product_id=p.id,
        our_product_id=p.our_product_id,
        image_url=_image_url(p),
        selling_price=_sell_price(p),
        stock_status=lbl,
        category=p.category,
        year_group=p.year_group,
        addons=[
            ShopAddonPublic(
                our_product_id=a["our_product_id"],
                name=a["name"],
                quantity=a["quantity"],
                unit=a.get("unit") or "pc",
                image_url=a.get("image_url") or "",
            )
            for a in addons
        ],
        # Offer swaps only when truly unavailable — not on low stock.
        alternatives=alts if raw_lbl == "out_of_stock" else [],
    )

@router.get("/products/suggestions", response_model=List[ShopSuggestionPublic])
def product_suggestions(
    q: str = Query(..., min_length=1, max_length=200),
    db: Session = Depends(get_db),
    _customer: Customer = Depends(get_current_customer),
):
    raw = _norm_q(q)
    if not raw:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="search text empty")
    cache_key = f"shop:suggest:{raw.lower()}"
    cached = response_cache.get(cache_key)
    if cached is not None:
        return cached

    rows = _query_products(db, raw, 25)
    stock = _stock_map(db, [r.id for r in rows])
    out = [
        ShopSuggestionPublic(
            catalog_product_id=r.id,
            our_product_id=r.our_product_id,
            image_url=_image_url(r),
            selling_price=_sell_price(r),
            stock_status=_portal_stock_status(*stock.get(r.id, (0, 5))),
            category=r.category,
        )
        for r in rows
    ]
    payload = [x.model_dump() for x in out]
    response_cache.set(cache_key, payload, 15.0)
    return out

def _query_products(db: Session, raw: str, limit: int) -> list[CatalogProduct]:
    # Exact-code fast path (dealer types full product name/code like 9500).
    exact = (
        db.query(CatalogProduct)
        .filter(
            CatalogProduct.is_active.is_(True),
            CatalogProduct.deleted_at.is_(None),
            or_(
                CatalogProduct.our_product_id == raw,
                CatalogProduct.vendor_product_id == raw,
            ),
        )
        .limit(limit)
        .all()
    )
    if exact and len(raw) >= 2:
        return _rank_products(exact, raw)[:limit]
    rows = (
        db.query(CatalogProduct)
        .filter(CatalogProduct.is_active.is_(True), CatalogProduct.deleted_at.is_(None), _match(raw))
        .limit(80)
        .all()
    )
    return _rank_products(rows, raw)[:limit]

def _rank_products(rows: list[CatalogProduct], raw: str) -> list[CatalogProduct]:
    """Exact → prefix → contains. Avoids '4' ranking '1045' first."""
    q = (raw or "").strip().lower()

    def score(p: CatalogProduct) -> tuple:
        oid = (p.our_product_id or "").lower()
        vid = (p.vendor_product_id or "").lower()
        if oid == q or vid == q:
            s = 100
        elif oid.startswith(q) or vid.startswith(q):
            s = 80
        elif q in oid or q in vid:
            s = 40
        else:
            s = 10
        return (-s, oid)

    return sorted(rows, key=score)

def _find_bill_for_line(db: Session, customer_id: int, catalog_product_id: int, placed_at) -> Optional[CustomerBill]:
    q = (
        db.query(CustomerBill)
        .join(CustomerBillLine, CustomerBillLine.bill_id == CustomerBill.id)
        .filter(
            CustomerBill.customer_id == customer_id,
            CustomerBillLine.catalog_product_id == catalog_product_id,
            CustomerBill.deleted_at.is_(None),
        )
    )
    if placed_at is not None:
        q = q.filter(CustomerBill.created_at >= placed_at)
    return q.order_by(CustomerBill.created_at.desc()).first()

def _image_url_from_keys(keys) -> str:
    for key in keys or []:
        if not key or not isinstance(key, str):
            continue
        key = key.strip()
        if not key:
            continue
        from app.routers import shop as shop_mod

        url = shop_mod.presigned_url(key)
        if url:
            return url
    return ""

def _fmt_price(val) -> str:
    if val is None:
        return "0"
    try:
        d = Decimal(str(val))
        if d <= 0:
            return "0"
        return format(d, "f")
    except Exception:
        return "0"

def _match(raw: str):
    term = f"%{raw}%"
    return or_(
        CatalogProduct.our_product_id == raw,
        CatalogProduct.vendor_product_id == raw,
        CatalogProduct.our_product_id.ilike(term),
        CatalogProduct.vendor_product_id.ilike(term),
    )

def _stock_map(db: Session, product_ids: list[int]) -> dict[int, tuple[int, int]]:
    if not product_ids:
        return {}
    rows = db.query(StockBalance).filter(StockBalance.catalog_product_id.in_(product_ids)).all()
    out = {int(r.catalog_product_id): (int(r.quantity_on_hand), int(r.low_stock_threshold or 5)) for r in rows}
    for pid in product_ids:
        out.setdefault(pid, (0, 5))
    return out

def _card_line_for_product(view: dict, catalog_product_id: int) -> dict:
    for ln in view.get("lines") or []:
        if not isinstance(ln, dict):
            continue
        if int(ln.get("catalog_product_id") or 0) == int(catalog_product_id):
            return ln
    return {}

def _sell_price(prod: CatalogProduct) -> str:
    from app.services.pricing import effective_selling_price

    eff = effective_selling_price(prod.buying_price, prod.selling_price)
    if eff is not None and eff > 0:
        return _fmt_price(eff)
    return "0"

def _dealer_status(qty: int, shipped: int) -> str:
    if shipped <= 0:
        return "ordered"
    if shipped >= qty:
        return "completed"
    return "partly_sent"

def _image_url(prod: CatalogProduct | None) -> str:
    if not prod:
        return ""
    return _image_url_from_keys(prod.image_keys)

def _portal_stock_status(qty: int, th: int) -> str:
    """Dealer-facing stock: available vs not. Never leak low-stock or on-hand qty."""
    lbl = stock_status_label(qty, th)
    return "out_of_stock" if lbl == "out_of_stock" else "in_stock"

def _norm_q(q: str) -> str:
    s = unicodedata.normalize("NFKC", (q or "").strip())
    return " ".join(s.split())

def _legacy_status(dealer_st: str) -> str:
    return {"ordered": "submitted", "partly_sent": "partial", "completed": "shipped"}.get(dealer_st, "submitted")

