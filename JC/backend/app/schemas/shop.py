from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class ShopSuggestionPublic(BaseModel):
    catalog_product_id: int
    our_product_id: str


class ShopAlternativePublic(BaseModel):
    catalog_product_id: int
    our_product_id: str
    image_url: str = ""
    stock_status: str
    selling_price: str = "0"


class ShopAddonPublic(BaseModel):
    our_product_id: str
    name: str
    quantity: int = 1
    unit: str = "pc"
    image_url: str = ""


class ShopProductPublic(BaseModel):
    catalog_product_id: int
    our_product_id: str
    image_url: str = ""
    selling_price: str = Field(default="0", description="Sell price per unit (Rs.)")
    stock_status: str = Field(..., description="in_stock | low_stock | out_of_stock")
    addons: List[ShopAddonPublic] = []
    alternatives: List[ShopAlternativePublic] = []


class CustomerOrderCreate(BaseModel):
    catalog_product_id: int
    quantity: int = Field(..., ge=1)
    customer_notes: Optional[str] = None


class PortalPlacementPublic(BaseModel):
    id: int
    line_id: int = 0
    catalog_product_id: int = 0
    our_product_id: str
    image_url: str = ""
    quantity: int
    quantity_shipped: int = 0
    unit_price: str
    line_total: str
    status: str
    customer_notes: Optional[str] = None
    placed_at: str
    bill_id: Optional[int] = None
    bill_number: Optional[str] = None
    has_bill_document: bool = False
    has_order_document: bool = False
