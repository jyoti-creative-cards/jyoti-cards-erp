from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class CustomerOrderLineIn(BaseModel):
    catalog_product_id: int = Field(..., ge=1)
    quantity: int = Field(..., ge=1)
    unit_price: Optional[float] = Field(None, description="Override unit price (admin only)")


class CustomerOrderCreate(BaseModel):
    lines: List[CustomerOrderLineIn] = Field(..., min_length=1)
    customer_notes: Optional[str] = Field(None, max_length=2000)


class CustomerOrderAdminCreate(BaseModel):
    """Admin creates a manual / walk-in order on behalf of a customer."""
    customer_id: int = Field(..., ge=1)
    items: List[CustomerOrderLineIn] = Field(..., min_length=1)
    notes: Optional[str] = Field(None, max_length=4000)
    customer_notes: Optional[str] = Field(None, max_length=2000)
    invoice_date: Optional[datetime] = None
    invoice_no: Optional[str] = Field(None, max_length=100)
    receipt_note_no: Optional[str] = Field(None, max_length=100)
    force_stock: bool = False  # allow negative stock if True


class CustomerOrderLinePublic(BaseModel):
    catalog_product_id: int
    our_product_id: str = ""
    name: str = ""
    quantity: int = Field(..., ge=1)
    unit_price: str = Field(default="0")
    line_total: str = Field(default="0")


class CustomerOrderPublic(BaseModel):
    id: int
    customer_id: int
    status: str
    items: List[CustomerOrderLinePublic]
    total_amount: str
    notes: Optional[str] = None
    customer_notes: Optional[str] = None
    shipment_receipt: Optional[str] = None
    shipment_contact: Optional[str] = None
    shipment_notes: Optional[str] = None
    customer_confirmed_delivery_at: Optional[datetime] = None
    invoice_date: Optional[datetime] = None
    invoice_no: Optional[str] = None
    receipt_note_no: Optional[str] = None
    versions: Optional[List[dict]] = None
    created_at: datetime
    updated_at: datetime


class CustomerOrderAdminPublic(CustomerOrderPublic):
    customer_name: str = ""
    customer_phone: str = ""


class CustomerOrderAdminPatch(BaseModel):
    status: Optional[str] = Field(None, description="open | closed | confirmed | cancelled")
    notes: Optional[str] = Field(None, max_length=4000)
    customer_notes: Optional[str] = Field(None, max_length=2000)
    items: Optional[List[CustomerOrderLineIn]] = Field(None, description="Replace all lines when set")
    shipment_receipt: Optional[str] = Field(None, max_length=255)
    shipment_contact: Optional[str] = Field(None, max_length=128)
    shipment_notes: Optional[str] = Field(None, max_length=4000)
    invoice_date: Optional[datetime] = None
    invoice_no: Optional[str] = Field(None, max_length=100)
    receipt_note_no: Optional[str] = Field(None, max_length=100)


class OfflineOrderCreate(BaseModel):
    """Admin creates an order + immediately generates a bill in one step."""
    customer_id: int = Field(..., ge=1)
    items: List[CustomerOrderLineIn] = Field(..., min_length=1)
    customer_notes: Optional[str] = Field(None, max_length=2000)
    notes: Optional[str] = Field(None, max_length=4000)
    # Billing params
    gst_enabled: bool = False
    gst_rate_percent: float = Field(default=18.0)
    discount_percent: Optional[float] = Field(None, ge=0, le=100)
    freight_charges: Optional[float] = Field(None, ge=0)
    packaging_charges: Optional[float] = Field(None, ge=0)
    additional_charges: Optional[List[dict]] = None  # [{name: str, amount: float}]
    narration: Optional[str] = Field(None, max_length=2000)
    bill_series_id: Optional[int] = None
    rate_type: Optional[str] = None  # "order" | "net" | "regular"
    force_duplicate: bool = False  # skip duplicate check if True
    force_stock: bool = False  # allow negative stock if True
    freight_vendor_id: Optional[int] = None  # link freight charges to a freight vendor
