"""City model — belongs to a route."""
from __future__ import annotations
from typing import Optional

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func, true as sql_true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class City(Base):
    __tablename__ = "portal_cities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    route_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("portal_routes.id", ondelete="SET NULL"), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=sql_true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
