from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class VendorApAccount(Base):
    """One running AP account per vendor."""

    __tablename__ = "jc_vendor_ap_accounts"
    __table_args__ = (Index("ix_jc_vendor_ap_vendor_open", "vendor_id", "is_open"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vendor_id: Mapped[int] = mapped_column(Integer, ForeignKey("jc_vendors.id", ondelete="RESTRICT"), nullable=False, unique=True, index=True)
    is_open: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ApLedgerEntry(Base):
    """AP transactions: bill (+), debit note (-), payment (-)."""

    __tablename__ = "jc_ap_ledger_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vendor_id: Mapped[int] = mapped_column(Integer, ForeignKey("jc_vendors.id", ondelete="RESTRICT"), nullable=False, index=True)
    entry_type: Mapped[str] = mapped_column(String(20), nullable=False)  # bill | debit_note | payment
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    receipt_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("jc_stock_receipts.id", ondelete="SET NULL"), nullable=True, index=True)
    debit_note_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("jc_debit_notes.id", ondelete="SET NULL"), nullable=True)
    payment_ref: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    payment_receipt_key: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    payment_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    created_by_type: Mapped[str] = mapped_column(String(20), nullable=False)
    created_by_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_by_name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
