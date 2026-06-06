from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class VendorOrder(Base):
    """One open order per vendor. Items accumulate until closed.
    Each item line records when it was ordered and when/how much was received.
    """

    __tablename__ = "portal_vendor_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vendor_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("portal_vendors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="open", index=True)
    # "open" | "closed"

    items: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # Each item:
    # {
    #   line_id: str (uuid),
    #   catalog_product_id: int,
    #   product_name: str,
    #   qty_ordered: int,
    #   qty_received: int,
    #   unit_price: float,
    #   date_ordered: str (ISO),
    #   date_received: str | null,
    #   notes: str
    # }

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Vendor bill tracking
    bill_number: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    bill_amount: Mapped[Optional[float]] = mapped_column(Numeric(14, 4), nullable=True)
    bill_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)  # uploaded bill doc
    bill_uploaded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
