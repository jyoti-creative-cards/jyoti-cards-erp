from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class CatalogProductCreate(BaseModel):
    our_product_id: str = Field(..., min_length=1, max_length=120, description="Your internal product id / SKU")
    vendor_id: int = Field(..., ge=1)
    name: Optional[str] = Field(None, max_length=500, description="Display name; defaults to category if blank")
    vendor_product_id: str = Field(..., min_length=1, max_length=255, description="Vendor SKU (required)")
    category: str = Field(..., min_length=1, max_length=120)
    series: Optional[str] = Field(None, max_length=120)
    year_group: Optional[str] = Field(None, max_length=30, description="Defaults to current year group if blank")
    unit: str = Field(default="pcs", max_length=50)
    buying_price: float = Field(..., ge=0, description="Our cost from vendor")
    selling_price: Optional[float] = Field(None, ge=0, description="Our sell price (can be set later)")


class AddonLinkInput(BaseModel):
    addon_product_id: int = Field(..., ge=1)
    quantity_per_unit: int = Field(default=1, ge=1)


class BulkCatalogProductCreate(CatalogProductCreate):
    """Extended create schema for bulk endpoint — allows linking add-ons and alternatives inline."""
    addon_links: List[AddonLinkInput] = Field(default_factory=list)
    alt_ids: List[int] = Field(default_factory=list, description="catalog_product_id of alternatives to link")


class CatalogProductUpdate(BaseModel):
    our_product_id: Optional[str] = Field(None, min_length=1, max_length=120)
    vendor_id: Optional[int] = Field(None, ge=1)
    name: Optional[str] = Field(None, max_length=500)
    vendor_product_id: Optional[str] = Field(None, min_length=1, max_length=255)
    category: Optional[str] = Field(None, min_length=1, max_length=120)
    series: Optional[str] = Field(None, max_length=120)
    year_group: Optional[str] = Field(None, max_length=30)
    unit: Optional[str] = Field(None, max_length=50)
    buying_price: Optional[float] = Field(None, ge=0)
    selling_price: Optional[float] = Field(None, ge=0)


class CatalogProductPublic(BaseModel):
    id: int
    our_product_id: str
    vendor_id: int
    name: str
    vendor_product_id: str
    category: str
    series: Optional[str] = None
    year_group: Optional[str] = None
    unit: str = "pcs"
    buying_price: float
    selling_price: Optional[float] = None
    image_keys: List[str]
    image_urls: List[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ImageDeleteBody(BaseModel):
    key: str = Field(..., min_length=1, description="S3 object key under product_images/")


class CategoryLabelCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)


class LookupCreate(BaseModel):
    value: str = Field(..., min_length=1, max_length=120)
    is_current: bool = False


class LookupPublic(BaseModel):
    id: int
    lookup_type: str
    value: str
    is_current: bool
