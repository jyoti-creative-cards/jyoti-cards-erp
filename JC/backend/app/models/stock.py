from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class StockBalance(Base):
    __tablename__ = "jc_stock_balances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    catalog_product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jc_catalog_products.id", ondelete="RESTRICT"), nullable=False, unique=True, index=True
    )
    quantity_on_hand: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    low_stock_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=5, server_default="5")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class StockReceipt(Base):
    __tablename__ = "jc_stock_receipts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    receipt_type: Mapped[str] = mapped_column(String(30), nullable=False, default="vendor_order")
    vendor_id: Mapped[int] = mapped_column(Integer, ForeignKey("jc_vendors.id", ondelete="RESTRICT"), nullable=False, index=True)
    placed_order_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("jc_vendor_orders.id", ondelete="SET NULL"), nullable=True)
    billed_placement_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("jc_vendor_order_placements.id", ondelete="SET NULL"), nullable=True
    )
    additional_charges: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    total_billed_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    bill_number: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    bill_file_key: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    receipt_document_key: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    received_by_type: Mapped[str] = mapped_column(String(20), nullable=False)
    received_by_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    received_by_name: Mapped[str] = mapped_column(String(200), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class StockReceiptLine(Base):
    __tablename__ = "jc_stock_receipt_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    receipt_id: Mapped[int] = mapped_column(Integer, ForeignKey("jc_stock_receipts.id", ondelete="CASCADE"), nullable=False, index=True)
    catalog_product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jc_catalog_products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    our_product_id: Mapped[str] = mapped_column(String(120), nullable=False)
    quantity_received: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quantity_billed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    billed_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    buying_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)


class StockLedger(Base):
    __tablename__ = "jc_stock_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    catalog_product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jc_catalog_products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    entry_type: Mapped[str] = mapped_column(String(30), nullable=False)
    quantity_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    reference_type: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    reference_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    party: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
