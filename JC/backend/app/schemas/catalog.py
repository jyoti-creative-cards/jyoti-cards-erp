from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field


class CatalogProductPublic(BaseModel):
    id: int
    our_product_id: str
    vendor_id: int
    vendor_name: Optional[str] = None
    vendor_city: Optional[str] = None
    vendor_product_id: str
    category: Optional[str]
    series: Optional[str]
    unit: Optional[str]
    year_group: Optional[str]
    buying_price: str
    selling_price: Optional[str]
    image_keys: List[str]
    image_urls: List[str] = []
    is_active: bool
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    addon_count: int = 0
    alt_count: int = 0


class AlternativePublic(BaseModel):
    id: int
    product_id: int
    alternative_product_id: int
    alternative_our_product_id: str
    alternative_vendor_name: Optional[str] = None
    alternative_vendor_city: Optional[str] = None
    buying_price: Optional[str] = None
    selling_price: Optional[str] = None
    image_urls: List[str] = []


class AddonLinkPublic(BaseModel):
    id: int
    catalog_product_id: int
    addon_product_id: int
    addon_our_product_id: str
    addon_name: Optional[str]
    quantity: int
    image_urls: List[str] = []


class CatalogDetail(CatalogProductPublic):
    alternatives: List[AlternativePublic] = []
    addon_links: List[AddonLinkPublic] = []
    price_history: List[dict] = []
    change_history: List[dict] = []


class CatalogBulkItem(BaseModel):
    our_product_id: str = Field(..., min_length=1, max_length=120)
    vendor_product_id: str = Field(..., min_length=1, max_length=255)
    category: Optional[str] = None
    series: Optional[str] = None
    unit: Optional[str] = None
    year_group: Optional[str] = None
    buying_price: Decimal = Field(..., ge=0)
    selling_price: Optional[Decimal] = Field(None, ge=0)
    image_keys: List[str] = []
    alternative_our_product_ids: List[str] = Field(default_factory=list, max_length=3)
    addon_links: List["AddonLinkIn"] = []


class AddonLinkIn(BaseModel):
    addon_our_product_id: str
    quantity: int = Field(..., ge=1)


class CatalogBulkCreate(BaseModel):
    vendor_id: int
    items: List[CatalogBulkItem] = Field(..., min_length=1)


class CatalogListResponse(BaseModel):
    items: List[CatalogProductPublic]
    total: int
    limit: int
    offset: int


class VendorOption(BaseModel):
    id: int
    business_name: str
    city_name: Optional[str] = None
    alias: Optional[str] = None
    is_active: bool


class CheckDuplicatesRequest(BaseModel):
    our_product_ids: List[str] = Field(..., min_length=1)


class CheckDuplicatesResponse(BaseModel):
    duplicates: List[str] = []


class CatalogUpdate(BaseModel):
    our_product_id: Optional[str] = Field(None, min_length=1, max_length=120)
    vendor_product_id: Optional[str] = None
    category: Optional[str] = None
    series: Optional[str] = None
    unit: Optional[str] = None
    year_group: Optional[str] = None
    buying_price: Optional[Decimal] = Field(None, ge=0)
    selling_price: Optional[Decimal] = Field(None, ge=0)
    image_keys: Optional[List[str]] = None
    alternative_our_product_ids: Optional[List[str]] = Field(None, max_length=3)
    addon_links: Optional[List[AddonLinkIn]] = None
