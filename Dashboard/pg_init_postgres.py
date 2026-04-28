"""One-time Postgres schema creation from SQLite DDL (sqlglot)."""
from __future__ import annotations

import re

import sqlglot

from pg_support import database_url


_RE_DT_NOW = re.compile(r"(?i)datetime\s*\(\s*['\"]now['\"]\s*\)")


def _sqlite_stmt_to_pg(sqlite_stmt: str) -> str:
    """sqlglot leaves ``DATETIME('now')`` invalid on Postgres — normalize first + fix output."""
    stmt = sqlite_stmt.strip()
    if not stmt.endswith(";"):
        stmt += ";"
    stmt = _RE_DT_NOW.sub("CURRENT_TIMESTAMP", stmt)
    pg_sql = sqlglot.transpile(stmt, read="sqlite", write="postgres")[0]
    pg_sql = _RE_DT_NOW.sub("CURRENT_TIMESTAMP", pg_sql)
    return pg_sql

CREATE_CUSTOMER_ORDER_SHIPMENTS = """
CREATE TABLE IF NOT EXISTS customer_order_shipments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_order_id INTEGER NOT NULL,
    quantity REAL NOT NULL,
    unit_price REAL NOT NULL,
    delivery_receipt_number TEXT,
    delivery_contact TEXT,
    receipt_image_path TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (customer_order_id) REFERENCES customer_orders (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_cos_order ON customer_order_shipments(customer_order_id);
"""


def _ordered_ddl_blocks():
    import models as m
    import gl

    return [
        m.CREATE_VENDORS_TABLE,
        m.CREATE_VENDOR_PRODUCTS_TABLE,
        m.CREATE_CUSTOMERS_TABLE,
        m.CREATE_WAREHOUSES_TABLE,
        m.CREATE_PURCHASE_ORDERS_TABLE,
        m.CREATE_STOCK_RECEIPTS_TABLE,
        m.CREATE_PO_BILLINGS_TABLE,
        m.CREATE_CUSTOMER_ORDERS_TABLE,
        m.CREATE_CUSTOMER_ORDER_BILLINGS_TABLE,
        CREATE_CUSTOMER_ORDER_SHIPMENTS,
        m.CREATE_PRODUCT_ALTERNATIVES_TABLE,
        gl.SCHEMA,
        m.CREATE_STOCK_MOVEMENTS_TABLE,
        m.CREATE_PURCHASE_ORDER_DOCS_TABLE,
        m.CREATE_PURCHASE_ORDER_DOC_LINES_TABLE,
        m.CREATE_GOODS_RECEIPT_DOCS_TABLE,
        m.CREATE_GOODS_RECEIPT_LINES_TABLE,
        m.CREATE_VENDOR_BILL_DOCS_TABLE,
        m.CREATE_VENDOR_BILL_LINES_TABLE,
        m.CREATE_SALES_ORDER_DOCS_TABLE,
        m.CREATE_SALES_ORDER_DOC_LINES_TABLE,
        m.CREATE_DELIVERY_DOCS_TABLE,
        m.CREATE_DELIVERY_LINES_TABLE,
        m.CREATE_CUSTOMER_INVOICE_DOCS_TABLE,
        m.CREATE_CUSTOMER_INVOICE_LINES_TABLE,
        m.CREATE_AR_PAYMENTS_TABLE,
        m.CREATE_AP_PAYMENTS_TABLE,
    ]


def init_postgres_schema() -> None:
    """Create all tables on empty Supabase DB."""
    import psycopg

    blocks = _ordered_ddl_blocks()
    conn = psycopg.connect(database_url(), autocommit=False)
    try:
        for block in blocks:
            parts = [p.strip() for p in block.split(";") if p.strip()]
            for p in parts:
                pg_sql = _sqlite_stmt_to_pg(p)
                with conn.cursor() as cur:
                    cur.execute(pg_sql)
        conn.commit()
    finally:
        conn.close()
