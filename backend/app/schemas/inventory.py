from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class InventoryRowPublic(BaseModel):
    catalog_product_id: int
    our_product_id: str
    name: str
    category: str
    vendor_id: int
    quantity: int = Field(..., ge=0)
    low_stock_threshold: int = Field(default=0, ge=0)
    stock_status: str = Field(
        default="out_of_stock",
        description="in_stock | low_stock | out_of_stock",
    )
    image_urls: List[str] = Field(default_factory=list)
    invoice_count: int = 0
    selling_price: float = 0.0


class LedgerEntryDetail(BaseModel):
    date: datetime
    type: str  # "inward" | "outward" | "adjustment"
    qty: int
    reference: str
    party: Optional[str] = None
    running_balance: int


class LedgerMonthSummary(BaseModel):
    year: int
    month: int
    month_label: str
    opening: int
    inward: int
    outward: int
    closing: int
    entries: List[LedgerEntryDetail]


class ProductLedgerResponse(BaseModel):
    catalog_product_id: int
    our_product_id: str
    name: str
    current_stock: int
    invoice_count: int
    months: List[LedgerMonthSummary]


class BalanceThresholdBody(BaseModel):
    low_stock_threshold: int = Field(..., ge=0)


class StockAdjustmentCreate(BaseModel):
    catalog_product_id: int = Field(..., ge=1)
    quantity_delta: int = Field(..., description="Positive adds, negative removes")
    note: Optional[str] = Field(None, max_length=2000)


class StockAdjustmentUpdate(BaseModel):
    note: Optional[str] = Field(None, max_length=2000)


class StockAdjustmentPublic(BaseModel):
    id: int
    catalog_product_id: int
    our_product_id: str = ""
    quantity_delta: int
    note: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": False}


class ManualStockBody(BaseModel):
    catalog_product_id: int = Field(..., ge=1)
    quantity: int = Field(..., ge=1)


class ReceiptLineIn(BaseModel):
    catalog_product_id: int = Field(..., ge=1)
    quantity: int = Field(..., ge=1)


class ReceiptFromPoBody(BaseModel):
    purchase_order_id: int = Field(..., ge=1)
    is_partial: bool = False
    receipt_number: Optional[str] = Field(None, max_length=120)
    lines: List[ReceiptLineIn] = Field(..., min_length=1)
    note: Optional[str] = Field(None, max_length=2000)
