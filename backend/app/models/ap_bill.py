from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class APBill(Base):
    """Accounts payable — one row per vendor bill."""

    __tablename__ = "portal_ap_bills"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    vendor_bill_id: Mapped[int] = mapped_column(
        ForeignKey("portal_vendor_bills.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    vendor_id: Mapped[int] = mapped_column(ForeignKey("portal_vendors.id"), nullable=False, index=True)
    purchase_order_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, index=True
    )
    amount: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # open | paid
    journal_entry_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("portal_journal_entries.id", ondelete="SET NULL"), nullable=True, index=True
    )
    payment_transaction_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    payment_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    payment_receipt_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    payment_journal_entry_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("portal_journal_entries.id", ondelete="SET NULL"), nullable=True, index=True
    )
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
