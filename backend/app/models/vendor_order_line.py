from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class VendorOrderLine(Base):
    """One row per product per vendor order.

    Replaces the JSONB ``items`` blob on ``portal_vendor_orders``.
    Partial-shipment tracking (qty_received, qty_billed) is updated here
    as goods arrive, keeping a single authoritative source.

    Relationships:
        vendor_order_id → portal_vendor_orders.id
        catalog_product_id → portal_catalog_products.id
    """

    __tablename__ = "portal_vendor_order_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # UUID string kept for frontend compatibility (existing wizards key by line_id)
    line_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)

    vendor_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("portal_vendor_orders.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    catalog_product_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("portal_catalog_products.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    # Denormalized display fields — avoids joins on every list view
    product_name: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    our_product_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)

    # Sub-order number: increments each time items are added to this order (batch grouping)
    sub_order_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1, index=True)

    # Order quantities
    qty_ordered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    qty_received: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    qty_billed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Prices
    unit_price: Mapped[float] = mapped_column(
        Numeric(14, 4), nullable=False, default=0,
        comment="Price agreed at order time",
    )
    billed_price: Mapped[Optional[float]] = mapped_column(
        Numeric(14, 4), nullable=True,
        comment="Last billed unit price (updated on each receipt)",
    )

    date_ordered: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    date_received: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
