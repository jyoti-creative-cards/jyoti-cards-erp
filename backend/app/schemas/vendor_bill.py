from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, Field


class VendorBillLineIn(BaseModel):
    bill_item_ref: str = Field("", max_length=255)
    catalog_product_id: int = Field(..., ge=1)
    quantity: int = Field(..., ge=1)
    unit_price: str = Field(..., description="Decimal as string")


class VendorBillCreate(BaseModel):
    bill_lines: List[VendorBillLineIn] = Field(..., min_length=1)
    notes: Optional[str] = Field(None, max_length=4000)


class VendorBillPatch(BaseModel):
    bill_lines: Optional[List[VendorBillLineIn]] = None
    notes: Optional[str] = Field(None, max_length=4000)


class VendorBillPublic(BaseModel):
    id: int
    document_key: Optional[str] = None
    document_url: Optional[str] = None
    bill_lines: List[dict[str, Any]] = Field(default_factory=list)
    match_status: str
    match_result: Optional[dict[str, Any]] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime
