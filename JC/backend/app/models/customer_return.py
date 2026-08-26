from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class CustomerReturn(Base):
    """One customer return — may span multiple bills. Creates AR credit note."""

    __tablename__ = "jc_customer_returns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(Integer, ForeignKey("jc_customers.id", ondelete="RESTRICT"), nullable=False, index=True)
    return_number: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    calculated_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    credit_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    document_key: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    deleted_by_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    created_by_type: Mapped[str] = mapped_column(String(20), nullable=False)
    created_by_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_by_name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CustomerReturnLine(Base):
    __tablename__ = "jc_customer_return_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    return_id: Mapped[int] = mapped_column(Integer, ForeignKey("jc_customer_returns.id", ondelete="CASCADE"), nullable=False, index=True)
    bill_id: Mapped[int] = mapped_column(Integer, ForeignKey("jc_customer_bills.id", ondelete="RESTRICT"), nullable=False, index=True)
    bill_line_id: Mapped[int] = mapped_column(Integer, ForeignKey("jc_customer_bill_lines.id", ondelete="RESTRICT"), nullable=False, index=True)
    catalog_product_id: Mapped[int] = mapped_column(Integer, ForeignKey("jc_catalog_products.id", ondelete="RESTRICT"), nullable=False)
    our_product_id: Mapped[str] = mapped_column(String(120), nullable=False)
    quantity_returned: Mapped[int] = mapped_column(Integer, nullable=False)
    sold_unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    line_calculated: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
