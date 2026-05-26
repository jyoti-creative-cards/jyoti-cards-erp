from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class StockBalance(Base):
    """On-hand quantity per catalog product (aggregated)."""

    __tablename__ = "portal_stock_balances"

    catalog_product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("portal_catalog_products.id", ondelete="CASCADE"), primary_key=True
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    low_stock_threshold: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
