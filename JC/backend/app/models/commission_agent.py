from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func, true as sql_true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class CommissionAgent(Base):
    """A person who delivers our goods and collects our money for a set of parties."""

    __tablename__ = "jc_commission_agents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True, server_default=sql_true())
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class CommissionLedgerEntry(Base):
    """Signed ledger. Positive increases what the agent owes us. Negative is money received or a credit."""

    __tablename__ = "jc_commission_ledger_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    commission_agent_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jc_commission_agents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    entry_type: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    customer_bill_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("jc_customer_bills.id", ondelete="SET NULL"), nullable=True, index=True
    )
    customer_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("jc_customers.id", ondelete="SET NULL"), nullable=True
    )
    customer_return_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    value_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    created_by_type: Mapped[str] = mapped_column(String(20), nullable=False)
    created_by_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_by_name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
