from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class VendorOrder(Base):
    """One order per vendor. Items are stored in ``portal_vendor_order_lines``
    (normalized rows, not JSONB). Notes are stored in ``portal_vendor_order_notes``
    keyed by lifecycle stage.
    """

    __tablename__ = "portal_vendor_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vendor_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("portal_vendors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="placed", index=True
    )
    # "placed" | "procured" | "closed"

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships — loaded with a single IN-clause query per session (no N+1)
    lines: Mapped[list] = relationship(
        "VendorOrderLine",
        foreign_keys="[VendorOrderLine.vendor_order_id]",
        order_by="VendorOrderLine.id",
        lazy="selectin",
        cascade="all, delete-orphan",
        uselist=True,
    )
    order_notes: Mapped[list] = relationship(
        "VendorOrderNote",
        foreign_keys="[VendorOrderNote.vendor_order_id]",
        order_by="VendorOrderNote.created_at",
        lazy="selectin",
        cascade="all, delete-orphan",
        uselist=True,
    )
