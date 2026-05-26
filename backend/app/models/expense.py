"""Expense model — indirect expenses (rent, electricity, salary, misc)."""
from __future__ import annotations
from typing import Optional

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Expense(Base):
    __tablename__ = "portal_expenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    expense_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(120), nullable=False, index=True)  # rent, salary, electricity, misc
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    payment_mode: Mapped[str] = mapped_column(String(60), nullable=False, default="cash")  # cash, bank, upi
    reference: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
