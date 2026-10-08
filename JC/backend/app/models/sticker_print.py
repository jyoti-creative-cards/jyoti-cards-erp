from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class StickerPrint(Base):
    """One A5 sticker that was printed. Kept so staff can see when a party was printed."""

    __tablename__ = "jc_sticker_prints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("jc_customers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    party_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    business_name: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")
    name_hi: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")
    city_name: Mapped[str] = mapped_column(String(300), nullable=False, default="", server_default="")
    city_hi: Mapped[str] = mapped_column(String(300), nullable=False, default="", server_default="")
    phone: Mapped[str] = mapped_column(String(32), nullable=False, default="", server_default="")
    printed_by: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    printed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
