from sqlalchemy.orm import Session
from db.models import (
    PurchaseOrder, PurchaseOrderItem, OrderStatus,
    Ledger,
)
from services.inventory import add_stock


def list_purchase_orders(db: Session, status: str = None):
    q = db.query(PurchaseOrder).order_by(PurchaseOrder.created_at.desc())
    if status:
        q = q.filter(PurchaseOrder.status == status)
    return q.all()


def get_purchase_order(db: Session, po_id: int):
    return db.query(PurchaseOrder).filter(PurchaseOrder.id == po_id).first()


def create_purchase_order(db: Session, vendor_id: int, items: list[dict], order_date=None, expected_date=None, notes=""):
    total = sum(i["quantity"] * i["unit_price"] for i in items)
    po = PurchaseOrder(
        vendor_id=vendor_id,
        order_date=order_date,
        expected_date=expected_date,
        total_amount=total,
        notes=notes,
    )
    db.add(po)
    db.flush()

    for i in items:
        item = PurchaseOrderItem(
            order_id=po.id,
            product_id=i["product_id"],
            quantity_ordered=i["quantity"],
            quantity_received=i["quantity"],
            unit_price=i["unit_price"],
            total_price=i["quantity"] * i["unit_price"],
        )
        db.add(item)
        add_stock(db, i["product_id"], i["quantity"], "purchase_order", po.id, notes="Stock added on PO creation", commit=False)

    # Ledger: vendor payable increases
    ledger = Ledger(
        entity_type="vendor",
        entity_id=vendor_id,
        debit=total,
        credit=0,
        description=f"PO#{po.id} created",
        reference_type="purchase_order",
        reference_id=po.id,
    )
    db.add(ledger)
    po.status = OrderStatus.COMPLETED
    db.commit()
    db.refresh(po)
    return po


def receive_goods(db: Session, po_id: int, received_items: list[dict]):
    """
    received_items: [{"item_id": ..., "quantity_received": ...}]
    """
    po = db.query(PurchaseOrder).filter(PurchaseOrder.id == po_id).first()
    if not po:
        raise ValueError("PO not found")

    all_complete = True
    for ri in received_items:
        item = db.query(PurchaseOrderItem).filter(PurchaseOrderItem.id == ri["item_id"]).first()
        if not item:
            continue
        item.quantity_received += ri["quantity_received"]
        add_stock(db, item.product_id, ri["quantity_received"], "purchase_order", po.id, commit=False)
        if item.quantity_received < item.quantity_ordered:
            all_complete = False

    if all_complete:
        po.status = OrderStatus.COMPLETED
    else:
        po.status = OrderStatus.PARTIALLY_RECEIVED

    db.commit()
    db.refresh(po)
    return po
