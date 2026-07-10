from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class CustomerCreate(BaseModel):
    business_name: str = Field(..., min_length=1, max_length=500)
    person_name: Optional[str] = Field(None, max_length=500)
    phone: str = Field(..., min_length=10, max_length=32)
    secondary_phone: Optional[str] = Field(None, max_length=32)
    alias: Optional[str] = Field(None, max_length=200)
    address: Optional[str] = None
    city_id: Optional[int] = None
    credit_limit: Optional[float] = None
    credit_override: bool = False
    gst_number: Optional[str] = Field(None, max_length=20)


class CustomerUpdate(BaseModel):
    business_name: Optional[str] = Field(None, min_length=1, max_length=500)
    person_name: Optional[str] = Field(None, max_length=500)
    phone: Optional[str] = Field(None, min_length=10, max_length=32)
    secondary_phone: Optional[str] = Field(None, max_length=32)
    alias: Optional[str] = Field(None, max_length=200)
    address: Optional[str] = None
    city_id: Optional[int] = None
    credit_limit: Optional[float] = None
    credit_override: Optional[bool] = None
    gst_number: Optional[str] = Field(None, max_length=20)
    is_active: Optional[bool] = None


class CustomerPublic(BaseModel):
    id: int
    business_name: str
    person_name: Optional[str]
    phone: str
    secondary_phone: Optional[str]
    alias: Optional[str]
    address: Optional[str]
    city_id: Optional[int]
    route_id: Optional[int]
    city_name: Optional[str] = None
    route_name: Optional[str] = None
    credit_limit: Optional[str]
    credit_override: bool
    gst_number: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    change_history: List[dict] = []


class CityIn(BaseModel):
    name: str
    route_id: Optional[int] = None


class CityUpdate(BaseModel):
    name: Optional[str] = None
    route_id: Optional[int] = None


class CustomerCreateResponse(CustomerPublic):
    whatsapp_sent: bool = False
    whatsapp_error: Optional[str] = None


class LoginRequest(BaseModel):
    phone: str = Field(..., min_length=10)
    password: str = Field(..., min_length=1)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int


class RouteIn(BaseModel):
    name: str
    notes: Optional[str] = None


class RouteUpdate(BaseModel):
    name: Optional[str] = None
    notes: Optional[str] = None


class RoutePublic(BaseModel):
    id: int
    name: str
    notes: Optional[str] = None
    is_active: bool
    city_count: int = 0
    customer_count: int = 0
    deleted_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class RouteDetail(RoutePublic):
    cities: List["CityPublic"] = []


class CityPublic(BaseModel):
    id: int
    name: str
    route_id: Optional[int] = None
    route_name: Optional[str] = None
    is_active: bool
    customer_count: int = 0
    deleted_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class CityDetail(CityPublic):
    customers: List["CustomerPublic"] = []


class RecycleBinItem(BaseModel):
    type: str  # route | city | customer
    id: int
    name: str
    subtitle: Optional[str] = None
    deleted_at: Optional[datetime] = None


class RecycleBinList(BaseModel):
    routes: List[RecycleBinItem] = []
    cities: List[RecycleBinItem] = []
    customers: List[RecycleBinItem] = []
    vendors: List[RecycleBinItem] = []
    catalog_products: List[RecycleBinItem] = []
    addons: List[RecycleBinItem] = []
    staff: List[RecycleBinItem] = []
    total: int = 0
