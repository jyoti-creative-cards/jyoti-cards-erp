from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class CustomerOrderLineOut(BaseModel):
    id: int
    catalog_product_id: int
    our_product_id: str
    quantity: int
    quantity_billed: int
    unit_price: str
    status: str
    cancel_reason: Optional[str] = None


class CustomerPlacementOut(BaseModel):
    id: int
    status: str
    customer_notes: Optional[str] = None
    cancel_reason: Optional[str] = None
    placed_at: datetime
    lines: List[CustomerOrderLineOut] = []


class CustomerOpenLineOut(BaseModel):
    id: int
    catalog_product_id: int
    our_product_id: str
    quantity_received: int
    quantity_open: int
    quantity_billed: int
    unit_price: str
    status: str
    cancel_reason: Optional[str] = None
    image_urls: List[str] = []


class CustomerOrderSummary(BaseModel):
    id: int
    customer_id: int
    customer_name: str
    bucket: str
    placement_count: int
    line_count: int
    total_quantity: int
    updated_at: datetime


class CustomerBillLineOut(BaseModel):
    id: int
    bill_id: int
    bill_number: str
    our_product_id: str
    quantity_shipped: int
    unit_price: str
    line_total: str
    status: str
    close_reason: Optional[str] = None


class CustomerBillOut(BaseModel):
    id: int
    bill_number: str
    grand_total: str
    narration: Optional[str] = None
    created_at: datetime
    lines: List[CustomerBillLineOut] = []


class CustomerOrderDetail(BaseModel):
    id: int
    customer_id: int
    customer_name: str
    bucket: str
    placements: List[CustomerPlacementOut] = []
    open_lines: List[CustomerOpenLineOut] = []
    bills: List[CustomerBillOut] = []


class CancelRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=2000)


class ProcessLineIn(BaseModel):
    catalog_product_id: int
    quantity_to_ship: int = Field(..., ge=0)
    discount_percent: Optional[float] = None


class AdditionalChargeIn(BaseModel):
    name: str
    amount: str


class ProcessBillIn(BaseModel):
    lines: List[ProcessLineIn]
    overall_discount_percent: Optional[float] = None
    gst_enabled: bool = False
    gst_rate_percent: float = 18
    freight_agent_id: Optional[int] = None
    freight_charges: Optional[str] = None
    packaging_charges: Optional[str] = None
    additional_charges: List[AdditionalChargeIn] = []
    bill_series_id: int
    narration: Optional[str] = None


class ProcessLineOut(BaseModel):
    open_line_id: int
    catalog_product_id: int
    our_product_id: str
    unit_price: str
    quantity_placed: int
    quantity_open: int
    quantity_billed: int
    quantity_on_hand: int
    image_urls: List[str] = []


class ProcessContextOut(BaseModel):
    customer_id: int
    customer_name: str
    lines: List[ProcessLineOut]
    default_narration: str = ""


class OfflineLineIn(BaseModel):
    catalog_product_id: int
    quantity: int = Field(..., ge=1)
    discount_percent: Optional[float] = None


class OfflineCustomerOrderIn(BaseModel):
    lines: List[OfflineLineIn] = Field(..., min_length=1)
    overall_discount_percent: Optional[float] = None
    gst_enabled: bool = False
    gst_rate_percent: float = 18
    additional_charges: List[AdditionalChargeIn] = []
    bill_series_id: int
    narration: Optional[str] = None


class CloseableItemOut(BaseModel):
    id: int
    item_type: str
    label: str
    sublabel: Optional[str] = None
    vendor_id: Optional[int] = None
    vendor_label: Optional[str] = None
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None
    quantity: Optional[int] = None
    amount: Optional[str] = None


class CloseBatchIn(BaseModel):
    placement_ids: List[int] = []
    bill_line_ids: List[int] = []
    reason: str = Field(..., min_length=1, max_length=2000)
