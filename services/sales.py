from sqlalchemy.orm import Session

from backend.services.whatsapp import send_internal_alert, send_whatsapp_message, send_whatsapp_document
from db.models import SalesOrder, SalesOrderItem, SalesStatus, Delivery, DeliveryStatus, Customer, Ledger, DiscountRule
from services.inventory import deduct_stock, add_stock
from services.pdfs import build_sales_order_pdf
from services.products import get_product_by_name
from services.customers import get_customer_by_whatsapp


def list_sales_orders(db: Session, status: str = None):
    q = db.query(SalesOrder).order_by(SalesOrder.created_at.desc())
    if status:
        q = q.filter(SalesOrder.status == status)
    return q.all()


def get_sales_order(db: Session, so_id: int):
    return db.query(SalesOrder).filter(SalesOrder.id == so_id).first()


def _resolve_discount(db: Session, customer_id: int, product_id: int, fallback_discount: float):
    rule = db.query(DiscountRule).filter(DiscountRule.customer_id == customer_id, DiscountRule.product_id == product_id, DiscountRule.active.is_(True)).first()
    return rule.discount_percent if rule else fallback_discount


def create_sales_order(db: Session, customer_id: int, items: list[dict], order_date=None, notes="", channel="manual", discount_percent=0):
    subtotal = sum(i["quantity"] * i["unit_price"] for i in items)
    order_discount = subtotal * (discount_percent / 100)
    total = subtotal - order_discount
    so = SalesOrder(customer_id=customer_id, order_date=order_date, channel=channel, subtotal_amount=subtotal, discount_percent=discount_percent, discount_amount=order_discount, total_amount=total, notes=notes, status=SalesStatus.CONFIRMED)
    db.add(so)
    db.flush()

    for i in items:
        item_discount = _resolve_discount(db, customer_id, i["product_id"], i.get("discount_percent", 0))
        line_total = i["quantity"] * i["unit_price"] * (1 - item_discount / 100)
        deduct_stock(db, i["product_id"], i["quantity"], "sales_order", so.id, notes="Stock deducted on sales order create", commit=False)
        db.add(SalesOrderItem(order_id=so.id, product_id=i["product_id"], quantity=i["quantity"], unit_price=i["unit_price"], discount_percent=item_discount, total_price=line_total))

    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if customer and customer.payment_mode == "credit":
        customer.outstanding_balance += total

    db.add(Ledger(entity_type="customer", entity_id=customer_id, debit=total, credit=0, description=f"SO#{so.id} created", reference_type="sales_order", reference_id=so.id))
    db.commit()
    db.refresh(so)

    if customer and customer.notifications_enabled:
        result = send_whatsapp_message(db, customer.whatsapp_phone or customer.phone, f"Order confirmed. SO#{so.id} amount ₹{so.total_amount:,.0f}", "sales_order", so.id)
        so.customer_notification_status = result.status
        pdf_bytes = build_sales_order_pdf(so)
        send_whatsapp_document(db, customer.whatsapp_phone or customer.phone, f"SO-{so.id}.pdf", pdf_bytes, caption=f"Order receipt SO#{so.id}", related_type="sales_order", related_id=so.id)
    so.internal_notification_status = send_internal_alert(db, f"SO#{so.id} created for {customer.name if customer else customer_id}", "sales_order", so.id).status
    db.commit()
    return so


def create_sales_order_from_names(db: Session, customer_phone: str, items: list[dict], notes: str = ""):
    customer = get_customer_by_whatsapp(db, customer_phone)
    if not customer:
        from services.customers import get_or_create_customer_by_whatsapp
        customer = get_or_create_customer_by_whatsapp(db, customer_phone)
    resolved = []
    for item in items:
        product = get_product_by_name(db, item["name"])
        if not product:
            raise ValueError(f"Product not found: {item['name']}")
        resolved.append({"product_id": product.id, "quantity": item["quantity"], "unit_price": product.selling_price})
    return create_sales_order(db, customer.id, resolved, notes=notes, channel="whatsapp", discount_percent=customer.default_discount_percent)


def update_sales_status(db: Session, so_id: int, new_status: SalesStatus):
    so = get_sales_order(db, so_id)
    if not so:
        raise ValueError("SO not found")
    if new_status == SalesStatus.DISPATCHED:
        db.add(Delivery(sales_order_id=so.id, status=DeliveryStatus.IN_TRANSIT))
    if new_status == SalesStatus.CANCELLED:
        for item in so.items:
            add_stock(db, item.product_id, item.quantity, "sales_order_cancel", so.id, notes="Stock restored on cancel", commit=False)
        if so.customer and so.customer.payment_mode == "credit":
            so.customer.outstanding_balance -= so.total_amount
        db.add(Ledger(entity_type="customer", entity_id=so.customer_id, debit=0, credit=so.total_amount, description=f"SO#{so.id} cancelled", reference_type="sales_order", reference_id=so.id))
    so.status = new_status
    db.commit()
    send_internal_alert(db, f"SO#{so.id} status -> {so.status.value}", "sales_order", so.id)
    return so


def mark_delivered(db: Session, so_id: int):
    so = get_sales_order(db, so_id)
    if so:
        so.status = SalesStatus.DELIVERED
        delivery = db.query(Delivery).filter(Delivery.sales_order_id == so_id).first()
        if delivery:
            from datetime import date
            delivery.status = DeliveryStatus.DELIVERED
            delivery.delivery_date = date.today()
        db.commit()
    return so
