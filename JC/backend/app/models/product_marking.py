from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class ProductMarking(Base):
    """A marking on one product, shown only between starts_on and ends_on."""

    __tablename__ = "jc_product_markings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    catalog_product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jc_catalog_products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    text: Mapped[str] = mapped_column(String(200), nullable=False)
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
