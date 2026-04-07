from fastapi import APIRouter
from db.database import SessionLocal
from services.products import list_products
from services.inventory import get_stock

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("/products")
def products():
    db = SessionLocal()
    try:
        items = list_products(db)
        stock_rows = {inv.product_id: inv.quantity_available for inv, _ in get_stock(db)}
        return [
            {
                "id": p.id,
                "name": p.name,
                "sku": p.sku,
                "price": p.selling_price,
                "available": stock_rows.get(p.id, 0),
            }
            for p in items if p.active
        ]
    finally:
        db.close()
