from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class FiscalYear(Base):
    __tablename__ = "portal_fiscal_years"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)  # e.g. "2025-26"
    start_date: Mapped[date] = mapped_column(Date, nullable=False, unique=True)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_closed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AccountingPeriod(Base):
    __tablename__ = "portal_accounting_periods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fiscal_year_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("portal_fiscal_years.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(32), nullable=False)  # e.g. "Apr-2025"
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
