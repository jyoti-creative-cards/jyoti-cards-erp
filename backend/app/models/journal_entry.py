from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class JournalEntry(Base):
    __tablename__ = "portal_journal_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    memo: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    ref_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    ref_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

    lines: Mapped[list["JournalLine"]] = relationship(
        "JournalLine", back_populates="entry", cascade="all, delete-orphan"
    )


class JournalLine(Base):
    __tablename__ = "portal_journal_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    journal_entry_id: Mapped[int] = mapped_column(
        ForeignKey("portal_journal_entries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    account_code: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    debit: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, server_default="0")
    credit: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, server_default="0")

    entry: Mapped["JournalEntry"] = relationship("JournalEntry", back_populates="lines")
