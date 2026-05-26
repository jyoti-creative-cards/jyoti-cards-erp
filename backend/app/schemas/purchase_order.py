from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class PurchaseOrderLineIn(BaseModel):
    catalog_product_id: int = Field(..., ge=1)
    quantity: int = Field(..., ge=1)


class PurchaseOrderLinePublic(BaseModel):
    catalog_product_id: int
    quantity: int
    received_quantity: int = Field(default=0, ge=0, description="Cumulative quantity received into stock")
    quantity_pending: int = Field(default=0, ge=0, description="quantity − received_quantity")
    name: str = ""
    our_product_id: str = ""
    vendor_product_id: str = ""
    buying_price: float = Field(default=0.0, description="Snapshot unit buying price at PO time")
    selling_price: float = Field(default=0.0, description="Snapshot unit selling price at PO time")
    line_total_buying: float = Field(default=0.0, description="quantity × buying_price")


class PurchaseOrderReceiptLinePublic(BaseModel):
    catalog_product_id: int
    quantity: int
    name: str = ""


class PurchaseOrderReceiptPublic(BaseModel):
    id: int
    receipt_number: Optional[str] = None
    contact_number: Optional[str] = None
    is_partial: bool = False
    receipt_image_url: Optional[str] = None
    lines: List[PurchaseOrderReceiptLinePublic] = Field(default_factory=list)
    created_at: datetime
    notes: Optional[str] = None


class PurchaseOrderCreate(BaseModel):
    vendor_id: int = Field(..., ge=1)
    items: List[PurchaseOrderLineIn] = Field(..., min_length=1)


class PurchaseOrderUpdate(BaseModel):
    items: Optional[List[PurchaseOrderLineIn]] = None
    status: Optional[str] = Field(None, min_length=1, max_length=40)
    notes: Optional[str] = None


class PurchaseOrderPublic(BaseModel):
    id: int
    vendor_id: int
    status: str
    items: List[PurchaseOrderLinePublic]
    receipts: List[PurchaseOrderReceiptPublic] = Field(default_factory=list)
    notes: Optional[str] = None
    total_buying_value: float = Field(default=0.0, description="Sum of line_total_buying")
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": False}
