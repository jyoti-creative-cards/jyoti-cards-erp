from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ops.db")
engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from db.models import (
        Product, Vendor, Customer, Inventory,
        PurchaseOrder, PurchaseOrderItem,
        SalesOrder, SalesOrderItem,
        Delivery, Payment, Ledger, InventoryTransaction, WhatsAppLog,
    )
    Base.metadata.create_all(bind=engine)
    _run_sqlite_migrations()


def _run_sqlite_migrations():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    migrations = {
        "products": {
            "vendor_id": "ALTER TABLE products ADD COLUMN vendor_id INTEGER",
            "image_path": "ALTER TABLE products ADD COLUMN image_path VARCHAR(500)",
        },
        "customers": {
            "customer_type": "ALTER TABLE customers ADD COLUMN customer_type VARCHAR(20) DEFAULT 'retailer'",
            "payment_mode": "ALTER TABLE customers ADD COLUMN payment_mode VARCHAR(20) DEFAULT 'credit'",
        },
    }

    for table_name, table_migrations in migrations.items():
        cursor.execute(f"PRAGMA table_info({table_name})")
        existing_columns = {row[1] for row in cursor.fetchall()}
        for column_name, statement in table_migrations.items():
            if column_name not in existing_columns:
                cursor.execute(statement)

    conn.commit()
    conn.close()
