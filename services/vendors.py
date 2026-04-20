from sqlalchemy.orm import Session

from backend.services.whatsapp import normalize_phone
from db.models import Vendor


def list_vendors(db: Session):
    return db.query(Vendor).order_by(Vendor.name).all()


def get_vendor(db: Session, vendor_id: int):
    return db.query(Vendor).filter(Vendor.id == vendor_id).first()


def create_vendor(db: Session, **kwargs):
    firm_name = kwargs.get("firm_name") or kwargs.get("name")
    kwargs["firm_name"] = firm_name
    kwargs["name"] = firm_name
    kwargs.setdefault("billing_condition", "100%")
    kwargs["phone"] = normalize_phone(kwargs.get("phone"))
    v = Vendor(**kwargs)
    db.add(v)
    db.commit()
    db.refresh(v)
    return v


def update_vendor(db: Session, vendor_id: int, **kwargs):
    v = get_vendor(db, vendor_id)
    if not v:
        return None
    firm_name = kwargs.get("firm_name") or kwargs.get("name") or v.firm_name or v.name
    kwargs["firm_name"] = firm_name
    kwargs["name"] = firm_name
    if "billing_condition" not in kwargs or not kwargs["billing_condition"]:
        kwargs["billing_condition"] = v.billing_condition or "100%"
    if "phone" in kwargs:
        kwargs["phone"] = normalize_phone(kwargs.get("phone"))
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
