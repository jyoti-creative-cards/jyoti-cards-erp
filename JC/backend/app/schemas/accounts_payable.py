from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field


class ApLedgerEntryOut(BaseModel):
    id: int
    entry_type: str
    amount: str
    signed_amount: str
    running_balance: str
    description: str
    receipt_id: Optional[int] = None
    debit_note_id: Optional[int] = None
    payment_ref: Optional[str] = None
    payment_receipt_url: Optional[str] = None
    payment_comment: Optional[str] = None
    bill_number: Optional[str] = None
    bill_amount: Optional[str] = None
    debit_note_total: Optional[str] = None
    net_payable: Optional[str] = None
    created_by_name: str
    created_at: datetime
    details: dict = {}


class ApVendorSummary(BaseModel):
    vendor_id: int
    vendor_label: str
    outstanding: str
    bill_total: str
    debit_note_total: str
    payment_total: str
    transaction_count: int
    updated_at: Optional[datetime] = None


class ApVendorDetail(BaseModel):
    vendor_id: int
    vendor_label: str
    outstanding: str
    bill_total: str
    debit_note_total: str
    payment_total: str
    entries: List[ApLedgerEntryOut]
    bills: List[dict] = []
    payments: List[dict] = []


class ApSettlementIn(BaseModel):
    payment_ref: str = Field(..., min_length=1, max_length=120)
    amount: Decimal = Field(..., gt=0)
    payment_receipt_key: Optional[str] = None
    comment: Optional[str] = None
