from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class CatalogProductAlternative(Base):
    """Alternative/substitute catalog product B for primary product A."""

    __tablename__ = "portal_catalog_product_alternatives"
    __table_args__ = (
        UniqueConstraint(
            "catalog_product_id",
            "alternative_catalog_product_id",
            name="uq_catalog_alt_pair",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    catalog_product_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("portal_catalog_products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    alternative_catalog_product_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("portal_catalog_products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
