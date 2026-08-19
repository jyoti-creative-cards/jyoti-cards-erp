from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class VendorOrderNote(Base):
    """Threaded notes attached to a vendor order, organised by lifecycle stage.

    stage values:
        "placed"   — note added when order is placed / items added
        "procured" — note added during goods receipt / 3-way match
        "settled"  — note added when payment is recorded
    """

    __tablename__ = "portal_vendor_order_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    vendor_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("portal_vendor_orders.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    stage: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="placed", index=True,
    )  # placed | procured | settled

    body: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
