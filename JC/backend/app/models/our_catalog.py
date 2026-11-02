from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class OurCatalog(Base):
    """A physical catalogue we make from stock items and send to parties."""

    __tablename__ = "jc_our_catalogs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    copies_made: Mapped[int] = mapped_column(Integer, nullable=False)
    expense_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    stock_journal_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OurCatalogLine(Base):
    __tablename__ = "jc_our_catalog_lines"
    __table_args__ = (UniqueConstraint("catalog_id", "catalog_product_id", name="uq_our_catalog_line"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    catalog_id: Mapped[int] = mapped_column(Integer, ForeignKey("jc_our_catalogs.id", ondelete="CASCADE"), nullable=False, index=True)
    catalog_product_id: Mapped[int] = mapped_column(Integer, ForeignKey("jc_catalog_products.id", ondelete="RESTRICT"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)


class OurCatalogAssignment(Base):
    """This catalogue should go to this party."""

    __tablename__ = "jc_our_catalog_assignments"
    __table_args__ = (UniqueConstraint("catalog_id", "customer_id", name="uq_our_catalog_assignment"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    catalog_id: Mapped[int] = mapped_column(Integer, ForeignKey("jc_our_catalogs.id", ondelete="CASCADE"), nullable=False, index=True)
    customer_id: Mapped[int] = mapped_column(Integer, ForeignKey("jc_customers.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OurCatalogIssue(Base):
    """Copies this party has actually received."""

    __tablename__ = "jc_our_catalog_issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    catalog_id: Mapped[int] = mapped_column(Integer, ForeignKey("jc_our_catalogs.id", ondelete="CASCADE"), nullable=False, index=True)
    customer_id: Mapped[int] = mapped_column(Integer, ForeignKey("jc_customers.id", ondelete="CASCADE"), nullable=False, index=True)
    copies: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal("0"))
    bill_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("jc_customer_bills.id", ondelete="SET NULL"), nullable=True, index=True)
    issued_on: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
