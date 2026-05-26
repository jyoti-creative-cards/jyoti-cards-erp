from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class StockReceipt(Base):
    """Goods receipt against a PO (partial or full). Manual stock does not use this table."""

    __tablename__ = "portal_stock_receipts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    purchase_order_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("portal_vendor_purchase_orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    receipt_number: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    contact_number: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    receipt_image_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    is_partial: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    line_items: Mapped[list] = mapped_column(JSON, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
