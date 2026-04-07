from sqlalchemy.orm import Session
from db.models import Inventory, InventoryTransaction, TxnType, Product


def get_stock(db: Session):
    return (
        db.query(Inventory, Product)
        .join(Product, Inventory.product_id == Product.id)
        .order_by(Product.name)
        .all()
    )


def get_product_stock(db: Session, product_id: int):
    return db.query(Inventory).filter(Inventory.product_id == product_id).first()


def add_stock(db: Session, product_id: int, qty: float, ref_type: str, ref_id: int, notes: str = "", commit: bool = True):
    inv = db.query(Inventory).filter(Inventory.product_id == product_id).first()
    if not inv:
        inv = Inventory(product_id=product_id, quantity_available=0, quantity_reserved=0)
        db.add(inv)
    inv.quantity_available += qty

    txn = InventoryTransaction(
        product_id=product_id,
        txn_type=TxnType.PURCHASE,
        quantity=qty,
        reference_type=ref_type,
        reference_id=ref_id,
        notes=notes,
    )
    db.add(txn)
    if commit:
        db.commit()


def deduct_stock(db: Session, product_id: int, qty: float, ref_type: str, ref_id: int, notes: str = "", commit: bool = True):
    inv = db.query(Inventory).filter(Inventory.product_id == product_id).first()
    if not inv or inv.quantity_available < qty:
        raise ValueError(f"Insufficient stock for product {product_id}")
    inv.quantity_available -= qty

    txn = InventoryTransaction(
        product_id=product_id,
        txn_type=TxnType.SALE,
        quantity=-qty,
        reference_type=ref_type,
        reference_id=ref_id,
        notes=notes,
    )
    db.add(txn)
    if commit:
        db.commit()


def reserve_stock(db: Session, product_id: int, qty: float):
    inv = db.query(Inventory).filter(Inventory.product_id == product_id).first()
    if not inv or inv.quantity_available < qty:
        raise ValueError(f"Insufficient stock for product {product_id}")
    inv.quantity_available -= qty
    inv.quantity_reserved += qty
    db.commit()


def release_reserved(db: Session, product_id: int, qty: float):
    """Move reserved stock back to available (e.g. order cancelled)."""
    inv = db.query(Inventory).filter(Inventory.product_id == product_id).first()
    if inv:
        inv.quantity_reserved -= qty
        inv.quantity_available += qty
        db.commit()


def fulfill_reserved(db: Session, product_id: int, qty: float, ref_type: str, ref_id: int):
    """Consume reserved stock (dispatch)."""
    inv = db.query(Inventory).filter(Inventory.product_id == product_id).first()
    if inv:
        inv.quantity_reserved -= qty
        txn = InventoryTransaction(
            product_id=product_id,
            txn_type=TxnType.SALE,
            quantity=-qty,
            reference_type=ref_type,
            reference_id=ref_id,
        )
        db.add(txn)
        db.commit()


def get_low_stock(db: Session):
    return (
        db.query(Inventory, Product)
        .join(Product, Inventory.product_id == Product.id)
        .filter(Inventory.quantity_available <= Product.min_stock_level)
        .all()
    )


def get_transactions(db: Session, product_id: int = None, limit: int = 50):
    q = db.query(InventoryTransaction).order_by(InventoryTransaction.created_at.desc())
    if product_id:
        q = q.filter(InventoryTransaction.product_id == product_id)
    return q.limit(limit).all()
