from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class CustomerBill(Base):
    """GST/discount invoice PDF for a delivered customer order (portal)."""

    __tablename__ = "portal_customer_bills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_order_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("portal_customer_orders.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    gst_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    gst_rate_percent: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False, server_default="0")
    discount_percent: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4), nullable=True)
    totals: Mapped[dict] = mapped_column(JSON, nullable=False)
    document_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    bill_no: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    bill_series_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("portal_bill_series.id", ondelete="SET NULL"), nullable=True)

    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
