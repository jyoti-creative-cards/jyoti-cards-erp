from sqlalchemy.orm import Session

from db.models import Vendor


def list_vendors(db: Session):
    return db.query(Vendor).order_by(Vendor.name).all()


def get_vendor(db: Session, vendor_id: int):
    return db.query(Vendor).filter(Vendor.id == vendor_id).first()


def create_vendor(db: Session, **kwargs):
    v = Vendor(**kwargs)
    db.add(v)
    db.commit()
    db.refresh(v)
    return v


def update_vendor(db: Session, vendor_id: int, **kwargs):
    v = get_vendor(db, vendor_id)
    if not v:
        return None
    for k, value in kwargs.items():
        setattr(v, k, value)
    db.commit()
    db.refresh(v)
    return v


def delete_vendor(db: Session, vendor_id: int):
    v = get_vendor(db, vendor_id)
    if v:
        db.delete(v)
        db.commit()
    return v
