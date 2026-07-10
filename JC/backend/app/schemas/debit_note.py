from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


DirectionItem = Literal["short", "extra"]
DirectionValue = Literal["over", "under"]


class DebitNoteIn(BaseModel):
    note_type: Literal["item", "value"]
    direction: Optional[Literal["short", "extra", "over", "under"]] = None
    catalog_product_id: Optional[int] = None
    quantity: Optional[int] = None
    amount: Optional[Decimal] = None
    notes: Optional[str] = None

    @model_validator(mode="after")
    def validate_type(self):
        if self.note_type == "item":
            if not self.catalog_product_id or self.quantity is None or self.quantity == 0:
                raise ValueError("item debit note requires catalog_product_id and non-zero quantity")
            if self.direction is not None and self.direction not in ("short", "extra"):
                raise ValueError("item debit note direction must be short or extra")
        else:
            if self.amount is None or self.amount == 0:
                raise ValueError("value debit note requires non-zero amount")
            if self.direction is not None and self.direction not in ("over", "under"):
                raise ValueError("value debit note direction must be over or under")
        return self


class DebitNoteUpdate(BaseModel):
    note_type: Optional[Literal["item", "value"]] = None
    direction: Optional[Literal["short", "extra", "over", "under"]] = None
    catalog_product_id: Optional[int] = None
    quantity: Optional[int] = None
    amount: Optional[Decimal] = None
    notes: Optional[str] = None


class DebitNoteOut(BaseModel):
    id: int
    vendor_id: int
    receipt_id: int
    note_type: str
    direction: Optional[str] = None
    catalog_product_id: Optional[int]
    our_product_id: Optional[str]
    quantity: Optional[int]
    unit_price: Optional[str]
    amount: str
    payable_effect: str
    notes: Optional[str]
    created_by_name: str
    created_by_type: str
    created_at: datetime
    updated_at: datetime
    bill_number: Optional[str] = None
    vendor_label: Optional[str] = None
