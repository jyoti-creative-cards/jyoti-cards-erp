from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class LedgerLineDetail(BaseModel):
    our_product_id: str
    quantity: Optional[int] = None
    quantity_remaining: Optional[int] = None
    quantity_received: Optional[int] = None
    quantity_billed: Optional[int] = None
    billed_amount: Optional[str] = None
    buying_price: Optional[str] = None


class EntityLedgerEntry(BaseModel):
    id: str
    event_type: str
    title: str
    summary: str
    occurred_at: datetime
    actor_name: Optional[str] = None
    actor_type: Optional[str] = None
    details: dict = {}


class EntityLedgerResponse(BaseModel):
    items: List[EntityLedgerEntry]
    total: int


class StockLedgerDetail(BaseModel):
    id: int
    entry_type: str
    quantity_delta: int
    balance_after: int
    party: Optional[str]
    notes: Optional[str]
    created_at: datetime
    reference_type: Optional[str] = None
    reference_id: Optional[int] = None
    receipt: Optional[dict] = None
