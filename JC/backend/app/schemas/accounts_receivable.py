from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field


class ArLedgerEntryOut(BaseModel):
    id: int
    entry_type: str
    amount: str
    signed_amount: str
    running_balance: str
    description: str
    bill_id: Optional[int] = None
    payment_ref: Optional[str] = None
    payment_comment: Optional[str] = None
    created_by_name: str
    created_at: datetime


class ArCustomerSummary(BaseModel):
    customer_id: int
    customer_label: str
    outstanding: str
    bill_total: str
    payment_total: str
    transaction_count: int


class ArCustomerDetail(BaseModel):
    customer_id: int
    customer_label: str
    outstanding: str
    bill_total: str
    payment_total: str
    entries: List[ArLedgerEntryOut]


class ArSettlementIn(BaseModel):
    payment_ref: str = Field(..., min_length=1, max_length=120)
    amount: Decimal = Field(..., gt=0)
    comment: Optional[str] = None
