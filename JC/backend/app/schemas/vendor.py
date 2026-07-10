from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class VendorCreate(BaseModel):
    business_name: str = Field(..., min_length=1, max_length=500)
    phone: str = Field(..., min_length=10, max_length=32)
    city_id: int
    person_name: Optional[str] = Field(None, max_length=500)
    secondary_phone: Optional[str] = Field(None, max_length=32)
    alias: Optional[str] = Field(None, max_length=200)
    address: Optional[str] = None
    gst_number: Optional[str] = Field(None, max_length=20)


class VendorUpdate(BaseModel):
    business_name: Optional[str] = Field(None, min_length=1, max_length=500)
    phone: Optional[str] = Field(None, min_length=10, max_length=32)
    city_id: Optional[int] = None
    person_name: Optional[str] = Field(None, max_length=500)
    secondary_phone: Optional[str] = Field(None, max_length=32)
    alias: Optional[str] = Field(None, max_length=200)
    address: Optional[str] = None
    gst_number: Optional[str] = Field(None, max_length=20)
    is_active: Optional[bool] = None


class VendorPublic(BaseModel):
    id: int
    business_name: str
    phone: str
    person_name: Optional[str]
    secondary_phone: Optional[str]
    alias: Optional[str]
    address: Optional[str]
    city_id: int
    city_name: Optional[str] = None
    gst_number: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    change_history: List[dict] = []
