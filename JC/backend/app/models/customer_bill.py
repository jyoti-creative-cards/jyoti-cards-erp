from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class CustomerBill(Base):
    __tablename__ = "jc_customer_bills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(Integer, ForeignKey("jc_customers.id", ondelete="RESTRICT"), nullable=False, index=True)
    placement_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("jc_customer_order_placements.id", ondelete="SET NULL"), nullable=True, index=True
    )
    bill_number: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    bill_series_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("jc_bill_series.id", ondelete="SET NULL"), nullable=True)
    narration: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    gst_enabled: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")
    gst_rate_percent: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, default=0, server_default="0")
    discount_percent: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2), nullable=True)
    freight_agent_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("jc_freight_agents.id", ondelete="SET NULL"), nullable=True)
    freight_charges: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    transport_mode: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    transport_receipt_number: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    # Dues post to freight agent only after pick (dispatch). Null = still pending pickup.
    freight_picked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    freight_picked_by: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    packaging_charges: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    additional_charges: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    subtotal_inclusive: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    taxable_value: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    gst_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    grand_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    totals_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    document_key: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by_type: Mapped[str] = mapped_column(String(20), nullable=False)
    created_by_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_by_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Invoice day (backdate). created_at is always the real enter-the-system clock.
    bill_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )


class CustomerBillLine(Base):
    __tablename__ = "jc_customer_bill_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bill_id: Mapped[int] = mapped_column(Integer, ForeignKey("jc_customer_bills.id", ondelete="CASCADE"), nullable=False, index=True)
    catalog_product_id: Mapped[int] = mapped_column(Integer, ForeignKey("jc_catalog_products.id", ondelete="RESTRICT"), nullable=False)
    our_product_id: Mapped[str] = mapped_column(String(120), nullable=False)
    quantity_shipped: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    discount_percent: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="billed", server_default="billed")
    close_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
