from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field


class AddonPublic(BaseModel):
    id: int
    our_product_id: str
    vendor_id: int
    vendor_name: Optional[str] = None
    vendor_product_id: str
    name: Optional[str]
    description: Optional[str]
    category: Optional[str]
    unit: str
    buying_price: str
    image_keys: List[str]
    image_urls: List[str] = []
    quantity_on_hand: int = 0
    low_stock_threshold: int = 5
    stock_status: str = "in_stock"  # in_stock | low_stock | out_of_stock | negative_stock
    is_active: bool
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None


class AddonDetail(AddonPublic):
    price_history: List[dict] = []
    change_history: List[dict] = []
    stock_movements: List[dict] = []


class AddonReceiveStockIn(BaseModel):
    quantity: int = Field(..., gt=0)
    total_cost: Optional[Decimal] = Field(None, ge=0)
    expense_date: Optional[str] = None  # ISO date, defaults to today
    note: Optional[str] = None


class AddonAdjustStockIn(BaseModel):
    delta: int = Field(..., ne=0)
    reason: str = Field(..., min_length=1)


class AddonCreate(BaseModel):
    our_product_id: str = Field(..., min_length=1, max_length=120)
    vendor_id: int
    vendor_product_id: str = Field(..., min_length=1, max_length=255)
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    unit: str = Field(..., min_length=1, max_length=50)
    buying_price: Decimal = Field(..., ge=0)
    image_keys: List[str] = []


class AddonUpdate(BaseModel):
    vendor_product_id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    unit: Optional[str] = None
    buying_price: Optional[Decimal] = Field(None, ge=0)
    image_keys: Optional[List[str]] = None
