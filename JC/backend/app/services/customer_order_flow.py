from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.catalog_product import CatalogProduct
from app.models.customer_order import CustomerOpenLine, CustomerOrder, CustomerOrderLine, CustomerOrderPlacement
from app.models.stock import StockBalance
from app.services.stock_receipt import add_stock


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
    order = CustomerOrder(customer_id=customer_id, bucket=bucket, status=status, is_open=True)
    db.add(order)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        order = get_open_customer_order(db, customer_id, bucket)
        if not order:
            raise
    return order


def _get_or_create_open_line(db: Session, customer_id: int, catalog_product_id: int, unit_price: Decimal) -> CustomerOpenLine:
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
    row = CustomerOpenLine(
        customer_id=customer_id,
        catalog_product_id=catalog_product_id,
        our_product_id=prod.our_product_id,
        quantity_received=0,
        quantity_open=0,
        quantity_billed=0,
        unit_price=unit_price,
        status="open",
    )
    db.add(row)
    db.flush()
    return row


def add_to_customer_open(db: Session, customer_id: int, lines: list[tuple[int, int, Decimal]]) -> None:
    for catalog_product_id, qty, price in lines:
        if qty <= 0:
            continue
        row = _get_or_create_open_line(db, customer_id, catalog_product_id, price)
        row.quantity_received += qty
        row.quantity_open += qty
        row.status = "open"


def reserve_stock(db: Session, *, catalog_product_id: int, our_product_id: str, quantity: int, reference_id: int, party: str) -> None:
    balance = db.query(StockBalance).filter(StockBalance.catalog_product_id == catalog_product_id).first()
    if not balance:
        balance = StockBalance(catalog_product_id=catalog_product_id, quantity_on_hand=0)
        db.add(balance)
        db.flush()
    if balance.quantity_on_hand < quantity:
        raise ValueError("insufficient stock")
    add_stock(
        db,
        catalog_product_id=catalog_product_id,
        our_product_id=our_product_id,
        quantity=-quantity,
        entry_type="reserved",
        reference_type="customer_placement",
        reference_id=reference_id,
        party=party,
        notes=f"Customer order reserved {quantity}",
    )


def restore_stock(db: Session, *, catalog_product_id: int, our_product_id: str, quantity: int, reference_id: int, party: str, notes: str) -> None:
    if quantity <= 0:
        return
    add_stock(
        db,
        catalog_product_id=catalog_product_id,
        our_product_id=our_product_id,
        quantity=quantity,
        entry_type="unreserved",
        reference_type="customer_placement",
        reference_id=reference_id,
        party=party,
        notes=notes,
    )


def create_portal_placement(
    db: Session,
    *,
    customer_id: int,
    customer_name: str,
    catalog_product_id: int,
    quantity: int,
    unit_price: Decimal,
    customer_notes: str | None,
    addons_json: list | None = None,
) -> CustomerOrderPlacement:
    prod = db.get(CatalogProduct, catalog_product_id)
    if not prod:
        raise ValueError("product not found")

    received = get_or_create_customer_order(db, customer_id, "received", "received")
    placement = CustomerOrderPlacement(
        customer_order_id=received.id,
        status="received",
        customer_notes=customer_notes,
        placed_at=datetime.now(timezone.utc),
    )
    db.add(placement)
    db.flush()

    db.add(
        CustomerOrderLine(
            placement_id=placement.id,
            catalog_product_id=prod.id,
            our_product_id=prod.our_product_id,
            quantity=quantity,
            quantity_billed=0,
            unit_price=unit_price,
            addons_json=addons_json or None,
            status="active",
        )
    )
    reserve_stock(
        db,
        catalog_product_id=prod.id,
        our_product_id=prod.our_product_id,
        quantity=quantity,
        reference_id=placement.id,
        party=customer_name,
    )
    add_to_customer_open(db, customer_id, [(prod.id, quantity, unit_price)])
    received.updated_at = datetime.now(timezone.utc)
    return placement
