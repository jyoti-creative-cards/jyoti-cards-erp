from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class CreditNote(Base):
    """Customer returns / credit — reduces AR."""

    __tablename__ = "portal_credit_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("portal_customer_orders.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    customer_bill_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("portal_customer_bills.id", ondelete="SET NULL"), nullable=True, index=True
    )
    customer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("portal_customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    amount: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    document_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="open")  # open | applied
    journal_entry_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("portal_journal_entries.id", ondelete="SET NULL"), nullable=True
    )
    note_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    # Return details
    return_items: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)  # [{catalog_product_id, name, qty, unit_price, line_amount}]
    is_full_return: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    refund_method: Mapped[str] = mapped_column(String(20), nullable=False, server_default="credit")  # "credit" | "payout"
    paid_out_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_to_bill_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("portal_customer_bills.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class DebitNote(Base):
    """Vendor overcharge / return — reduces AP."""

    __tablename__ = "portal_debit_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    purchase_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("portal_vendor_purchase_orders.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    vendor_bill_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("portal_vendor_bills.id", ondelete="SET NULL"), nullable=True, index=True
    )
    vendor_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("portal_vendors.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    amount: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    document_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="open")
    journal_entry_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("portal_journal_entries.id", ondelete="SET NULL"), nullable=True
    )
    note_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
