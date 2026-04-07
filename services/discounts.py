from sqlalchemy.orm import Session

from db.models import DiscountRule


def list_discount_rules(db: Session):
    return db.query(DiscountRule).order_by(DiscountRule.created_at.desc()).all()


def create_discount_rule(db: Session, **kwargs):
    rule = DiscountRule(**kwargs)
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule
