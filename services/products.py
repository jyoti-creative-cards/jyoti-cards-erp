from sqlalchemy.orm import Session
from sqlalchemy import or_

from db.models import Product, Inventory


def list_products(db: Session, active_only: bool = False):
    q = db.query(Product).order_by(Product.name)
    if active_only:
        q = q.filter(Product.active.is_(True))
    return q.all()


def search_products(db: Session, query: str):
    return (
        db.query(Product)
        .filter(or_(Product.name.ilike(f"%{query}%"), Product.sku.ilike(f"%{query}%")))
        .order_by(Product.name)
        .all()
    )


def get_product(db: Session, product_id: int):
    return db.query(Product).filter(Product.id == product_id).first()


def get_product_by_name(db: Session, name: str):
    return db.query(Product).filter(Product.name.ilike(name.strip())).first()


def create_product(db: Session, **kwargs):
    kwargs["unit"] = "pcs"
    p = Product(**kwargs)
    db.add(p)
    db.flush()
    db.add(Inventory(product_id=p.id, quantity_available=0, quantity_reserved=0))
    db.commit()
    db.refresh(p)
    return p


def update_product(db: Session, product_id: int, **kwargs):
    kwargs["unit"] = "pcs"
    p = get_product(db, product_id)
    if not p:
        return None
    for k, v in kwargs.items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    return p


def delete_product(db: Session, product_id: int):
    p = get_product(db, product_id)
    if p:
        inv = db.query(Inventory).filter(Inventory.product_id == product_id).first()
        if inv:
            db.delete(inv)
        db.delete(p)
        db.commit()
    return p
