from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class InvoicePayment(Base):
    """One payment transaction against an AR or AP row (supports partials)."""

    __tablename__ = "portal_invoice_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # kind: "ar" | "ap"
    kind: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    ref_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)  # ar_invoice.id or ap_bill.id
    amount: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    payment_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    transaction_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    receipt_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    journal_entry_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("portal_journal_entries.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
