from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, Field


class CustomerBillGenerate(BaseModel):
    customer_order_id: int = Field(..., ge=1)
    gst_enabled: bool = False
    gst_rate_percent: Decimal = Field(default=Decimal("18"), description="GST % e.g. 18 for 18%")
    discount_percent: Optional[Decimal] = Field(
        None, description="Optional discount % on inclusive subtotal", ge=0, le=100
    )
    freight_charges: Optional[Decimal] = Field(None, description="Freight / shipping charges in Rs.", ge=0)
    packaging_charges: Optional[Decimal] = Field(None, description="Packaging charges in Rs.", ge=0)


class CustomerBillPublic(BaseModel):
    id: int
    customer_order_id: int
    gst_enabled: bool
    gst_rate_percent: str
    discount_percent: Optional[str] = None
    totals: dict[str, Any]
    document_key: Optional[str] = None
    document_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime
