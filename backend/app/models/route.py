"""Route model — a collection of cities for collector trips."""
from __future__ import annotations
from typing import Optional

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func, true as sql_true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Route(Base):
    __tablename__ = "portal_routes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=sql_true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
