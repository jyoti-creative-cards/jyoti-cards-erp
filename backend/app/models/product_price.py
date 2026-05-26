"""Product price history — SCD Type 2 (start_date / end_date)."""
from __future__ import annotations
from typing import Optional

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, func, true as sql_true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class ProductPrice(Base):
    __tablename__ = "portal_product_prices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    catalog_product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("portal_catalog_products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    buying_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    selling_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)  # NULL = current price
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=sql_true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
