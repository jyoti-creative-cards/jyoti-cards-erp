from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class LookupCreate(BaseModel):
    lookup_type: str = Field(..., pattern="^(category|series|unit|year_group)$")
    value: str = Field(..., min_length=1, max_length=120)


class LookupPublic(BaseModel):
    id: int
    lookup_type: str
    value: str
    is_active: bool
    created_at: datetime


class HistoryPublic(BaseModel):
    id: int
    entity_type: str
    entity_id: int
    snapshot_json: str
    change_summary: Optional[str]
    valid_from: datetime
    valid_to: Optional[datetime]


class PriceHistoryPublic(BaseModel):
    id: int
    entity_type: str
    entity_id: int
    buying_price: str
    selling_price: Optional[str]
    recorded_at: datetime
