from sqlalchemy.orm import Session

from backend.services.whatsapp import normalize_phone
from db.models import Customer


def list_customers(db: Session):
    return db.query(Customer).order_by(Customer.created_at.desc()).all()


def get_customer(db: Session, customer_id: int):
    return db.query(Customer).filter(Customer.id == customer_id).first()


def create_customer(db: Session, **kwargs):
    if "phone" in kwargs:
        kwargs["phone"] = normalize_phone(kwargs.get("phone"))
    if "whatsapp_phone" in kwargs:
        kwargs["whatsapp_phone"] = normalize_phone(kwargs.get("whatsapp_phone"))
    customer = Customer(**kwargs)
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


def update_customer(db: Session, customer_id: int, **kwargs):
    customer = get_customer(db, customer_id)
    if not customer:
        return None
    if "phone" in kwargs:
        kwargs["phone"] = normalize_phone(kwargs.get("phone"))
    if "whatsapp_phone" in kwargs:
        kwargs["whatsapp_phone"] = normalize_phone(kwargs.get("whatsapp_phone"))
    for key, value in kwargs.items():
        setattr(customer, key, value)
    db.commit()
    db.refresh(customer)
    return customer


def delete_customer(db: Session, customer_id: int):
    customer = get_customer(db, customer_id)
    if customer:
        db.delete(customer)
        db.commit()
    return customer
