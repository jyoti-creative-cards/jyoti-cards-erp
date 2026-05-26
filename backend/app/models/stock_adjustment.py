from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class StockAdjustment(Base):
    """Manual quantity correction (delta applied to portal_stock_balances)."""

    __tablename__ = "portal_stock_adjustments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    catalog_product_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("portal_catalog_products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    quantity_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
