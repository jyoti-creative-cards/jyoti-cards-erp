from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class DebitNote(Base):
    __tablename__ = "jc_debit_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vendor_id: Mapped[int] = mapped_column(Integer, ForeignKey("jc_vendors.id", ondelete="RESTRICT"), nullable=False, index=True)
    receipt_id: Mapped[int] = mapped_column(Integer, ForeignKey("jc_stock_receipts.id", ondelete="RESTRICT"), nullable=False, index=True)
    note_type: Mapped[str] = mapped_column(String(20), nullable=False)  # item | value
    # item: short | extra ; value: over | under
    direction: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    catalog_product_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("jc_catalog_products.id", ondelete="SET NULL"), nullable=True
    )
    our_product_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    quantity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    unit_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by_type: Mapped[str] = mapped_column(String(20), nullable=False)
    created_by_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_by_name: Mapped[str] = mapped_column(String(200), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
