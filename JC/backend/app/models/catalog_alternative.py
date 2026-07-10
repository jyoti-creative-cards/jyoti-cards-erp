from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class CatalogAlternative(Base):
    __tablename__ = "jc_catalog_alternatives"
    __table_args__ = (
        UniqueConstraint("product_id", "alternative_product_id", name="uq_jc_catalog_alt_pair"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jc_catalog_products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    alternative_product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jc_catalog_products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
