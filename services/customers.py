from sqlalchemy.orm import Session
from db.models import Customer


def list_customers(db: Session):
    return db.query(Customer).order_by(Customer.name).all()


def get_customer(db: Session, customer_id: int):
    return db.query(Customer).filter(Customer.id == customer_id).first()


def create_customer(db: Session, **kwargs):
    c = Customer(**kwargs)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def update_customer(db: Session, customer_id: int, **kwargs):
    c = db.query(Customer).filter(Customer.id == customer_id).first()
    if not c:
        return None
    for k, v in kwargs.items():
        setattr(c, k, v)
    db.commit()
    db.refresh(c)
    return c


def delete_customer(db: Session, customer_id: int):
    c = db.query(Customer).filter(Customer.id == customer_id).first()
    if c:
        db.delete(c)
        db.commit()
    return c
