from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class AddonStockLedger(Base):
    """Movement log for add-on stock — mirrors jc_stock_ledger but for AddonProduct.
    Lightweight: no receipts/bills/debit-notes, just qty in/out + why."""

    __tablename__ = "jc_addon_stock_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    addon_product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jc_addon_products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    entry_type: Mapped[str] = mapped_column(String(30), nullable=False)  # received | adjustment | customer_order | customer_order_restore
    quantity_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    reference_type: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    reference_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    party: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
