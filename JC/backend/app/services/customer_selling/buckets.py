from __future__ import annotations
"""Split from app/services/customer_order_flow.py."""

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.catalog_product import CatalogProduct
from app.models.customer_order import CustomerOpenLine, CustomerOrder, CustomerOrderLine, CustomerOrderPlacement
from app.models.stock import StockBalance
from app.services.stock_receipt import add_stock
from app.services.addon_stock import deduct_addons_for_product


def get_open_customer_order(db: Session, customer_id: int, bucket: str) -> CustomerOrder | None:
    return (
        db.query(CustomerOrder)
        .filter(CustomerOrder.customer_id == customer_id, CustomerOrder.bucket == bucket, CustomerOrder.is_open.is_(True))
        .first()
    )

def get_or_create_customer_order(db: Session, customer_id: int, bucket: str, status: str) -> CustomerOrder:
    from sqlalchemy.exc import IntegrityError

    order = get_open_customer_order(db, customer_id, bucket)
    if order:
        return order
    try:
        with db.begin_nested():
            now = datetime.now(timezone.utc)
            # Set updated_at explicitly (not just server_default) — day-scoping queries
            # compare it against tz-aware IST-day bounds, and a raw server-side
            # CURRENT_TIMESTAMP bypasses the column's tz-aware bind/result processing.
            order = CustomerOrder(
                customer_id=customer_id, bucket=bucket, status=status, is_open=True,
                created_at=now, updated_at=now,
            )
            db.add(order)
            db.flush()
    except IntegrityError:
        order = get_open_customer_order(db, customer_id, bucket)
        if not order:
            raise
    return order

def _get_or_create_open_line(
    db: Session,
    customer_id: int,
    catalog_product_id: int,
    unit_price: Decimal,
    *,
    as_of: datetime | None = None,
) -> CustomerOpenLine:
    prod = db.get(CatalogProduct, catalog_product_id)
    if not prod:
        raise ValueError("product not found")
    row = (
        db.query(CustomerOpenLine)
        .filter(CustomerOpenLine.customer_id == customer_id, CustomerOpenLine.catalog_product_id == catalog_product_id)
        .first()
    )
    if row:
        if row.status != "open":
            row.status = "open"
        row.unit_price = unit_price
        row.our_product_id = prod.our_product_id
        return row
    from sqlalchemy.exc import IntegrityError

    new_row = CustomerOpenLine(
        customer_id=customer_id,
        catalog_product_id=catalog_product_id,
        our_product_id=prod.our_product_id,
        quantity_received=0,
        quantity_open=0,
        quantity_billed=0,
        unit_price=unit_price,
        status="open",
    )
    if as_of is not None:
        new_row.created_at = as_of
    try:
        with db.begin_nested():
            db.add(new_row)
            db.flush()
    except IntegrityError:
        # CustomerOpenLine has a real UniqueConstraint(customer_id, catalog_product_id) —
        # a concurrent request can win the insert race between our SELECT above and this
        # INSERT. Without this retry, that 500s the whole cancel/edit-bill request even
        # though the other request's write succeeded fine.
        row = (
            db.query(CustomerOpenLine)
            .filter(CustomerOpenLine.customer_id == customer_id, CustomerOpenLine.catalog_product_id == catalog_product_id)
            .first()
        )
        if not row:
            raise
        return row
    return new_row

def add_to_customer_open(
    db: Session,
    customer_id: int,
    lines: list[tuple[int, int, Decimal]],
    *,
    as_of: datetime | None = None,
) -> None:
    for catalog_product_id, qty, price in lines:
        if qty <= 0:
            continue
        row = _get_or_create_open_line(db, customer_id, catalog_product_id, price, as_of=as_of)
        row.quantity_received += qty
        row.quantity_open += qty
        row.status = "open"

