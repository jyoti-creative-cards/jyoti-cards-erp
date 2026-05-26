from __future__ import annotations

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class CatalogCategoryLabel(Base):
    """Categories you add before any product uses them; merged with distinct product categories in GET /catalog/categories."""

    __tablename__ = "portal_catalog_category_labels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
