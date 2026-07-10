from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.catalog_product import CatalogProduct
from app.models.stock import StockBalance, StockLedger, StockReceipt, StockReceiptLine
from app.models.vendor_order import VendorOrder, VendorOrderLine, VendorOrderPlacement


def get_open_order(db: Session, vendor_id: int, bucket: str) -> VendorOrder | None:
    return (
        db.query(VendorOrder)
        .filter(
            VendorOrder.vendor_id == vendor_id,
            VendorOrder.bucket == bucket,
            VendorOrder.is_open.is_(True),
        )
        .first()
    )


def get_or_create_open_order(db: Session, vendor_id: int, bucket: str, status: str) -> VendorOrder:
    from sqlalchemy.exc import IntegrityError

    order = get_open_order(db, vendor_id, bucket)
    if order:
        return order
    order = VendorOrder(vendor_id=vendor_id, bucket=bucket, status=status, is_open=True)
    db.add(order)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        order = get_open_order(db, vendor_id, bucket)
        if not order:
            raise
    return order


def add_stock(
    db: Session,
    *,
    catalog_product_id: int,
    our_product_id: str,
    quantity: int,
    entry_type: str,
    reference_type: str,
    reference_id: int,
    party: str | None = None,
    notes: str | None = None,
) -> StockBalance:
    balance = db.query(StockBalance).filter(StockBalance.catalog_product_id == catalog_product_id).first()
    if not balance:
        balance = StockBalance(catalog_product_id=catalog_product_id, quantity_on_hand=0)
        db.add(balance)
        db.flush()
    balance.quantity_on_hand += quantity
    db.add(
        StockLedger(
            catalog_product_id=catalog_product_id,
            entry_type=entry_type,
            quantity_delta=quantity,
            balance_after=balance.quantity_on_hand,
            reference_type=reference_type,
            reference_id=reference_id,
            party=party,
            notes=notes,
        )
    )
    return balance
