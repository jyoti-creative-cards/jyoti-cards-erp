from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, func, true as sql_true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class CatalogProduct(Base):
    __tablename__ = "jc_catalog_products"
    __table_args__ = (UniqueConstraint("our_product_id", name="uq_jc_catalog_our_product_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    our_product_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    vendor_id: Mapped[int] = mapped_column(Integer, ForeignKey("jc_vendors.id", ondelete="RESTRICT"), nullable=False, index=True)
    vendor_product_id: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    series: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    unit: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    year_group: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    buying_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    selling_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    image_keys: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=sql_true())
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
