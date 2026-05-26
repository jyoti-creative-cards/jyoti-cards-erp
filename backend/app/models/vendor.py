from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func, true as sql_true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Vendor(Base):
    __tablename__ = "portal_vendors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    person_name: Mapped[str] = mapped_column(String(500), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)

    company_name: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    alias: Mapped[Optional[str]] = mapped_column(String(200), nullable=True, index=True)
    secondary_phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    billing_percentage: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
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
