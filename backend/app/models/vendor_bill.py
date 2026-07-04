from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class VendorBill(Base):
    """Vendor invoice linked to a vendor order batch receive + 3-way match data."""

    __tablename__ = "portal_vendor_bills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vendor_order_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("portal_vendor_orders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    vendor_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("portal_vendors.id", ondelete="SET NULL"), nullable=True, index=True
    )
    bill_number: Mapped[Optional[str]] = mapped_column(String(200), nullable=True, index=True)
    bill_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 4), nullable=True)
    # legacy field kept for any old PO references
    purchase_order_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    document_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    bill_lines: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    match_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="matched", index=True
    )
    match_result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
