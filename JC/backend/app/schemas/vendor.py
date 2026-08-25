from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class VendorCreate(BaseModel):
    business_name: str = Field(..., min_length=1, max_length=500)
    phone: str = Field(..., min_length=10, max_length=32)
    city_id: Optional[int] = None
    person_name: Optional[str] = Field(None, max_length=500)
    secondary_phone: Optional[str] = Field(None, max_length=32)
    alias: Optional[str] = Field(None, max_length=200)
    address: Optional[str] = None
    gst_number: Optional[str] = Field(None, max_length=20)
    opening_balance_due: Optional[float] = Field(None, ge=0)
    opening_balance_as_on: Optional[date] = None


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


class VendorBillingTerms(BaseModel):
    billing_pct: float = Field(100.0, gt=0, le=100)
    additional_charge: float = Field(100.0, ge=0)
    additional_charge_label: str = Field("Additional charge", max_length=50)
    discount_pct: float = Field(0.0, ge=0, le=100)
    gst_included: bool = True
    gst_rate_pct: float = Field(18.0, ge=0, le=100)
    billing_notes: Optional[str] = None


class VendorPublic(BaseModel):
    id: int
    business_name: str
    phone: str
    person_name: Optional[str]
    secondary_phone: Optional[str]
    alias: Optional[str]
    address: Optional[str]
    city_id: Optional[int] = None
    city_name: Optional[str] = None
    gst_number: Optional[str]
    is_active: bool
    opening_balance_due: Optional[str] = None
    opening_balance_as_on: Optional[str] = None
    billing_terms: VendorBillingTerms
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    change_history: List[dict] = []
