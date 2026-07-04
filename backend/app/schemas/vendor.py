from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class VendorCreate(BaseModel):
    company_name: str = Field(..., min_length=1, max_length=500)
    person_name: Optional[str] = Field(None, max_length=500)
    phone: str = Field(..., min_length=8, max_length=32)
    secondary_phone: Optional[str] = Field(None, max_length=32)
    address: Optional[str] = None
    city: Optional[str] = Field(None, max_length=200)
    city_id: Optional[int] = None
    gst_number: Optional[str] = Field(None, max_length=20)
    alias: Optional[str] = Field(None, max_length=200)


class VendorUpdate(BaseModel):
    person_name: Optional[str] = Field(None, min_length=1, max_length=500)
    phone: Optional[str] = Field(None, min_length=8, max_length=32)
    company_name: Optional[str] = Field(None, max_length=500)
    secondary_phone: Optional[str] = Field(None, max_length=32)
    address: Optional[str] = None
    city: Optional[str] = Field(None, max_length=200)
    city_id: Optional[int] = None
    gst_number: Optional[str] = Field(None, max_length=20)
    alias: Optional[str] = Field(None, max_length=200)


class VendorPublic(BaseModel):
    id: int
    person_name: str
    phone: str
    company_name: Optional[str]
    alias: Optional[str]
    secondary_phone: Optional[str]
    address: Optional[str]
    city: Optional[str]
    city_id: Optional[int] = None
    gst_number: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
