from __future__ import annotations

from sqlalchemy import Boolean, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class CatalogLookup(Base):
    """Generic admin-created lookup table for units, series, year_groups."""
    __tablename__ = "portal_catalog_lookups"
    __table_args__ = (
        UniqueConstraint("lookup_type", "value", name="uq_catalog_lookup_type_value"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lookup_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # unit | series | year_group
    value: Mapped[str] = mapped_column(String(120), nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
