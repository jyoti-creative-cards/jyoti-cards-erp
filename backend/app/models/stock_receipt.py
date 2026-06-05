from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class StockReceipt(Base):
    """Goods receipt — either against a PO or directly from a vendor."""

    __tablename__ = "portal_stock_receipts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    purchase_order_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("portal_vendor_purchase_orders.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    vendor_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("portal_vendors.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    receipt_number: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    contact_number: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    receipt_image_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    is_partial: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    line_items: Mapped[list] = mapped_column(JSON, nullable=False)
    extra_charges: Mapped[Optional[float]] = mapped_column(Numeric(14, 4), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    vendor_bill_no: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    bill_photo_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    image_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
