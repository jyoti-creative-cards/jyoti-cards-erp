from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, UniqueConstraint, func, true as sql_true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class CatalogLookup(Base):
    __tablename__ = "jc_catalog_lookups"
    __table_args__ = (UniqueConstraint("lookup_type", "value", name="uq_jc_catalog_lookup"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lookup_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    value: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=sql_true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
