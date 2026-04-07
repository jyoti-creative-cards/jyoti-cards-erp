import pandas as pd
from sqlalchemy.orm import Session

from db.models import SalesOrder, PurchaseOrder, Inventory, Product, PurchaseOrderStatus


def sales_dataframe(db: Session):
    rows = []
    for so in db.query(SalesOrder).all():
        rows.append({"date": so.order_date, "amount": so.total_amount, "channel": so.channel, "status": so.status.value})
    return pd.DataFrame(rows)


def purchase_dataframe(db: Session):
    rows = []
    for po in db.query(PurchaseOrder).all():
        rows.append({"date": po.order_date, "amount": po.final_amount or po.total_amount, "status": po.status.value})
    return pd.DataFrame(rows)


def inventory_dataframe(db: Session):
    rows = []
    for inv, prod in db.query(Inventory, Product).join(Product, Inventory.product_id == Product.id).all():
        total = inv.quantity_available + inv.quantity_reserved
        sold_pct = 0 if total == 0 else round((inv.quantity_reserved / total) * 100, 2)
        rows.append({"product": prod.name, "sku": prod.sku, "available": inv.quantity_available, "reserved": inv.quantity_reserved, "left_percent": 0 if total == 0 else round((inv.quantity_available / total) * 100, 2), "sold_percent": sold_pct})
    return pd.DataFrame(rows)


def vendor_performance_dataframe(db: Session):
    rows = []
    for po in db.query(PurchaseOrder).all():
        rows.append({"vendor": po.vendor.name, "status": po.status.value, "committed": po.vendor_committed_date, "received": po.receiving_date})
    return pd.DataFrame(rows)
