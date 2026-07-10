from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field

from app.schemas.debit_note import DebitNoteIn


class StockProductSummary(BaseModel):
    catalog_product_id: int
    our_product_id: str
    vendor_id: int
    vendor_name: str
    vendor_city: Optional[str]
    vendor_label: str
    category: Optional[str] = None
    series: Optional[str] = None
    quantity_on_hand: int
    low_stock_threshold: int = 5
    stock_status: str = "out_of_stock"
    selling_price: Optional[str]
    buying_price: str
    unit: Optional[str]
    image_urls: List[str] = []
    addon_count: int = 0
    alt_count: int = 0


class StockLedgerEntry(BaseModel):
    id: int
    entry_type: str
    quantity_delta: int
    balance_after: int
    party: Optional[str]
    notes: Optional[str]
    created_at: datetime
    reference_type: Optional[str] = None
    reference_id: Optional[int] = None


class StockProductDetail(StockProductSummary):
    vendor_product_id: str
    alternatives: List[dict] = []
    quantity_pending: int = 0
    quantity_sold: int = 0
    ledger: List[StockLedgerEntry] = []


class SellingPriceUpdate(BaseModel):
    selling_price: Optional[Decimal] = Field(None, ge=0)


class StockThresholdUpdate(BaseModel):
    low_stock_threshold: int = Field(..., ge=0)


class VendorReceiptLineIn(BaseModel):
    catalog_product_id: int
    quantity_received: int = Field(0, ge=0)
    quantity_billed: int = Field(0, ge=0)
    billed_amount: Decimal = Field(Decimal("0"), ge=0)


class VendorReceiptCreate(BaseModel):
    vendor_id: int
    lines: List[VendorReceiptLineIn] = Field(..., min_length=1)
    additional_charges: Optional[Decimal] = Field(None, ge=0)
    total_billed_amount: Optional[Decimal] = Field(None, ge=0)
    bill_number: Optional[str] = None
    bill_file_key: Optional[str] = None
    debit_notes: List[DebitNoteIn] = []


class OfflineVendorReceiptCreate(VendorReceiptCreate):
    """Direct receive + bill — skips placed pipeline."""


class PlacedLineForReceipt(BaseModel):
    catalog_product_id: int
    our_product_id: str
    quantity_ordered: int
    quantity_remaining: int
    buying_price: str
    unit: Optional[str]
    image_urls: List[str] = []


class VendorPlacedOrderForReceipt(BaseModel):
    vendor_id: int
    vendor_label: str
    order_id: Optional[int]
    lines: List[PlacedLineForReceipt] = []
