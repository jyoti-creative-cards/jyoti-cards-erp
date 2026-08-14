from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field


class ReturnLineIn(BaseModel):
    bill_line_id: int
    quantity: int = Field(..., gt=0)


class CustomerReturnCreate(BaseModel):
    customer_id: int
    lines: List[ReturnLineIn]
    credit_amount: Decimal = Field(..., ge=0)
    notes: Optional[str] = None


class ReturnableLineOut(BaseModel):
    bill_line_id: int
    bill_id: int
    bill_number: str
    catalog_product_id: int
    our_product_id: str
    quantity_billed: int
    quantity_returned: int
    quantity_returnable: int
    sold_unit_price: str
    unit_price: str
    bill_date: datetime


class CustomerReturnSummary(BaseModel):
    customer_id: int
    customer_label: str
    business_name: str = ""
    person_name: Optional[str] = None
    alias: Optional[str] = None
    phone: Optional[str] = None
    city_name: Optional[str] = None
    return_count: int
    credit_total: str
    last_return_at: Optional[datetime] = None


class CustomerReturnListItem(BaseModel):
    id: int
    return_number: str
    credit_amount: str
    calculated_amount: str
    notes: Optional[str] = None
    line_count: int
    total_quantity: int
    document_key: Optional[str] = None
    created_by_name: str
    created_at: datetime


class CustomerReturnLineOut(BaseModel):
    id: int
    bill_id: int
    bill_number: str
    bill_line_id: int
    catalog_product_id: int
    our_product_id: str
    quantity_returned: int
    sold_unit_price: str
    line_calculated: str


class CustomerReturnDetail(BaseModel):
    id: int
    customer_id: int
    customer_label: str
    return_number: str
    credit_amount: str
    calculated_amount: str
    notes: Optional[str] = None
    document_key: Optional[str] = None
    created_by_name: str
    created_at: datetime
    lines: List[CustomerReturnLineOut] = []
