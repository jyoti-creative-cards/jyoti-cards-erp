from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class WhatsAppMessage(Base):
    """One WhatsApp message on the business number, in or out."""

    __tablename__ = "jc_whatsapp_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wamid: Mapped[str] = mapped_column(String(160), nullable=False, unique=True, index=True)
    direction: Mapped[str] = mapped_column(String(8), nullable=False, index=True)  # in | out
    phone: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    contact_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    customer_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    message_type: Mapped[str] = mapped_column(String(32), nullable=False, default="text")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    wa_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
