from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class VendorCreate(BaseModel):
    company_name: str = Field(..., min_length=1, max_length=500, description="Shop / business name (required)")
    person_name: Optional[str] = Field(None, max_length=500, description="Contact person name (optional)")
    phone: str = Field(..., min_length=8, max_length=32)
    secondary_phone: Optional[str] = Field(None, max_length=32)
    address: Optional[str] = None
    city_id: Optional[int] = None
    gst_number: Optional[str] = Field(None, max_length=20)
    alias: Optional[str] = Field(None, max_length=200)


class VendorUpdate(BaseModel):
    company_name: Optional[str] = Field(None, max_length=500)
    person_name: Optional[str] = Field(None, max_length=500)
    phone: Optional[str] = Field(None, min_length=8, max_length=32)
    secondary_phone: Optional[str] = Field(None, max_length=32)
    address: Optional[str] = None
    city_id: Optional[int] = None
    gst_number: Optional[str] = Field(None, max_length=20)
    alias: Optional[str] = Field(None, max_length=200)


class VendorPublic(BaseModel):
    id: int
    company_name: Optional[str]
    person_name: str
    phone: str
    alias: Optional[str]
    secondary_phone: Optional[str]
    address: Optional[str]
    city_id: Optional[int] = None
    gst_number: Optional[str]
    deleted_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
