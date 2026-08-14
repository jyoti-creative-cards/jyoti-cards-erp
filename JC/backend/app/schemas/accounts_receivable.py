from __future__ import annotations

from datetime import date, datetime
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
    return_id: Optional[int] = None
    payment_ref: Optional[str] = None
    payment_mode: Optional[str] = None
    payment_comment: Optional[str] = None
    value_date: Optional[str] = None
    reverses_entry_id: Optional[int] = None
    created_by_name: str
    created_at: datetime


class ArCustomerSummary(BaseModel):
    customer_id: int
    customer_label: str
    business_name: str = ""
    person_name: Optional[str] = None
    alias: Optional[str] = None
    phone: Optional[str] = None
    city_name: Optional[str] = None
    outstanding: str
    opening_total: str = "0.00"
    opening_as_on: Optional[str] = None
    bill_total: str
    payment_total: str
    credit_total: str = "0.00"
    transaction_count: int


class ArCustomerDetail(BaseModel):
    customer_id: int
    customer_label: str
    outstanding: str
    opening_total: str = "0.00"
    opening_as_on: Optional[str] = None
    bill_total: str
    payment_total: str
    credit_total: str = "0.00"
    credit_limit: Optional[str] = None
    credit_left: Optional[str] = None
    credit_override: bool = False
    credit_unlimited: bool = True
    entries: List[ArLedgerEntryOut]


class ArSettlementIn(BaseModel):
    payment_ref: Optional[str] = Field(None, max_length=120)
    payment_mode_id: Optional[int] = None
    amount: Decimal = Field(..., gt=0)
    comment: Optional[str] = None


class OpeningBalanceIn(BaseModel):
    amount: Decimal = Field(..., ge=0)
    as_on: date
