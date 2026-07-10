from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class VendorOrder(Base):
    """One running order bucket per vendor until procurement closes it."""

    __tablename__ = "jc_vendor_orders"
    __table_args__ = (
        Index("ix_jc_vendor_orders_vendor_open", "vendor_id", "bucket", "is_open"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vendor_id: Mapped[int] = mapped_column(Integer, ForeignKey("jc_vendors.id", ondelete="RESTRICT"), nullable=False, index=True)
    bucket: Mapped[str] = mapped_column(String(20), nullable=False, default="placed", server_default="placed", index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="placed", server_default="placed")
    is_open: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class VendorOrderPlacement(Base):
    __tablename__ = "jc_vendor_order_placements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vendor_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jc_vendor_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="placed", server_default="placed")
    placed_by_type: Mapped[str] = mapped_column(String(20), nullable=False)
    placed_by_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    placed_by_name: Mapped[str] = mapped_column(String(200), nullable=False)
    document_key: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    close_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class VendorOrderLine(Base):
    __tablename__ = "jc_vendor_order_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    placement_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jc_vendor_order_placements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    catalog_product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jc_catalog_products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    our_product_id: Mapped[str] = mapped_column(String(120), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_remaining: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_billed: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    billed_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    buying_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
