from __future__ import annotations

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
from app.services.storage import download_bytes, presigned_url, storage_configured
from app.services.stock_levels import stock_status_label

router = APIRouter(prefix="/shop", tags=["shop"])
logger = logging.getLogger("jc.shop")


def _norm_q(q: str) -> str:
    s = unicodedata.normalize("NFKC", (q or "").strip())
    return " ".join(s.split())


def _match(raw: str):
    term = f"%{raw}%"
    return or_(
        CatalogProduct.our_product_id == raw,
        CatalogProduct.vendor_product_id == raw,
        CatalogProduct.our_product_id.ilike(term),
        CatalogProduct.vendor_product_id.ilike(term),
    )


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


def _image_url(prod: CatalogProduct | None) -> str:
    if not prod:
        return ""
    for key in prod.image_keys or []:
        if not key or not isinstance(key, str):
            continue
        key = key.strip()
        if not key:
            continue
        url = presigned_url(key)
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


def _sell_price(prod: CatalogProduct) -> str:
    from app.services.pricing import effective_selling_price

    eff = effective_selling_price(prod.buying_price, prod.selling_price)
    if eff is not None and eff > 0:
        return _fmt_price(eff)
    return "0"


def _stock_map(db: Session, product_ids: list[int]) -> dict[int, tuple[int, int]]:
    if not product_ids:
        return {}
    rows = db.query(StockBalance).filter(StockBalance.catalog_product_id.in_(product_ids)).all()
    out = {int(r.catalog_product_id): (int(r.quantity_on_hand), int(r.low_stock_threshold or 5)) for r in rows}
    for pid in product_ids:
        out.setdefault(pid, (0, 5))
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


def _portal_stock_status(qty: int, th: int) -> str:
    """Dealer-facing stock: available vs not. Never leak low-stock or on-hand qty."""
    lbl = stock_status_label(qty, th)
    return "out_of_stock" if lbl == "out_of_stock" else "in_stock"


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


def _staff_notify_phones() -> list[str]:
    raw = (get_settings().whatsapp_staff_notify_phones or "").strip()
    if not raw:
        return []
    return [p.strip() for p in re.split(r"[,;\s]+", raw) if p.strip()]


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
        doc_key = None
        doc_url = None
        if storage_configured():
            try:
                doc_key = generate_customer_order_document(db, placement.id)
                doc_url = presigned_url(doc_key) if doc_key else None
            except Exception:
                logger.exception("order PDF failed placement=%s", placement.id)
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
        document_key=doc_key,
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
        "document_key": doc_key,
        "document_url": doc_url,
        "whatsapp_sent": True,
    }


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
    if not placement.document_key:
        if storage_configured():
            try:
                generate_customer_order_document(db, placement.id)
                db.commit()
            except Exception:
                db.rollback()
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
        if not bill.document_key:
            raise HTTPException(404, "document not available")
    url = presigned_url(bill.document_key)
    if not url:
        raise HTTPException(503, "storage not available")
    return {"document_url": url, "document_key": bill.document_key, "bill_number": bill.bill_number}


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


def _dealer_status(qty: int, shipped: int) -> str:
    if shipped <= 0:
        return "ordered"
    if shipped >= qty:
        return "completed"
    return "partly_sent"


def _legacy_status(dealer_st: str) -> str:
    return {"ordered": "submitted", "partly_sent": "partial", "completed": "shipped"}.get(dealer_st, "submitted")


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
            prod = db.get(CatalogProduct, ln.catalog_product_id)
            bill = _find_bill_for_line(db, customer.id, ln.catalog_product_id, p.placed_at) if shipped > 0 else None
            line_total = (ln.unit_price * ln.quantity).quantize(Decimal("0.01"))
            total += line_total
            hist_lines.append(
                ShopOrderHistoryLine(
                    catalog_product_id=ln.catalog_product_id,
                    our_product_id=ln.our_product_id,
                    image_url=_image_url(prod) if prod else "",
                    quantity=qty,
                    quantity_shipped=shipped,
                    unit_price=format(ln.unit_price, "f"),
                    line_total=format(line_total, "f"),
                    category=prod.category if prod else None,
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
                    our_product_id=ln.our_product_id,
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
