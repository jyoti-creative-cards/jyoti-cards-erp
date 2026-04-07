import os
import sqlite3
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

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
    from db import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    _run_sqlite_migrations()


def _run_sqlite_migrations():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    migrations = {
        "products": {
            "vendor_id": "ALTER TABLE products ADD COLUMN vendor_id INTEGER",
            "image_path": "ALTER TABLE products ADD COLUMN image_path VARCHAR(500)",
            "reorder_level": "ALTER TABLE products ADD COLUMN reorder_level FLOAT DEFAULT 0",
            "active": "ALTER TABLE products ADD COLUMN active BOOLEAN DEFAULT 1",
        },
        "vendors": {
            "gst_number": "ALTER TABLE vendors ADD COLUMN gst_number VARCHAR(50)",
            "gst_percent": "ALTER TABLE vendors ADD COLUMN gst_percent FLOAT DEFAULT 0",
            "gst_inclusive": "ALTER TABLE vendors ADD COLUMN gst_inclusive BOOLEAN DEFAULT 0",
            "default_shipment_mode": "ALTER TABLE vendors ADD COLUMN default_shipment_mode VARCHAR(50)",
            "transporter_name": "ALTER TABLE vendors ADD COLUMN transporter_name VARCHAR(200)",
            "transporter_contact": "ALTER TABLE vendors ADD COLUMN transporter_contact VARCHAR(50)",
        },
        "customers": {
            "customer_type": "ALTER TABLE customers ADD COLUMN customer_type VARCHAR(20) DEFAULT 'retailer'",
            "payment_mode": "ALTER TABLE customers ADD COLUMN payment_mode VARCHAR(20) DEFAULT 'credit'",
            "whatsapp_phone": "ALTER TABLE customers ADD COLUMN whatsapp_phone VARCHAR(20)",
            "default_discount_percent": "ALTER TABLE customers ADD COLUMN default_discount_percent FLOAT DEFAULT 0",
            "notifications_enabled": "ALTER TABLE customers ADD COLUMN notifications_enabled BOOLEAN DEFAULT 1",
        },
        "purchase_orders": {
            "vendor_committed_date": "ALTER TABLE purchase_orders ADD COLUMN vendor_committed_date DATE",
            "loading_date": "ALTER TABLE purchase_orders ADD COLUMN loading_date DATE",
            "receiving_date": "ALTER TABLE purchase_orders ADD COLUMN receiving_date DATE",
            "gst_amount": "ALTER TABLE purchase_orders ADD COLUMN gst_amount FLOAT DEFAULT 0",
            "final_amount": "ALTER TABLE purchase_orders ADD COLUMN final_amount FLOAT DEFAULT 0",
            "shipment_mode": "ALTER TABLE purchase_orders ADD COLUMN shipment_mode VARCHAR(50)",
            "transport_name": "ALTER TABLE purchase_orders ADD COLUMN transport_name VARCHAR(200)",
            "transport_contact": "ALTER TABLE purchase_orders ADD COLUMN transport_contact VARCHAR(50)",
            "vendor_notification_status": "ALTER TABLE purchase_orders ADD COLUMN vendor_notification_status VARCHAR(20) DEFAULT 'pending'",
            "internal_notification_status": "ALTER TABLE purchase_orders ADD COLUMN internal_notification_status VARCHAR(20) DEFAULT 'pending'",
        },
        "sales_orders": {
            "channel": "ALTER TABLE sales_orders ADD COLUMN channel VARCHAR(20) DEFAULT 'manual'",
            "subtotal_amount": "ALTER TABLE sales_orders ADD COLUMN subtotal_amount FLOAT DEFAULT 0",
            "discount_percent": "ALTER TABLE sales_orders ADD COLUMN discount_percent FLOAT DEFAULT 0",
            "discount_amount": "ALTER TABLE sales_orders ADD COLUMN discount_amount FLOAT DEFAULT 0",
            "customer_notification_status": "ALTER TABLE sales_orders ADD COLUMN customer_notification_status VARCHAR(20) DEFAULT 'pending'",
            "internal_notification_status": "ALTER TABLE sales_orders ADD COLUMN internal_notification_status VARCHAR(20) DEFAULT 'pending'",
        },
        "sales_order_items": {
            "discount_percent": "ALTER TABLE sales_order_items ADD COLUMN discount_percent FLOAT DEFAULT 0",
        },
        "whatsapp_logs": {
            "related_type": "ALTER TABLE whatsapp_logs ADD COLUMN related_type VARCHAR(50)",
            "related_id": "ALTER TABLE whatsapp_logs ADD COLUMN related_id INTEGER",
            "status": "ALTER TABLE whatsapp_logs ADD COLUMN status VARCHAR(20) DEFAULT 'logged'",
        },
        "purchase_order_items": {
            "gst_percent": "ALTER TABLE purchase_order_items ADD COLUMN gst_percent FLOAT DEFAULT 0",
        },
    }

    for table_name, table_migrations in migrations.items():
        cursor.execute(f"PRAGMA table_info({table_name})")
        existing_columns = {row[1] for row in cursor.fetchall()}
        for column_name, statement in table_migrations.items():
            if column_name not in existing_columns:
                cursor.execute(statement)

    legacy_updates = [
        ("sales_orders", "status", {
            "PENDING": "pending",
            "CREATED": "created",
            "CONFIRMED": "confirmed",
            "PACKED": "packed",
            "DISPATCHED": "dispatched",
            "DELIVERED": "delivered",
            "CANCELLED": "cancelled",
        }),
        ("purchase_orders", "status", {
            "PENDING": "pending",
            "CREATED": "created",
            "APPROVED": "approved",
            "LOADED": "loaded",
            "IN_TRANSIT": "in_transit",
            "RECEIVED": "received",
            "MATCHED": "matched",
            "CLOSED": "closed",
            "DISPUTED": "disputed",
            "PARTIALLY_RECEIVED": "partially_received",
            "COMPLETED": "completed",
            "CANCELLED": "cancelled",
        }),
        ("purchase_orders", "vendor_notification_status", {
            "PENDING": "pending",
            "SENT": "sent",
            "FAILED": "failed",
            "SKIPPED": "skipped",
            "MOCK_SENT": "mock_sent",
        }),
        ("purchase_orders", "internal_notification_status", {
            "PENDING": "pending",
            "SENT": "sent",
            "FAILED": "failed",
            "SKIPPED": "skipped",
            "MOCK_SENT": "mock_sent",
        }),
        ("sales_orders", "customer_notification_status", {
            "PENDING": "pending",
            "SENT": "sent",
            "FAILED": "failed",
            "SKIPPED": "skipped",
            "MOCK_SENT": "mock_sent",
        }),
        ("sales_orders", "internal_notification_status", {
            "PENDING": "pending",
            "SENT": "sent",
            "FAILED": "failed",
            "SKIPPED": "skipped",
            "MOCK_SENT": "mock_sent",
        }),
        ("inventory_transactions", "txn_type", {
            "PURCHASE": "purchase",
            "PURCHASE_RECEIPT": "purchase_receipt",
            "SALE": "sale",
            "SALE_CANCEL": "sale_cancel",
            "ADJUSTMENT": "adjustment",
        }),
        ("deliveries", "status", {
            "PENDING": "pending",
            "IN_TRANSIT": "in_transit",
            "DELIVERED": "delivered",
        }),
        ("payments", "payment_type", {
            "INCOMING": "incoming",
            "OUTGOING": "outgoing",
        }),
        ("three_way_matches", "status", {
            "PENDING": "pending",
            "MATCHED": "matched",
            "DISPUTED": "disputed",
        }),
    ]

    for table_name, column_name, replacements in legacy_updates:
        cursor.execute(f"PRAGMA table_info({table_name})")
        existing_columns = {row[1] for row in cursor.fetchall()}
        if column_name not in existing_columns:
            continue
        for old_value, new_value in replacements.items():
            cursor.execute(
                f"UPDATE {table_name} SET {column_name} = ? WHERE {column_name} = ?",
                (new_value, old_value),
            )

    conn.commit()
    conn.close()
