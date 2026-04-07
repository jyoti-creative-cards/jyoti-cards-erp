from fastapi import APIRouter
from pydantic import BaseModel

from db.database import SessionLocal
from services.sales import create_sales_order_from_names

router = APIRouter(prefix="/orders", tags=["orders"])


class OrderItemIn(BaseModel):
    name: str
    quantity: float


class OrderIn(BaseModel):
    customer_phone: str
    items: list[OrderItemIn]
    notes: str = ""


@router.post("/whatsapp")
def create_order(payload: OrderIn):
    db = SessionLocal()
    try:
        so = create_sales_order_from_names(db, payload.customer_phone, [i.model_dump() for i in payload.items], payload.notes)
        return {"sales_order_id": so.id, "status": so.status.value}
    finally:
        db.close()
