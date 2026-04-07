from sqlalchemy.orm import Session

from db.models import Inventory, InventoryTransaction, TxnType, Product


def get_stock(db: Session):
    return db.query(Inventory, Product).join(Product, Inventory.product_id == Product.id).order_by(Product.name).all()


def get_product_stock(db: Session, product_id: int):
    return db.query(Inventory).filter(Inventory.product_id == product_id).first()


def add_stock(db: Session, product_id: int, qty: float, ref_type: str, ref_id: int, notes: str = "", txn_type: TxnType = TxnType.PURCHASE_RECEIPT, commit: bool = True):
    inv = get_product_stock(db, product_id)
    if not inv:
        inv = Inventory(product_id=product_id, quantity_available=0, quantity_reserved=0)
        db.add(inv)
    inv.quantity_available += qty
    db.add(InventoryTransaction(product_id=product_id, txn_type=txn_type, quantity=qty, reference_type=ref_type, reference_id=ref_id, notes=notes))
    if commit:
        db.commit()


def deduct_stock(db: Session, product_id: int, qty: float, ref_type: str, ref_id: int, notes: str = "", commit: bool = True):
    inv = get_product_stock(db, product_id)
    if not inv or inv.quantity_available < qty:
        raise ValueError(f"Insufficient stock for product {product_id}")
    inv.quantity_available -= qty
    db.add(InventoryTransaction(product_id=product_id, txn_type=TxnType.SALE, quantity=-qty, reference_type=ref_type, reference_id=ref_id, notes=notes))
    if commit:
        db.commit()


def get_low_stock(db: Session):
    return db.query(Inventory, Product).join(Product, Inventory.product_id == Product.id).filter(Inventory.quantity_available <= Product.min_stock_level).all()


def get_transactions(db: Session, product_id: int = None, limit: int = 100):
    q = db.query(InventoryTransaction).order_by(InventoryTransaction.created_at.desc())
    if product_id:
        q = q.filter(InventoryTransaction.product_id == product_id)
    return q.limit(limit).all()
