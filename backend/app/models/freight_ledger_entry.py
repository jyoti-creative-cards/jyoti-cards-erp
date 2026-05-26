"""Freight vendor ledger entries."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import ForeignKey, Numeric, String, Text, Date
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class FreightLedgerEntry(Base):
    __tablename__ = "portal_freight_ledger"

    id: Mapped[int] = mapped_column(primary_key=True)
    freight_vendor_id: Mapped[int] = mapped_column(ForeignKey("portal_freight_vendors.id", ondelete="CASCADE"), nullable=False)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    # type: "charge" (we owe them) or "payment" (we paid them)
    entry_type: Mapped[str] = mapped_column(String(20), nullable=False, default="charge")
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    # reference to customer order / shipment
    reference: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
