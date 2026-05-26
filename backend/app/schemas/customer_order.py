from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class CustomerOrderLineIn(BaseModel):
    catalog_product_id: int = Field(..., ge=1)
    quantity: int = Field(..., ge=1)


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
    created_at: datetime
    updated_at: datetime


class CustomerOrderAdminPublic(CustomerOrderPublic):
    customer_name: str = ""
    customer_phone: str = ""


class CustomerOrderAdminPatch(BaseModel):
    status: Optional[str] = Field(None, description="confirmed | shipped | cancelled")
    notes: Optional[str] = Field(None, max_length=4000)
    customer_notes: Optional[str] = Field(None, max_length=2000)
    items: Optional[List[CustomerOrderLineIn]] = Field(None, description="Replace all lines when set")
    shipment_receipt: Optional[str] = Field(None, max_length=255)
    shipment_contact: Optional[str] = Field(None, max_length=128)
    shipment_notes: Optional[str] = Field(None, max_length=4000)
    invoice_date: Optional[datetime] = None
    invoice_no: Optional[str] = Field(None, max_length=100)
    receipt_note_no: Optional[str] = Field(None, max_length=100)
