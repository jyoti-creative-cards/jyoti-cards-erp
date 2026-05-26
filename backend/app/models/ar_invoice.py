from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class ARInvoice(Base):
    """Accounts receivable — one row per customer bill."""

    __tablename__ = "portal_ar_invoices"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    customer_bill_id: Mapped[int] = mapped_column(
        ForeignKey("portal_customer_bills.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    customer_id: Mapped[int] = mapped_column(ForeignKey("portal_customers.id"), nullable=False, index=True)
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
