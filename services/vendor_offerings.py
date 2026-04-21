from typing import Optional

from sqlalchemy.orm import Session

from db.models import VendorOffering


def list_vendor_offerings(db: Session, vendor_id: Optional[int] = None, active_only: bool = False):
    q = db.query(VendorOffering).order_by(VendorOffering.created_at.desc())
    if vendor_id:
        q = q.filter(VendorOffering.vendor_id == vendor_id)
    if active_only:
        q = q.filter(VendorOffering.active.is_(True))
    return q.all()


def get_vendor_offering(db: Session, offering_id: int):
    return db.query(VendorOffering).filter(VendorOffering.id == offering_id).first()


def create_vendor_offering(db: Session, **kwargs):
    offering = VendorOffering(**kwargs)
    db.add(offering)
    db.commit()
    db.refresh(offering)
    return offering


def get_vendor_offering_by_vendor_item(db: Session, vendor_id: int, vendor_product_code: str):
    if not vendor_id or not vendor_product_code:
        return None
    return (
        db.query(VendorOffering)
        .filter(
            VendorOffering.vendor_id == vendor_id,
            VendorOffering.vendor_product_code == vendor_product_code,
        )
        .first()
    )


def upsert_vendor_offering(db: Session, vendor_id: int, product_id: int, vendor_product_code: str, vendor_price: float = 0, billing_percent: float = 100, active: bool = True, notes: str = ""):
    offering = get_vendor_offering_by_vendor_item(db, vendor_id, vendor_product_code)
    if not offering:
        return create_vendor_offering(
            db,
            vendor_id=vendor_id,
            product_id=product_id,
            vendor_product_code=vendor_product_code,
            vendor_price=vendor_price,
            billing_percent=billing_percent,
            active=active,
            notes=notes,
        )
    return update_vendor_offering(
        db,
        offering.id,
        product_id=product_id,
        vendor_product_code=vendor_product_code,
        vendor_price=vendor_price,
        billing_percent=billing_percent,
        active=active,
        notes=notes,
    )


def update_vendor_offering(db: Session, offering_id: int, **kwargs):
    offering = get_vendor_offering(db, offering_id)
    if not offering:
        return None
    for key, value in kwargs.items():
        setattr(offering, key, value)
    db.commit()
    db.refresh(offering)
    return offering


def delete_vendor_offering(db: Session, offering_id: int):
    offering = get_vendor_offering(db, offering_id)
    if offering:
        db.delete(offering)
        db.commit()
    return offering
