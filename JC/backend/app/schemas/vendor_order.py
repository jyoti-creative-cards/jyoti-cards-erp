from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class VendorOrderLineIn(BaseModel):
    catalog_product_id: int
    quantity: int = Field(..., ge=1)


class PlacementCreate(BaseModel):
    vendor_id: int
    lines: List[VendorOrderLineIn] = Field(..., min_length=1)


class AlternativeBrief(BaseModel):
    catalog_product_id: int
    our_product_id: str
    buying_price: str


class CatalogProductForOrder(BaseModel):
    id: int
    our_product_id: str
    vendor_product_id: str
    buying_price: str
    unit: Optional[str]
    image_urls: List[str] = []
    alternatives: List[AlternativeBrief] = []


class PlacementLineDetail(BaseModel):
    line_id: int
    placement_id: int
    catalog_product_id: int
    our_product_id: str
    quantity: int
    quantity_billed: Optional[int] = None
    billed_amount: Optional[str] = None
    buying_price: str
    placed_at: datetime
    placed_by_name: str
    placed_by_type: str
    placement_color_index: int


class AggregatedLine(BaseModel):
    catalog_product_id: int
    our_product_id: str
    total_quantity: int
    total_placed: int = 0
    total_received: int = 0
    total_pending: int = 0
    buying_price: str
    unit: Optional[str]
    image_urls: List[str] = []
    breakdown: List[PlacementLineDetail] = []


class PlacementSummary(BaseModel):
    id: int
    status: str
    placed_at: datetime
    placed_by_name: str
    placed_by_type: str
    color_index: int
    line_count: int
    total_quantity: int = 0
    receipt_id: Optional[int] = None
    bill_number: Optional[str] = None
    bill_file_url: Optional[str] = None
    closed_at: Optional[datetime] = None
    cancel_reason: Optional[str] = None
    close_reason: Optional[str] = None
    bill_amount: Optional[str] = None
    debit_note_total: Optional[str] = None
    net_payable: Optional[str] = None


class VendorOrderSummary(BaseModel):
    id: int
    vendor_id: int
    vendor_name: str
    vendor_city: Optional[str]
    vendor_label: str
    status: str
    bucket: str
    is_open: bool
    placement_count: int
    line_count: int
    total_quantity: int
    updated_at: datetime


class VendorOrderDetail(BaseModel):
    id: int
    vendor_id: int
    vendor_name: str
    vendor_city: Optional[str]
    vendor_label: str
    status: str
    bucket: str
    is_open: bool
    created_at: datetime
    updated_at: datetime
    placements: List[PlacementSummary]
    aggregated_lines: List[AggregatedLine]


class OrderSummaryLine(BaseModel):
    catalog_product_id: int
    our_product_id: str
    total_placed: int
    total_received: int
    total_pending: int
    total_cancelled: int
    total_closed: int = 0
    buying_price: str
    unit: Optional[str]
    image_urls: List[str] = []
    open_line_id: Optional[int] = None


class OrderSummaryEvent(BaseModel):
    event_type: str
    quantity: int
    quantity_billed: Optional[int] = None
    billed_amount: Optional[str] = None
    occurred_at: datetime
    actor_name: Optional[str] = None
    bill_number: Optional[str] = None
    placement_index: Optional[int] = None


class OrderSummaryDrillDown(BaseModel):
    vendor_id: int
    vendor_label: str
    catalog_product_id: int
    our_product_id: str
    events: List[OrderSummaryEvent]


class VendorOrderSummaryDetail(BaseModel):
    vendor_id: int
    vendor_label: str
    lines: List[OrderSummaryLine]


class VendorOrderLineUpdate(BaseModel):
    catalog_product_id: Optional[int] = None
    quantity: Optional[int] = Field(None, ge=1)


class OpenLineUpdate(BaseModel):
    catalog_product_id: Optional[int] = None
    quantity: Optional[int] = Field(None, ge=1)


class OpenLineOut(BaseModel):
    id: int
    catalog_product_id: int
    our_product_id: str
    quantity: int
    buying_price: str
    unit: Optional[str] = None
    image_urls: List[str] = []
    status: str


class OpenVendorDetail(BaseModel):
    vendor_id: int
    vendor_label: str
    lines: List[OpenLineOut]


class ClosedLineOut(BaseModel):
    id: int
    catalog_product_id: int
    our_product_id: str
    quantity: int
    buying_price: str
    source: str  # open | billed
    closed_at: Optional[datetime] = None
    bill_number: Optional[str] = None
    close_reason: Optional[str] = None
    placement_id: Optional[int] = None


class CloseableVendorItemOut(BaseModel):
    id: int
    item_type: str = "placement"
    vendor_id: int
    vendor_label: str
    bill_number: Optional[str] = None
    line_count: int = 0
    total_qty: int = 0
    placed_at: Optional[datetime] = None


class CloseBatchIn(BaseModel):
    placement_ids: List[int] = Field(..., min_length=1)
    reason: str = Field(..., min_length=1, max_length=2000)


class ReasonIn(BaseModel):
    reason: str = Field(..., min_length=1, max_length=2000)
