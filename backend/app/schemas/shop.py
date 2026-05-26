from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class ShopProductAlternativePublic(BaseModel):
    catalog_product_id: int
    our_product_id: str = ""
    image_url: str = Field("", description="First product image presigned URL")


class ShopProductPublic(BaseModel):
    catalog_product_id: int
    our_product_id: str = ""
    image_url: str = ""
    selling_price: str = Field(default="0", description="Snapshot list price (for ordering)")
    stock_status: str = Field(
        ...,
        description="in_stock | low_stock | out_of_stock",
    )
    alternatives: List[ShopProductAlternativePublic] = Field(
        default_factory=list,
        description="Filled only when searched product is low_stock or out_of_stock; in-stock substitutes only",
    )


class ShopSuggestionPublic(BaseModel):
    catalog_product_id: int
    our_product_id: str
