from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class VendorOpenLine(Base):
    """Operational open-order line per vendor+product (daily pending tracker)."""

    __tablename__ = "jc_vendor_open_lines"
    __table_args__ = (UniqueConstraint("vendor_id", "catalog_product_id", name="uq_jc_vendor_open_line"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vendor_id: Mapped[int] = mapped_column(Integer, ForeignKey("jc_vendors.id", ondelete="CASCADE"), nullable=False, index=True)
    catalog_product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jc_catalog_products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    our_product_id: Mapped[str] = mapped_column(String(120), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    buying_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", server_default="open", index=True)
    cancel_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    close_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
