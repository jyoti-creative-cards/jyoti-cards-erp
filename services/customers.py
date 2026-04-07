from sqlalchemy.orm import Session

from db.models import Customer


def list_customers(db: Session):
    return db.query(Customer).order_by(Customer.name).all()


def get_customer(db: Session, customer_id: int):
    return db.query(Customer).filter(Customer.id == customer_id).first()


def get_customer_by_whatsapp(db: Session, phone: str):
    return db.query(Customer).filter(Customer.whatsapp_phone == phone).first()


def get_or_create_customer_by_whatsapp(db: Session, phone: str):
    customer = get_customer_by_whatsapp(db, phone)
    if customer:
        return customer
    customer = Customer(name=f"WhatsApp {phone}", phone=phone, whatsapp_phone=phone, customer_type="retailer", payment_mode="credit")
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


def create_customer(db: Session, **kwargs):
    c = Customer(**kwargs)
    if not c.whatsapp_phone:
        c.whatsapp_phone = c.phone
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def update_customer(db: Session, customer_id: int, **kwargs):
    c = get_customer(db, customer_id)
    if not c:
        return None
    for k, value in kwargs.items():
        setattr(c, k, value)
    db.commit()
    db.refresh(c)
    return c


def delete_customer(db: Session, customer_id: int):
    c = get_customer(db, customer_id)
    if c:
        db.delete(c)
        db.commit()
    return c
