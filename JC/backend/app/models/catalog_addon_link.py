from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class CatalogAddonLink(Base):
    __tablename__ = "jc_catalog_addon_links"
    __table_args__ = (
        UniqueConstraint("catalog_product_id", "addon_product_id", name="uq_jc_catalog_addon_link"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    catalog_product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jc_catalog_products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    addon_product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jc_addon_products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
