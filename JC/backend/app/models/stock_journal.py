from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class StockJournal(Base):
    """Tally-style stock voucher. Not a sale and not a purchase."""

    __tablename__ = "jc_stock_journals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    journal_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # transfer | consumption
    narration: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    expense_category: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    expense_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    created_by_name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    voided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    voided_by_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    void_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class StockJournalLine(Base):
    __tablename__ = "jc_stock_journal_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    journal_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jc_stock_journals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    catalog_product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jc_catalog_products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    our_product_id: Mapped[str] = mapped_column(String(120), nullable=False)
    quantity_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0, server_default="0")
