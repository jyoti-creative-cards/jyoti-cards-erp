from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, func, true as sql_true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class CatalogProduct(Base):
    """Vendor catalog line items. `our_product_id` is your internal code; `id` is DB-only."""

    __tablename__ = "portal_catalog_products"
    __table_args__ = (
        UniqueConstraint("vendor_id", "vendor_product_id", name="uq_catalog_vendor_product_ext"),
        UniqueConstraint("our_product_id", name="uq_catalog_our_product_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    our_product_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    vendor_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("portal_vendors.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    vendor_product_id: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    series: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    year_group: Mapped[Optional[str]] = mapped_column(String(30), nullable=True, index=True)
    unit: Mapped[str] = mapped_column(String(50), nullable=False, server_default="pcs")

    buying_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, server_default="0")
    selling_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, server_default="0")

    image_keys: Mapped[list] = mapped_column(JSON, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=sql_true()
    )

    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
