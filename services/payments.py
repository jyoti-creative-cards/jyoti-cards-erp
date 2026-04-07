from sqlalchemy.orm import Session

from backend.services.whatsapp import send_internal_alert
from db.models import Payment, PaymentType, Ledger, Customer


def list_payments(db: Session, payment_type: str = None):
    q = db.query(Payment).order_by(Payment.created_at.desc())
    if payment_type:
        q = q.filter(Payment.payment_type == payment_type)
    return q.all()


def record_customer_payment(db: Session, customer_id: int, amount: float, reference: str = "", notes: str = ""):
    p = Payment(payment_type=PaymentType.INCOMING, customer_id=customer_id, amount=amount, reference=reference, notes=notes)
    db.add(p)
    cust = db.query(Customer).filter(Customer.id == customer_id).first()
    if cust:
        cust.outstanding_balance -= amount
    db.add(Ledger(entity_type="customer", entity_id=customer_id, debit=0, credit=amount, description=f"Payment received - {reference}", reference_type="payment"))
    db.commit()
    db.refresh(p)
    send_internal_alert(db, f"Customer payment received ₹{amount:,.0f}", "payment", p.id)
    return p


def record_vendor_payment(db: Session, vendor_id: int, amount: float, reference: str = "", notes: str = ""):
    p = Payment(payment_type=PaymentType.OUTGOING, vendor_id=vendor_id, amount=amount, reference=reference, notes=notes)
    db.add(p)
    db.add(Ledger(entity_type="vendor", entity_id=vendor_id, debit=0, credit=amount, description=f"Payment made - {reference}", reference_type="payment"))
    db.commit()
    db.refresh(p)
    send_internal_alert(db, f"Vendor payment made ₹{amount:,.0f}", "payment", p.id)
    return p


def get_customer_ledger(db: Session, customer_id: int):
    return db.query(Ledger).filter(Ledger.entity_type == "customer", Ledger.entity_id == customer_id).order_by(Ledger.created_at.desc()).all()


def get_vendor_ledger(db: Session, vendor_id: int):
    return db.query(Ledger).filter(Ledger.entity_type == "vendor", Ledger.entity_id == vendor_id).order_by(Ledger.created_at.desc()).all()
