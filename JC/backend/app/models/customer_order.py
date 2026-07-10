from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class CustomerOrder(Base):
    """One running order bucket per customer (received / open / billed / cancelled / closed)."""

    __tablename__ = "jc_customer_orders"
    __table_args__ = (Index("ix_jc_customer_orders_customer_open", "customer_id", "bucket", "is_open"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(Integer, ForeignKey("jc_customers.id", ondelete="RESTRICT"), nullable=False, index=True)
    bucket: Mapped[str] = mapped_column(String(20), nullable=False, default="received", server_default="received", index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="received", server_default="received")
    is_open: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class CustomerOrderPlacement(Base):
    __tablename__ = "jc_customer_order_placements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jc_customer_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="received", server_default="received")
    customer_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    document_key: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    cancel_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CustomerOrderLine(Base):
    __tablename__ = "jc_customer_order_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    placement_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jc_customer_order_placements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    catalog_product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jc_catalog_products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    our_product_id: Mapped[str] = mapped_column(String(120), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_billed: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    addons_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    cancel_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class CustomerOpenLine(Base):
    """Operational open-order line per customer+product (pending to ship)."""

    __tablename__ = "jc_customer_open_lines"
    __table_args__ = (UniqueConstraint("customer_id", "catalog_product_id", name="uq_jc_customer_open_line"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(Integer, ForeignKey("jc_customers.id", ondelete="CASCADE"), nullable=False, index=True)
    catalog_product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jc_catalog_products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    our_product_id: Mapped[str] = mapped_column(String(120), nullable=False)
    quantity_received: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quantity_open: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quantity_billed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", server_default="open", index=True)
    cancel_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
