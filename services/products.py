from sqlalchemy.orm import Session
from db.models import Product, Inventory


def list_products(db: Session):
    return db.query(Product).order_by(Product.name).all()


def get_product(db: Session, product_id: int):
    return db.query(Product).filter(Product.id == product_id).first()


def create_product(db: Session, **kwargs):
    p = Product(**kwargs)
    db.add(p)
    db.flush()
    inv = Inventory(product_id=p.id, quantity_available=0, quantity_reserved=0)
    db.add(inv)
    db.commit()
    db.refresh(p)
    return p


def update_product(db: Session, product_id: int, **kwargs):
    p = db.query(Product).filter(Product.id == product_id).first()
    if not p:
        return None
    for k, v in kwargs.items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    return p


def delete_product(db: Session, product_id: int):
    p = db.query(Product).filter(Product.id == product_id).first()
    if p:
        inv = db.query(Inventory).filter(Inventory.product_id == product_id).first()
        if inv:
            db.delete(inv)
        db.delete(p)
        db.commit()
    return p
