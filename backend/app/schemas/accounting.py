from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class ChartAccountPublic(BaseModel):
    code: str
    name: str
    kind: str


class JournalLinePublic(BaseModel):
    account_code: str
    debit: str
    credit: str


class JournalEntryPublic(BaseModel):
    id: int
    posted_at: datetime
    memo: str
    ref_type: str
    ref_id: Optional[int] = None
    lines: list[JournalLinePublic]


class ARInvoicePublic(BaseModel):
    id: int
    customer_bill_id: int
    customer_id: int
    amount: str
    amount_paid: str = "0"
    balance: str = "0"
    status: str
    journal_entry_id: Optional[int] = None
    payment_transaction_id: Optional[str] = None
    payment_date: Optional[date] = None
    payment_receipt_key: Optional[str] = None
    payment_receipt_url: Optional[str] = None
    payment_journal_entry_id: Optional[int] = None
    paid_at: Optional[datetime] = None
    created_at: datetime


class APBillPublic(BaseModel):
    id: int
    vendor_bill_id: int
    vendor_id: int
    purchase_order_id: int
    amount: str
    amount_paid: str = "0"
    balance: str = "0"
    status: str
    journal_entry_id: Optional[int] = None
    payment_transaction_id: Optional[str] = None
    payment_date: Optional[date] = None
    payment_receipt_key: Optional[str] = None
    payment_receipt_url: Optional[str] = None
    payment_journal_entry_id: Optional[int] = None
    paid_at: Optional[datetime] = None
    created_at: datetime


class GLAccountRowPublic(BaseModel):
    account_code: str
    name: str
    kind: str
    debit_total: str
    credit_total: str


class PnLReportPublic(BaseModel):
    date_from: date
    date_to: date
    revenue_total: str
    expense_total: str
    net_pnl: str


class DashboardPublic(BaseModel):
    date_from: date
    date_to: date
    revenue_total: str
    expense_total: str
    net_pnl: str
    open_ar_count: int
    open_ap_count: int
    monthly_pnl: list[dict[str, Any]] = Field(default_factory=list)


class VendorAPSummaryPublic(BaseModel):
    vendor_id: int
    vendor_name: str
    total_billed: str
    total_paid: str
    balance: str
    bills: list[APBillPublic]


class CustomerARSummaryPublic(BaseModel):
    customer_id: int
    customer_name: str
    total_billed: str
    total_paid: str
    balance: str
    invoices: list[ARInvoicePublic]

