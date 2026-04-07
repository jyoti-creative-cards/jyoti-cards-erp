from datetime import date

from backend.services.whatsapp import send_internal_alert
from db.models import SalesOrder, PurchaseOrder, Inventory, Product


def build_daily_summary(db):
    today = date.today()
    sales = db.query(SalesOrder).filter(SalesOrder.order_date == today).all()
    pos = db.query(PurchaseOrder).filter(PurchaseOrder.order_date == today).all()
    sales_total = sum(s.total_amount for s in sales)
    po_total = sum((p.final_amount or p.total_amount) for p in pos)
    low_stock = db.query(Inventory, Product).join(Product, Inventory.product_id == Product.id).filter(Inventory.quantity_available <= Product.min_stock_level).count()
    return f"Daily summary {today}: Sales {len(sales)} / ₹{sales_total:,.0f}, POs {len(pos)} / ₹{po_total:,.0f}, Low stock {low_stock}"


def send_daily_summary(db):
    return send_internal_alert(db, build_daily_summary(db), "daily_summary", None)
