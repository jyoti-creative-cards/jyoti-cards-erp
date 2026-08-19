"""Add-on products — packaging, accessories, freebies that come with catalog products.

Add-ons are sourced from vendors just like catalog products but are never sold individually.
Each catalog product can have 1 or many add-ons linked to it.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, Numeric,
    String, UniqueConstraint, func, true as sql_true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class AddonProduct(Base):
    """Master list of add-on items sourced from vendors."""

    __tablename__ = "portal_addon_products"
    __table_args__ = (
        UniqueConstraint("our_product_id", name="uq_addon_our_product_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Identity fields — same pattern as CatalogProduct
    our_product_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    vendor_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("portal_vendors.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    vendor_product_id: Mapped[str] = mapped_column(String(255), nullable=False)

    name: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    unit: Mapped[str] = mapped_column(String(50), nullable=False, server_default="pcs")
    buying_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, server_default="0")

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=sql_true())
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AddonStock(Base):
    """On-hand stock per add-on."""

    __tablename__ = "portal_addon_stock"

    addon_product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("portal_addon_products.id", ondelete="CASCADE"), primary_key=True
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class CatalogProductAddon(Base):
    """Maps a catalog product to its add-on(s). 1 product → many add-ons."""

    __tablename__ = "portal_catalog_product_addons"
    __table_args__ = (
        UniqueConstraint("catalog_product_id", "addon_product_id", name="uq_catalog_addon_link"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    catalog_product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("portal_catalog_products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    addon_product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("portal_addon_products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    quantity_per_unit: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
