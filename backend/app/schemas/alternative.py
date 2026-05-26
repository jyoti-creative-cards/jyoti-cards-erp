from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ProductAlternativePublic(BaseModel):
    id: int
    catalog_product_id: int
    alternative_catalog_product_id: int
    alternative_our_product_id: str = ""
    alternative_name: str = ""
    alternative_category: str = ""
    alternative_vendor_id: int = 0
    created_at: datetime


class ProductAlternativeCreate(BaseModel):
    alternative_catalog_product_id: int = Field(..., ge=1)


class ProductAlternativeUpdate(BaseModel):
    alternative_catalog_product_id: int = Field(..., ge=1)
