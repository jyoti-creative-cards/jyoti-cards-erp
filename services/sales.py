from sqlalchemy.orm import Session
from db.models import (
    SalesOrder, SalesOrderItem, SalesStatus,
    Delivery, DeliveryStatus, Customer, Ledger,
)
from services.inventory import deduct_stock, add_stock


def list_sales_orders(db: Session, status: str = None):
    q = db.query(SalesOrder).order_by(SalesOrder.created_at.desc())
    if status:
        q = q.filter(SalesOrder.status == status)
    return q.all()


def get_sales_order(db: Session, so_id: int):
    return db.query(SalesOrder).filter(SalesOrder.id == so_id).first()


def create_sales_order(db: Session, customer_id: int, items: list[dict], order_date=None, notes=""):
    total = sum(i["quantity"] * i["unit_price"] for i in items)
    so = SalesOrder(
        customer_id=customer_id,
        order_date=order_date,
        total_amount=total,
        notes=notes,
    )
    db.add(so)
    db.flush()

    for i in items:
        deduct_stock(db, i["product_id"], i["quantity"], "sales_order", so.id, notes="Stock deducted on sales order creation", commit=False)
        item = SalesOrderItem(
            order_id=so.id,
            product_id=i["product_id"],
            quantity=i["quantity"],
            unit_price=i["unit_price"],
            total_price=i["quantity"] * i["unit_price"],
        )
        db.add(item)

    # Ledger: customer outstanding increases
    cust = db.query(Customer).filter(Customer.id == customer_id).first()
    if cust:
        cust.outstanding_balance += total

    ledger = Ledger(
        entity_type="customer",
        entity_id=customer_id,
        debit=total,
        credit=0,
        description=f"SO#{so.id} created",
        reference_type="sales_order",
        reference_id=so.id,
    )
    db.add(ledger)
    db.commit()
    db.refresh(so)
    return so


def update_sales_status(db: Session, so_id: int, new_status: SalesStatus):
    so = db.query(SalesOrder).filter(SalesOrder.id == so_id).first()
    if not so:
        raise ValueError("SO not found")

    if new_status == SalesStatus.DISPATCHED:
        delivery = Delivery(sales_order_id=so.id, status=DeliveryStatus.IN_TRANSIT)
        db.add(delivery)

    if new_status == SalesStatus.CANCELLED:
        for item in so.items:
            add_stock(db, item.product_id, item.quantity, "sales_order_cancel", so.id, notes="Stock restored on sales order cancel", commit=False)
        cust = db.query(Customer).filter(Customer.id == so.customer_id).first()
        if cust:
            cust.outstanding_balance -= so.total_amount
        ledger = Ledger(
            entity_type="customer",
            entity_id=so.customer_id,
            debit=0,
            credit=so.total_amount,
            description=f"SO#{so.id} cancelled",
            reference_type="sales_order",
            reference_id=so.id,
        )
        db.add(ledger)

    so.status = new_status
    db.commit()
    db.refresh(so)
    return so


def mark_delivered(db: Session, so_id: int):
    so = db.query(SalesOrder).filter(SalesOrder.id == so_id).first()
    if so:
        so.status = SalesStatus.DELIVERED
        delivery = db.query(Delivery).filter(Delivery.sales_order_id == so_id).first()
        if delivery:
            delivery.status = DeliveryStatus.DELIVERED
            from datetime import date
            delivery.delivery_date = date.today()
        db.commit()
    return so
