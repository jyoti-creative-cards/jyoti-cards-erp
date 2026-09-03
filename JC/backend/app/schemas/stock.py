from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from app.schemas.debit_note import DebitNoteIn


class VoidIn(BaseModel):
    reason: Optional[str] = None


class StockAdjustIn(BaseModel):
    quantity_delta: int = Field(..., description="Positive to add stock, negative to remove")
    reason: str = Field(..., min_length=1, max_length=500)

    @field_validator("quantity_delta")
    @classmethod
    def _nonzero(cls, v: int) -> int:
        if v == 0:
            raise ValueError("quantity_delta must not be zero")
        return v


class StockProductSummary(BaseModel):
    catalog_product_id: int
    our_product_id: str
    vendor_product_id: Optional[str] = None
    vendor_id: int
    vendor_name: str
    vendor_city: Optional[str]
    vendor_label: str
    category: Optional[str] = None
    series: Optional[str] = None
    year_group: Optional[str] = None
    quantity_on_hand: int
    low_stock_threshold: int = 5
    stock_status: str = "out_of_stock"
    selling_price: Optional[str]
    buying_price: Optional[str] = None
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
    alternatives: List[dict] = []
    quantity_pending: int = 0
    quantity_sold: int = 0
    ledger: List[StockLedgerEntry] = []


class SellingPriceUpdate(BaseModel):
    selling_price: Optional[Decimal] = Field(None, ge=0)


class BulkSellingPriceItem(BaseModel):
    catalog_product_id: int
    selling_price: Decimal = Field(..., ge=0)


class BulkSellingPriceIn(BaseModel):
    items: List[BulkSellingPriceItem] = Field(..., min_length=1)


class StockThresholdUpdate(BaseModel):
    low_stock_threshold: int = Field(..., ge=0)


class VendorReceiptLineIn(BaseModel):
    catalog_product_id: int
    quantity_received: int = Field(0, ge=0)
    quantity_billed: int = Field(0, ge=0)
    # Raw (pre-billing_pct) line value the vendor's paper bill states — qty x their rate.
    # None = not overridden, fall back to quantity_billed x our catalog buying_price.
    billed_amount: Optional[Decimal] = Field(None, ge=0)


class VendorReceiptCreate(BaseModel):
    vendor_id: int
    lines: List[VendorReceiptLineIn] = Field(..., min_length=1)
    additional_charges: Optional[Decimal] = Field(None, ge=0)
    total_billed_amount: Optional[Decimal] = Field(None, ge=0)
    actual_ap_amount: Optional[Decimal] = Field(None, ge=0)  # actual payable when split-pricing differs from bill
    bill_number: Optional[str] = None
    order_receipt_number: Optional[str] = None
    bill_file_key: Optional[str] = None
    notes: Optional[str] = None
    debit_notes: List[DebitNoteIn] = []
    bill_date: Optional[date] = None  # vendor bill backdate
    received_on: Optional[date] = None  # receive backdate (goods in)


class VendorBillLineIn(BaseModel):
    catalog_product_id: int
    quantity_billed: Optional[int] = Field(None, ge=0)
    # Raw (pre-billing_pct) line value the vendor's paper bill states — qty x their rate.
    # None = not overridden, fall back to quantity_billed x our catalog buying_price.
    billed_amount: Optional[Decimal] = Field(None, ge=0)


class VendorBillIn(BaseModel):
    total_billed_amount: Decimal = Field(..., ge=0)
    lines: List[VendorBillLineIn] = []
    bill_number: Optional[str] = None
    bill_file_key: Optional[str] = None
    bill_date: Optional[date] = None  # vendor's paper invoice date; default = today
    notes: Optional[str] = None
    debit_notes: List[DebitNoteIn] = []


class VendorReceiveCreate(BaseModel):
    """Goods-only receive (placed order or offline). Bill later from Received."""
    vendor_id: int
    lines: List[VendorReceiptLineIn] = Field(..., min_length=1)
    order_receipt_number: str = Field(..., min_length=1, max_length=120)
    bill_file_key: Optional[str] = None
    notes: Optional[str] = None
    received_on: Optional[date] = None  # backdate; default = today


class OfflineVendorReceiptCreate(VendorReceiveCreate):
    """Offline receive only — no placed order; bill later from Received."""


class PlacedLineForReceipt(BaseModel):
    catalog_product_id: int
    our_product_id: str
    vendor_product_id: Optional[str] = None
    category: Optional[str] = None
    quantity_ordered: int
    quantity_remaining: int
    buying_price: Optional[str] = None
    unit: Optional[str]
    image_urls: List[str] = []


class VendorPlacedOrderForReceipt(BaseModel):
    vendor_id: int
    vendor_label: str
    order_id: Optional[int]
    lines: List[PlacedLineForReceipt] = []


class PendingBillReceipt(BaseModel):
    receipt_id: int
    order_receipt_number: Optional[str] = None
    received_at: datetime
    expected_bill_amount: Optional[str] = None
    expected_extra_cash: Optional[str] = None
    line_count: int
    total_quantity: int


class VendorPendingBillList(BaseModel):
    vendor_id: int
    vendor_label: str
    receipts: List[PendingBillReceipt] = []


class ReceiptLineForBill(BaseModel):
    catalog_product_id: int
    our_product_id: str
    vendor_product_id: Optional[str] = None
    quantity_received: int
    buying_price: str
    unit: Optional[str] = None
    image_urls: List[str] = []


class ReceiptForBillDetail(BaseModel):
    receipt_id: int
    vendor_id: int
    vendor_label: str
    order_receipt_number: Optional[str] = None
    expected_bill_amount: Optional[str] = None
    expected_extra_cash: Optional[str] = None
    billing_terms: dict
    lines: List[ReceiptLineForBill] = []


class BillPreviewIn(BaseModel):
    total_billed_amount: Decimal = Field(..., ge=0)
    lines: List[VendorBillLineIn] = []


class BillPreviewOut(BaseModel):
    expected_bill_total: str
    expected_extra_cash: Optional[str] = None
    suggested_debit_notes: List[dict] = []
