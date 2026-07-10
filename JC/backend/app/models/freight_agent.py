from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class FreightAgent(Base):
    __tablename__ = "jc_freight_agents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    balance_due: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class FreightLedgerEntry(Base):
    __tablename__ = "jc_freight_ledger_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    freight_agent_id: Mapped[int] = mapped_column(Integer, ForeignKey("jc_freight_agents.id", ondelete="CASCADE"), nullable=False, index=True)
    entry_type: Mapped[str] = mapped_column(String(20), nullable=False)  # charge | settlement
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    customer_bill_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("jc_customer_bills.id", ondelete="SET NULL"), nullable=True)
    expense_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("jc_expenses.id", ondelete="SET NULL"), nullable=True)
    transaction_ref: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by_name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
