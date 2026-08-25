from __future__ import annotations

from decimal import Decimal
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, func, true as sql_true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Vendor(Base):
    __tablename__ = "jc_vendors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    business_name: Mapped[str] = mapped_column(String(500), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    person_name: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    secondary_phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    alias: Mapped[Optional[str]] = mapped_column(String(200), nullable=True, index=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    city_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("jc_cities.id", ondelete="RESTRICT"), nullable=True, index=True)
    gst_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    billing_context: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    billing_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("100"), server_default="100")
    additional_charge: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("100"), server_default="100")
    additional_charge_label: Mapped[str] = mapped_column(String(50), nullable=False, default="Additional charge", server_default="Additional charge")
    discount_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("0"), server_default="0")
    gst_included: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=sql_true())
    gst_rate_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("18"), server_default="18")
    billing_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=sql_true())
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
