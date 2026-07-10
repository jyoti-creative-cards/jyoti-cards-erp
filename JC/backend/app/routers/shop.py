from __future__ import annotations

import unicodedata
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import get_current_customer
from app.models.catalog_alternative import CatalogAlternative
from app.models.catalog_product import CatalogProduct
from app.models.customer import Customer
from app.models.customer_bill import CustomerBill, CustomerBillLine
from app.models.customer_order import CustomerOrder, CustomerOrderLine, CustomerOrderPlacement
from app.models.stock import StockBalance
from app.schemas.shop import (
    CustomerOrderCreate,
    PortalPlacementPublic,
    ShopAlternativePublic,
    ShopAddonPublic,
    ShopProductPublic,
    ShopSuggestionPublic,
)
from app.services.catalog_addons import addon_snapshots_for_product
from app.services.customer_order_flow import create_portal_placement
from app.services.doc_gen import generate_customer_bill_document, generate_customer_order_document
from app.services.storage import presigned_url, storage_configured
from app.services.stock_levels import stock_status_label
from app.services.storage import presigned_urls

router = APIRouter(prefix="/shop", tags=["shop"])


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


def _qty_threshold(db: Session, catalog_product_id: int) -> tuple[int, int]:
    bal = db.query(StockBalance).filter(StockBalance.catalog_product_id == catalog_product_id).first()
    if not bal:
        return 0, 5
    return int(bal.quantity_on_hand), int(bal.low_stock_threshold or 5)


def _image_url(prod: CatalogProduct) -> str:
    urls = presigned_urls(prod.image_keys or [])
    return urls[0] if urls else ""


def _customer_status_label(qty: int, threshold: int) -> str:
    label = stock_status_label(qty, threshold)
    return label


def _fmt_price(val) -> str:
    if val is None:
        return "0"
    try:
        return format(Decimal(str(val)), "f")
    except Exception:
        return "0"


def _alternatives_in_stock(db: Session, parent_id: int) -> List[ShopAlternativePublic]:
    rows = db.query(CatalogAlternative).filter(CatalogAlternative.product_id == parent_id).all()
    out: List[ShopAlternativePublic] = []
    for alt in rows:
        alt_prod = db.get(CatalogProduct, alt.alternative_product_id)
        if not alt_prod or not alt_prod.is_active or alt_prod.deleted_at:
            continue
        qty, th = _qty_threshold(db, alt_prod.id)
        lbl = _customer_status_label(qty, th)
        if lbl == "out_of_stock":
            continue
        out.append(
            ShopAlternativePublic(
                catalog_product_id=alt_prod.id,
                our_product_id=alt_prod.our_product_id,
                image_url=_image_url(alt_prod),
                stock_status=lbl,
                selling_price=_fmt_price(alt_prod.selling_price),
            )
        )
    return out


@router.get("/products/suggestions", response_model=List[ShopSuggestionPublic])
def product_suggestions(
    q: str = Query(..., min_length=1, max_length=200),
    db: Session = Depends(get_db),
    _customer: Customer = Depends(get_current_customer),
):
    raw = _norm_q(q)
    if not raw:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="search text empty")
    rows = (
        db.query(CatalogProduct)
        .filter(CatalogProduct.is_active.is_(True), CatalogProduct.deleted_at.is_(None), _match(raw))
        .order_by(CatalogProduct.our_product_id.asc())
        .limit(25)
        .all()
    )
    return [ShopSuggestionPublic(catalog_product_id=r.id, our_product_id=r.our_product_id) for r in rows]


@router.get("/products/search", response_model=List[ShopProductPublic])
def product_search(
    q: str = Query(..., min_length=1, max_length=200),
    db: Session = Depends(get_db),
    _customer: Customer = Depends(get_current_customer),
):
    raw = _norm_q(q)
    if not raw:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="search text empty")
    rows = (
        db.query(CatalogProduct)
        .filter(CatalogProduct.is_active.is_(True), CatalogProduct.deleted_at.is_(None), _match(raw))
        .order_by(CatalogProduct.our_product_id.asc())
        .limit(20)
        .all()
    )
    out: List[ShopProductPublic] = []
    for p in rows:
        qty, th = _qty_threshold(db, p.id)
        lbl = _customer_status_label(qty, th)
        alts: List[ShopAlternativePublic] = []
        if lbl in ("out_of_stock", "low_stock"):
            alts = _alternatives_in_stock(db, p.id)
        out.append(
            ShopProductPublic(
                catalog_product_id=p.id,
                our_product_id=p.our_product_id,
                image_url=_image_url(p),
                selling_price=_fmt_price(p.selling_price),
                stock_status=lbl,
                addons=[
                    ShopAddonPublic(
                        our_product_id=a["our_product_id"],
                        name=a["name"],
                        quantity=a["quantity"],
                        unit=a.get("unit") or "pc",
                        image_url=a.get("image_url") or "",
                    )
                    for a in addon_snapshots_for_product(db, p.id)
                ],
                alternatives=alts,
            )
        )
    return out


@router.post("/orders", status_code=status.HTTP_201_CREATED)
def create_customer_order(
    body: CustomerOrderCreate,
    db: Session = Depends(get_db),
    customer: Customer = Depends(get_current_customer),
):
    prod = db.get(CatalogProduct, body.catalog_product_id)
    if not prod or not prod.is_active or prod.deleted_at:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="product not found")

    qty, th = _qty_threshold(db, prod.id)
    status_lbl = _customer_status_label(qty, th)
    if status_lbl == "out_of_stock":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="product is out of stock")
    if body.quantity > qty:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Insufficient inventory. Please call godown to book order.",
        )

    unit_price = prod.selling_price if prod.selling_price is not None else Decimal("0")
    if unit_price <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Price not set for this product. Please contact godown.")
    addons = addon_snapshots_for_product(db, prod.id)
    try:
        placement = create_portal_placement(
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
                pass
        db.commit()
    except ValueError as e:
        db.rollback()
        if "insufficient" in str(e).lower():
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="Insufficient inventory. Please call godown to book order.",
            ) from e
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Order could not be saved. Please try again.") from e

    return {
        "ok": True,
        "placement_id": placement.id,
        "our_product_id": prod.our_product_id,
        "quantity": body.quantity,
        "unit_price": format(unit_price, "f"),
        "line_total": format(unit_price * body.quantity, "f"),
        "message": "Your order has been submitted successfully.",
        "document_key": doc_key,
        "document_url": doc_url,
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
    if not bill.document_key:
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
        )
    )
    if placed_at is not None:
        q = q.filter(CustomerBill.created_at >= placed_at)
    return q.order_by(CustomerBill.created_at.desc()).first()


@router.get("/orders", response_model=List[PortalPlacementPublic])
def list_my_orders(
    db: Session = Depends(get_db),
    customer: Customer = Depends(get_current_customer),
):
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
        .filter(CustomerOrderPlacement.customer_order_id == received.id, CustomerOrderPlacement.status == "received")
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
            if shipped <= 0:
                status = "submitted"
            elif shipped >= qty:
                status = "shipped"
            else:
                status = "partial"
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
                    status=status,
                    customer_notes=p.customer_notes,
                    placed_at=p.placed_at.isoformat(),
                    bill_id=bill.id if bill else None,
                    bill_number=bill.bill_number if bill else None,
                    has_bill_document=bool(bill and bill.document_key) or bool(bill),
                    has_order_document=bool(p.document_key),
                )
            )
    return out
