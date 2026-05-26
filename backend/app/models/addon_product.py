"""Add-on products — murti, stickers, freebies etc.

Not billed to the customer. Managed purely for internal stock + packing.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func, true as sql_true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class AddonProduct(Base):
    """Master list of add-on items."""

    __tablename__ = "portal_addon_products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    unit: Mapped[str] = mapped_column(String(50), nullable=False, server_default="pcs")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=sql_true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


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
    """Links a catalog card to its add-on(s)."""

    __tablename__ = "portal_catalog_product_addons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    catalog_product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("portal_catalog_products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    addon_product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("portal_addon_products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    quantity_per_card: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
