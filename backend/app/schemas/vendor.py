from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class VendorCreate(BaseModel):
    person_name: str = Field(..., min_length=1, max_length=500)
    phone: str = Field(..., min_length=8, max_length=32)
    company_name: Optional[str] = Field(None, max_length=500)
    secondary_phone: Optional[str] = Field(None, max_length=32)
    address: Optional[str] = None
    billing_percentage: Optional[int] = Field(None, ge=0, le=100)
    city: Optional[str] = Field(None, max_length=200)


class VendorUpdate(BaseModel):
    person_name: Optional[str] = Field(None, min_length=1, max_length=500)
    phone: Optional[str] = Field(None, min_length=8, max_length=32)
    company_name: Optional[str] = Field(None, max_length=500)
    secondary_phone: Optional[str] = Field(None, max_length=32)
    address: Optional[str] = None
    billing_percentage: Optional[int] = Field(None, ge=0, le=100)
    city: Optional[str] = Field(None, max_length=200)


class VendorPublic(BaseModel):
    id: int
    person_name: str
    phone: str
    company_name: Optional[str]
    secondary_phone: Optional[str]
    address: Optional[str]
    billing_percentage: Optional[int]
    city: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
