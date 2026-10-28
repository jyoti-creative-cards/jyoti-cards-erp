"""Same party, same day: warn when an item or the order total is already booked."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.catalog_product import CatalogProduct
from app.models.customer_order import CustomerOrder, CustomerOrderLine, CustomerOrderPlacement
from app.services.biz_date import ist_day_bounds_utc, today_ist
from app.services.pricing import effective_selling_price


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def _priced_lines(db: Session, lines: list[dict]) -> list[dict]:
    product_ids = [int(ln["catalog_product_id"]) for ln in lines if int(ln.get("quantity") or 0) > 0]
    products = {
        p.id: p
        for p in db.query(CatalogProduct).filter(CatalogProduct.id.in_(set(product_ids))).all()
    } if product_ids else {}
    priced = []
    for ln in lines:
        qty = int(ln.get("quantity") or 0)
        if qty <= 0:
            continue
        cid = int(ln["catalog_product_id"])
        prod = products.get(cid)
        if ln.get("unit_price") is not None:
            unit = _money(ln["unit_price"])
        else:
            unit = effective_selling_price(
                prod.buying_price if prod else None,
                prod.selling_price if prod else None,
            )
            unit = _money(unit)
        priced.append({
            "catalog_product_id": cid,
            "our_product_id": (prod.our_product_id if prod else None) or str(cid),
            "quantity": qty,
            "line_total": (unit * qty).quantize(Decimal("0.01")),
        })
    return priced


def same_day_order_clashes(
    db: Session,
    *,
    customer_id: int,
    lines: list[dict],
    placed_on: date | None,
    ignore_placement_id: int | None = None,
) -> list[dict]:
    incoming = _priced_lines(db, lines)
    if not incoming:
        return []
    incoming_ids = {row["catalog_product_id"] for row in incoming}
    incoming_names = {row["catalog_product_id"]: row["our_product_id"] for row in incoming}
    incoming_total = sum((row["line_total"] for row in incoming), Decimal("0.00"))
    start, end = ist_day_bounds_utc(placed_on or today_ist())
    placements = (
        db.query(CustomerOrderPlacement)
        .join(CustomerOrder, CustomerOrder.id == CustomerOrderPlacement.customer_order_id)
        .filter(
            CustomerOrder.customer_id == customer_id,
            CustomerOrder.bucket != "cancelled",
            CustomerOrderPlacement.deleted_at.is_(None),
            CustomerOrderPlacement.status != "cancelled",
            CustomerOrderPlacement.placed_at >= start,
            CustomerOrderPlacement.placed_at < end,
        )
        .all()
    )
    clashes = []
    for placement in placements:
        if ignore_placement_id and placement.id == ignore_placement_id:
            continue
        existing = (
            db.query(CustomerOrderLine)
            .filter(
                CustomerOrderLine.placement_id == placement.id,
                CustomerOrderLine.status != "cancelled",
            )
            .all()
        )
        if not existing:
            continue
        shared = []
        total = Decimal("0.00")
        for ln in existing:
            total += (_money(ln.unit_price) * int(ln.quantity or 0)).quantize(Decimal("0.01"))
            if ln.catalog_product_id in incoming_ids:
                shared.append(ln.our_product_id or incoming_names.get(ln.catalog_product_id) or str(ln.catalog_product_id))
        same_amount = total == incoming_total
        if not shared and not same_amount:
            continue
        clashes.append({
            "placement_id": placement.id,
            "same_items": shared,
            "same_amount": same_amount,
            "total": format(total, "f"),
        })
    return clashes
