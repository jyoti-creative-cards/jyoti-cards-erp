from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class VendorReceiptLine(Base):
    """One row per item per partial shipment.

    Every time goods are received against a vendor order, one row is inserted
    per catalog product received. This is the authoritative audit trail for
    all incoming stock — queryable by product, vendor, date, price etc.

    Relationships:
        vendor_bill_id  → portal_vendor_bills.id  (one bill per shipment)
        vendor_order_id → portal_vendor_orders.id (which PO it came against)
        vendor_id       → portal_vendors.id
    """

    __tablename__ = "portal_vendor_receipt_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # FK to the bill/receipt batch this line belongs to
    vendor_bill_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("portal_vendor_bills.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    # FK to the placed order (None for ad-hoc receipts)
    vendor_order_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("portal_vendor_orders.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    vendor_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("portal_vendors.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    catalog_product_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("portal_catalog_products.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    # Denormalized for fast reads / reporting without joins
    product_name: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    order_line_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # JSONB line_id

    # Quantities
    qty_received: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    qty_billed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Prices
    order_price: Mapped[Optional[float]] = mapped_column(
        Numeric(14, 4), nullable=True,
        comment="Unit price we placed the order at",
    )
    billed_price: Mapped[Optional[float]] = mapped_column(
        Numeric(14, 4), nullable=True,
        comment="Unit price on vendor's bill for this shipment",
    )

    # Computed discrepancy stored for fast reporting (can always be recalculated)
    qty_discrepancy: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
        comment="qty_billed - qty_received; positive = vendor billed more than delivered",
    )
    price_discrepancy: Mapped[Optional[float]] = mapped_column(
        Numeric(14, 4), nullable=True,
        comment="billed_price - order_price; positive = vendor charged more than PO price",
    )

    receipt_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True,
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
