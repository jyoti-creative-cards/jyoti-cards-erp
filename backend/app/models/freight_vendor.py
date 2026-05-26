"""Freight vendor — transport agents (Vishnu, Ganesh, Robin, etc.)"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from sqlalchemy import Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class FreightVendor(Base):
    __tablename__ = "portal_freight_vendors"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    balance_due: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False, server_default="0")
