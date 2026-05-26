from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class VendorBill(Base):
    """Vendor invoice + manual line entry for 3-way match vs PO and receipts."""

    __tablename__ = "portal_vendor_bills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    purchase_order_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("portal_vendor_purchase_orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    bill_lines: Mapped[list] = mapped_column(JSON, nullable=False)
    match_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="pending", index=True
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
