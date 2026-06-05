from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


PERMISSIONS = [
    "people.view", "people.edit",
    "catalog.view", "catalog.edit",
    "stock.view", "stock.edit",
    "orders.view", "orders.edit",
    "finance.view",
    "returns.view", "returns.edit",
    "admin.manage",   # manage staff accounts
    "admin.setup",    # routes, cities, categories, bill series, etc.
    "admin.audit",    # view audit log
    "recyclebin.view",
    "create.use",
]


class StaffUser(Base):
    """Admin-managed employee accounts with granular permissions."""

    __tablename__ = "portal_staff_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    username: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, server_default="staff")  # "admin" | "staff"
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    permissions: Mapped[list] = mapped_column(JSON, nullable=False, server_default="[]")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
