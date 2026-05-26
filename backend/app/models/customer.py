from __future__ import annotations

from datetime import datetime
from typing import Optional

from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, func, true as sql_true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Customer(Base):
    """Separate from any legacy `customers` table — full schema below."""

    __tablename__ = "portal_customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    company_name: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    alias: Mapped[Optional[str]] = mapped_column(String(200), nullable=True, index=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    secondary_phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    # Route / City assignment for collector trips
    city_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("portal_cities.id", ondelete="SET NULL"), nullable=True, index=True)
    route_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("portal_routes.id", ondelete="SET NULL"), nullable=True, index=True)

    # Credit management
    credit_limit: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 4), nullable=True)
    credit_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=sql_true()
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
