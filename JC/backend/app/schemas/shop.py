from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class ShopSuggestionPublic(BaseModel):
    catalog_product_id: int
    our_product_id: str
    image_url: str = ""
    selling_price: str = "0"
    stock_status: str = "in_stock"
    category: Optional[str] = None


class ShopAlternativePublic(BaseModel):
    catalog_product_id: int
    our_product_id: str
    image_url: str = ""
    stock_status: str
    selling_price: str = "0"
    category: Optional[str] = None


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
    selling_price: str = Field(default="0", description="Your buying price / our sell price (Rs.)")
    # Portal-safe: never expose on-hand qty. "low_stock" is collapsed to in_stock.
    stock_status: str = Field(..., description="in_stock | out_of_stock")
    category: Optional[str] = None
    year_group: Optional[str] = None
    addons: List[ShopAddonPublic] = []
    alternatives: List[ShopAlternativePublic] = []


class CustomerOrderCreate(BaseModel):
    catalog_product_id: int
    quantity: int = Field(..., ge=50)
    customer_notes: Optional[str] = None

    @field_validator("quantity")
    @classmethod
    def quantity_multiple_of_50(cls, v: int) -> int:
        if v < 50 or v % 50 != 0:
            raise ValueError("Quantity must be a multiple of 50")
        return v


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
    category: Optional[str] = None
    series: Optional[str] = None
    unit: Optional[str] = None


class ShopAccountProfile(BaseModel):
    id: int
    business_name: str
    person_name: Optional[str] = None
    phone: str
    secondary_phone: Optional[str] = None
    address: Optional[str] = None
    city_name: Optional[str] = None
    route_name: Optional[str] = None
    gst_number: Optional[str] = None


class ShopAccountMoney(BaseModel):
    pending: str = "0"  # outstanding
    paid: str = "0"
    billed: str = "0"
    credit_notes: str = "0"
    opening: str = "0"
    credit_limit: Optional[str] = None
    remaining_limit: Optional[str] = None
    unlimited: bool = False


class ShopLedgerEntryPublic(BaseModel):
    id: int
    entry_type: str  # bill | payment | credit_note | opening_balance
    label: str  # Bill | Payment | Credit | Opening
    amount: str
    signed_amount: str
    running_balance: str
    description: Optional[str] = None
    bill_id: Optional[int] = None
    payment_ref: Optional[str] = None
    date: str  # ISO date for dealer


class ShopAccountPublic(BaseModel):
    profile: ShopAccountProfile
    money: ShopAccountMoney
    ledger: List[ShopLedgerEntryPublic] = []


class ShopOrderHistoryLine(BaseModel):
    catalog_product_id: int
    our_product_id: str
    image_url: str = ""
    quantity: int
    quantity_shipped: int = 0
    unit_price: str
    line_total: str
    category: Optional[str] = None
    bill_id: Optional[int] = None
    bill_number: Optional[str] = None
    has_bill_document: bool = False


class ShopOrderHistoryPublic(BaseModel):
    id: int  # placement id
    placed_at: str
    status: str  # ordered | partly_sent | completed
    customer_notes: Optional[str] = None
    total_amount: str
    has_order_document: bool = False
    lines: List[ShopOrderHistoryLine] = []
