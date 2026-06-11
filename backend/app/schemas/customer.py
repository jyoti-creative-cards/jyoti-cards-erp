from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class CustomerCreate(BaseModel):
    company_name: str = Field(..., min_length=1, max_length=500, description="Shop / business name (required)")
    name: Optional[str] = Field(None, max_length=500, description="Person / contact name (optional; defaults to company_name)")
    phone: str = Field(..., min_length=8, max_length=32)
    password: Optional[str] = Field(None, min_length=4, max_length=128)
    alias: Optional[str] = Field(None, max_length=200)
    address: Optional[str] = None
    secondary_phone: Optional[str] = Field(None, max_length=32)
    city: Optional[str] = Field(None, max_length=200)
    city_id: Optional[int] = None
    route_id: Optional[int] = None
    credit_limit: Optional[Decimal] = None
    credit_override: bool = False


class CustomerUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=500)
    phone: Optional[str] = Field(None, min_length=8, max_length=32)
    password: Optional[str] = Field(None, min_length=4, max_length=128)
    company_name: Optional[str] = Field(None, max_length=500)
    alias: Optional[str] = Field(None, max_length=200)
    address: Optional[str] = None
    secondary_phone: Optional[str] = Field(None, max_length=32)
    city: Optional[str] = Field(None, max_length=200)
    city_id: Optional[int] = None
    route_id: Optional[int] = None
    credit_limit: Optional[Decimal] = None
    credit_override: Optional[bool] = None


class CustomerPublic(BaseModel):
    id: int
    name: str
    phone: str
    company_name: Optional[str]
    alias: Optional[str]
    address: Optional[str]
    secondary_phone: Optional[str]
    city: Optional[str]
    city_id: Optional[int]
    route_id: Optional[int]
    credit_limit: Optional[str]
    credit_override: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": False}


class LoginRequest(BaseModel):
    phone: str = Field(..., min_length=8)
    password: str = Field(..., min_length=1)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int
