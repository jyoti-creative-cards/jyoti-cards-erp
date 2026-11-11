"""Shared tile notes and the sticky board. Everyone signed in sees the same text."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class TileNote(Base):
    __tablename__ = "jc_tile_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tile_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True, index=True)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_by_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class StickyNote(Base):
    __tablename__ = "jc_sticky_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    author_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
