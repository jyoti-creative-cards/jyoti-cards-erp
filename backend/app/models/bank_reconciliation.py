from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func, true as sql_true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class BankAccount(Base):
    __tablename__ = "portal_bank_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    account_number: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    bank_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    ifsc: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=sql_true()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class BankReconciliation(Base):
    __tablename__ = "portal_bank_reconciliations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bank_account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("portal_bank_accounts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    opening_balance: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, server_default="0")
    closing_balance_bank: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, server_default="0")
    closing_balance_books: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, server_default="0")
    difference: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, server_default="0")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    statement_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)  # S3 key for uploaded statement
    is_finalised: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
