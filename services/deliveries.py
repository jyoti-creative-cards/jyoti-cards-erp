from sqlalchemy.orm import Session
from db.models import Delivery, DeliveryStatus, SalesOrder


def list_deliveries(db: Session, status: str = None):
    q = db.query(Delivery).order_by(Delivery.created_at.desc())
    if status:
        q = q.filter(Delivery.status == status)
    return q.all()


def update_delivery(db: Session, delivery_id: int, **kwargs):
    d = db.query(Delivery).filter(Delivery.id == delivery_id).first()
    if not d:
        return None
    for k, v in kwargs.items():
        setattr(d, k, v)
    db.commit()
    db.refresh(d)
    return d
