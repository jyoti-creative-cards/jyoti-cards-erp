from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class StickerLabel(Base):
    """Hindi party name and city for the A5 sticker print only."""

    __tablename__ = "jc_sticker_labels"

    customer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jc_customers.id", ondelete="CASCADE"), primary_key=True
    )
    name_hi: Mapped[str] = mapped_column(String(500), nullable=False)
    city_hi: Mapped[str] = mapped_column(String(300), nullable=False, default="", server_default="")
    source_name: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")
    source_city: Mapped[str] = mapped_column(String(300), nullable=False, default="", server_default="")
    name_edited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
