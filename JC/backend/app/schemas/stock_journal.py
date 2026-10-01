from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field


class JournalLineIn(BaseModel):
    catalog_product_id: int
    quantity: int = Field(..., gt=0)
    rate: Optional[Decimal] = None


class JournalIn(BaseModel):
    journal_date: date
    kind: Literal["transfer", "consumption"]
    narration: Optional[str] = None
    expense_category: Optional[str] = None
    from_product_id: Optional[int] = None
    to_product_id: Optional[int] = None
    quantity: Optional[int] = Field(None, gt=0)
    album: Optional[str] = None
    copies: Optional[int] = Field(None, gt=0)
    lines: Optional[list[JournalLineIn]] = None


class JournalVoidIn(BaseModel):
    reason: str = Field(..., min_length=1)


class JournalLineOut(BaseModel):
    catalog_product_id: int
    our_product_id: str
    quantity_delta: int
    rate: str
    amount: str
    on_hand: int


class JournalOut(BaseModel):
    id: int
    journal_date: date
    kind: str
    narration: Optional[str] = None
    expense_category: Optional[str] = None
    expense_id: Optional[int] = None
    total_cost: str
    created_by_name: Optional[str] = None
    voided_at: Optional[datetime] = None
    void_reason: Optional[str] = None
    lines: list[JournalLineOut] = []
    warnings: list[str] = []
