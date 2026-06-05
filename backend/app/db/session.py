from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import String, cast, create_engine, or_, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session, declarative_base, sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from app.config import get_settings

Base = declarative_base()

_settings = get_settings()
_db_url = _settings.database_url.strip()
_is_sqlite = _db_url.lower().startswith("sqlite:")
_connect_args: dict = {}
if _is_sqlite:
    _connect_args["check_same_thread"] = False
elif "supabase" in _db_url.lower():
    if "sslmode=" not in _db_url.lower():
        _db_url += "&sslmode=require" if "?" in _db_url else "?sslmode=require"
    if "connect_timeout=" not in _db_url.lower():
        _db_url += "&connect_timeout=15" if "?" in _db_url else "?connect_timeout=15"
engine = create_engine(
    _db_url,
    pool_pre_ping=not _is_sqlite,
    connect_args=_connect_args,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def sql_is_active_true(column: ColumnElement[bool]) -> ColumnElement[bool]:
    """WHERE clause: row is active. SQLite may store legacy BOOLEAN as TEXT 'true'."""
    if engine.dialect.name != "sqlite":
        return column.is_(True)
    return or_(
        column.is_(True),
        column == 1,
        cast(column, String).in_(("true", "True", "1")),
    )


def legacy_active_value(v: object) -> bool:
    """ORM-loaded flag (SQLite quirk: may be str)."""
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    if isinstance(v, int):
        return v != 0
    s = str(v).strip().lower()
    return s in ("true", "1", "yes")


def _migrate_catalog_our_product_id_postgres() -> None:
    """Existing DBs created before our_product_id: add column and backfill."""
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE portal_catalog_products ADD COLUMN IF NOT EXISTS our_product_id VARCHAR(120)"
            )
        )
        conn.execute(
            text(
                "UPDATE portal_catalog_products SET our_product_id = id::text "
                "WHERE our_product_id IS NULL"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE portal_catalog_products ALTER COLUMN our_product_id SET NOT NULL"
            )
        )
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "ALTER TABLE portal_catalog_products "
                    "ADD CONSTRAINT uq_catalog_our_product_id UNIQUE (our_product_id)"
                )
            )
    except ProgrammingError:
        pass


def _migrate_catalog_prices_postgres() -> None:
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE portal_catalog_products ADD COLUMN IF NOT EXISTS "
                "buying_price NUMERIC(14,4) NOT NULL DEFAULT 0"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE portal_catalog_products ADD COLUMN IF NOT EXISTS "
                "selling_price NUMERIC(14,4) NOT NULL DEFAULT 0"
            )
        )


def _migrate_stock_threshold_postgres() -> None:
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE portal_stock_balances ADD COLUMN IF NOT EXISTS "
                "low_stock_threshold INTEGER NOT NULL DEFAULT 0"
            )
        )


def _migrate_customer_order_shipment_postgres() -> None:
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE portal_customer_orders ADD COLUMN IF NOT EXISTS "
                "shipment_receipt VARCHAR(255)"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE portal_customer_orders ADD COLUMN IF NOT EXISTS "
                "shipment_contact VARCHAR(128)"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE portal_customer_orders ADD COLUMN IF NOT EXISTS shipment_notes TEXT"
            )
        )


def _migrate_po_notes_and_receipt_contact_postgres() -> None:
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE portal_vendor_purchase_orders ADD COLUMN IF NOT EXISTS notes TEXT"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE portal_stock_receipts ADD COLUMN IF NOT EXISTS "
                "contact_number VARCHAR(64)"
            )
        )


def _migrate_customer_confirmed_delivery_postgres() -> None:
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE portal_customer_orders ADD COLUMN IF NOT EXISTS "
                "customer_confirmed_delivery_at TIMESTAMPTZ"
            )
        )


def _repair_sqlite_is_active_text_values() -> None:
    """SQLite DDL from server_default='true' stored TEXT; boolean filters expect 0/1."""
    if engine.dialect.name != "sqlite":
        return
    tables = (
        "portal_customers",
        "portal_vendors",
        "portal_catalog_products",
        "portal_bank_accounts",
    )
    with engine.begin() as conn:
        for tbl in tables:
            conn.execute(
                text(
                    f"UPDATE {tbl} SET is_active = 1 WHERE typeof(is_active) = 'text' "
                    f"AND lower(cast(is_active AS TEXT)) IN ('true', '1')"
                )
            )
            conn.execute(
                text(
                    f"UPDATE {tbl} SET is_active = 0 WHERE typeof(is_active) = 'text' "
                    f"AND lower(cast(is_active AS TEXT)) IN ('false', '0')"
                )
            )
            conn.execute(text(f"UPDATE {tbl} SET is_active = 1 WHERE is_active IS NULL"))


def _migrate_v4_features_postgres() -> None:
    """Add v4 columns: staff users + credit note return fields."""
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        # Staff users table
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS portal_staff_users (
                id SERIAL PRIMARY KEY,
                name VARCHAR(200) NOT NULL,
                email VARCHAR(200) NOT NULL UNIQUE,
                phone VARCHAR(30),
                password_hash VARCHAR(512) NOT NULL,
                role VARCHAR(20) NOT NULL DEFAULT 'staff',
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                permissions JSONB NOT NULL DEFAULT '[]',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        # Credit note enhancements
        conn.execute(text("ALTER TABLE portal_credit_notes ADD COLUMN IF NOT EXISTS return_items JSONB"))
        conn.execute(text("ALTER TABLE portal_credit_notes ADD COLUMN IF NOT EXISTS is_full_return BOOLEAN NOT NULL DEFAULT FALSE"))
        conn.execute(text("ALTER TABLE portal_credit_notes ADD COLUMN IF NOT EXISTS refund_method VARCHAR(20) NOT NULL DEFAULT 'credit'"))
        conn.execute(text("ALTER TABLE portal_credit_notes ADD COLUMN IF NOT EXISTS paid_out_at TIMESTAMPTZ"))
        conn.execute(text(
            "ALTER TABLE portal_credit_notes ADD COLUMN IF NOT EXISTS "
            "applied_to_bill_id INTEGER REFERENCES portal_customer_bills(id) ON DELETE SET NULL"
        ))
        conn.execute(text("ALTER TABLE portal_credit_notes ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"))


def init_db() -> None:
    from app.models import (  # noqa: F401
        addon_product,
        ap_bill,
        ar_invoice,
        audit_log,
        bank_reconciliation,
        bill_series,
        catalog_category_label,
        catalog_product,
        catalog_product_alternative,
        chart_account,
        city,
        credit_debit_note,
        customer,
        customer_bill,
        customer_order,
        expense,
        fiscal_year,
        invoice_payment,
        journal_entry,
        product_price,
        route,
        stock_adjustment,
        stock_balance,
        stock_receipt,
        staff_user,
        vendor,
        vendor_bill,
        vendor_purchase_order,
    )

    Base.metadata.create_all(bind=engine)
    _repair_sqlite_is_active_text_values()
    _migrate_catalog_our_product_id_postgres()
    _migrate_catalog_prices_postgres()
    _migrate_stock_threshold_postgres()
    _migrate_customer_order_shipment_postgres()
    _migrate_po_notes_and_receipt_contact_postgres()
    _migrate_customer_confirmed_delivery_postgres()
    _migrate_soft_delete_columns_postgres()
    _migrate_customer_order_notes_postgres()
    _migrate_new_fields_postgres()
    _migrate_addon_tables_postgres()
    _migrate_v2_features_postgres()
    _migrate_v3_features_postgres()
    _migrate_v4_features_postgres()
    from app.services.accounting import seed_chart_accounts

    s = SessionLocal()
    try:
        seed_chart_accounts(s)
        s.commit()
    finally:
        s.close()


def _migrate_customer_order_notes_postgres() -> None:
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE portal_customer_orders ADD COLUMN IF NOT EXISTS customer_notes TEXT"
        ))
        conn.execute(text(
            "ALTER TABLE portal_customer_orders ADD COLUMN IF NOT EXISTS invoice_date TIMESTAMPTZ"
        ))
        conn.execute(text(
            "ALTER TABLE portal_customer_orders ADD COLUMN IF NOT EXISTS invoice_no VARCHAR(100)"
        ))
        conn.execute(text(
            "ALTER TABLE portal_customer_orders ADD COLUMN IF NOT EXISTS receipt_note_no VARCHAR(100)"
        ))
        conn.execute(text(
            "ALTER TABLE portal_catalog_products ADD COLUMN IF NOT EXISTS series VARCHAR(120)"
        ))
        conn.execute(text(
            "ALTER TABLE portal_catalog_products ADD COLUMN IF NOT EXISTS year_group VARCHAR(30)"
        ))


def _migrate_soft_delete_columns_postgres() -> None:
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        for tbl, col in [
            ("portal_customers", "is_active"),
            ("portal_vendors", "is_active"),
            ("portal_catalog_products", "is_active"),
        ]:
            conn.execute(text(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS {col} BOOLEAN NOT NULL DEFAULT TRUE"))


def _migrate_new_fields_postgres() -> None:
    """Add all new columns: customer credit/route/alias, vendor alias, expense/price/route/city tables."""
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        # Customer new columns
        for col_sql in [
            "ALTER TABLE portal_customers ADD COLUMN IF NOT EXISTS alias VARCHAR(200)",
            "ALTER TABLE portal_customers ADD COLUMN IF NOT EXISTS city_id INTEGER REFERENCES portal_cities(id) ON DELETE SET NULL",
            "ALTER TABLE portal_customers ADD COLUMN IF NOT EXISTS route_id INTEGER REFERENCES portal_routes(id) ON DELETE SET NULL",
            "ALTER TABLE portal_customers ADD COLUMN IF NOT EXISTS credit_limit NUMERIC(14,4)",
            "ALTER TABLE portal_customers ADD COLUMN IF NOT EXISTS credit_override BOOLEAN NOT NULL DEFAULT FALSE",
            # Vendor alias
            "ALTER TABLE portal_vendors ADD COLUMN IF NOT EXISTS alias VARCHAR(200)",
            # Catalog unit
            "ALTER TABLE portal_catalog_products ADD COLUMN IF NOT EXISTS unit VARCHAR(50) NOT NULL DEFAULT 'pcs'",
        ]:
            conn.execute(text(col_sql))


def _migrate_addon_tables_postgres() -> None:
    """Ensure addon tables and columns exist."""
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS portal_addon_products (
                id SERIAL PRIMARY KEY,
                name VARCHAR(300) NOT NULL,
                description VARCHAR(1000),
                unit VARCHAR(50) NOT NULL DEFAULT 'pcs',
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS portal_addon_stock (
                addon_product_id INTEGER PRIMARY KEY REFERENCES portal_addon_products(id) ON DELETE CASCADE,
                quantity INTEGER NOT NULL DEFAULT 0,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS portal_catalog_product_addons (
                id SERIAL PRIMARY KEY,
                catalog_product_id INTEGER NOT NULL REFERENCES portal_catalog_products(id) ON DELETE CASCADE,
                addon_product_id INTEGER NOT NULL REFERENCES portal_addon_products(id) ON DELETE CASCADE,
                quantity_per_card INTEGER NOT NULL DEFAULT 1
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS portal_freight_vendors (
                id SERIAL PRIMARY KEY,
                name VARCHAR(200) NOT NULL,
                phone VARCHAR(30),
                notes TEXT,
                balance_due NUMERIC(14,2) NOT NULL DEFAULT 0
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS portal_freight_ledger (
                id SERIAL PRIMARY KEY,
                freight_vendor_id INTEGER NOT NULL REFERENCES portal_freight_vendors(id) ON DELETE CASCADE,
                entry_date DATE NOT NULL,
                entry_type VARCHAR(20) NOT NULL DEFAULT 'charge',
                amount NUMERIC(14,2) NOT NULL,
                reference VARCHAR(200),
                notes TEXT
            )
        """))


def _migrate_v2_features_postgres() -> None:
    """Add v2 columns: bill_no, bill_series_id, deleted_at for all key tables."""
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE portal_customer_bills ADD COLUMN IF NOT EXISTS bill_no VARCHAR(100)"
        ))
        conn.execute(text(
            "ALTER TABLE portal_customer_bills ADD COLUMN IF NOT EXISTS "
            "bill_series_id INTEGER REFERENCES portal_bill_series(id) ON DELETE SET NULL"
        ))
        conn.execute(text(
            "ALTER TABLE portal_customer_bills ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ"
        ))
        conn.execute(text(
            "ALTER TABLE portal_customers ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ"
        ))
        conn.execute(text(
            "ALTER TABLE portal_vendors ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ"
        ))
        conn.execute(text(
            "ALTER TABLE portal_catalog_products ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ"
        ))
        conn.execute(text(
            "ALTER TABLE portal_customer_orders ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ"
        ))
        conn.execute(text(
            "ALTER TABLE portal_vendor_purchase_orders ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ"
        ))


def _migrate_v3_features_postgres() -> None:
    """Add v3 columns: vendor_bill_no and bill_photo_key on stock receipts."""
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE portal_stock_receipts ADD COLUMN IF NOT EXISTS vendor_bill_no VARCHAR(200)"))
        conn.execute(text("ALTER TABLE portal_stock_receipts ADD COLUMN IF NOT EXISTS bill_photo_key VARCHAR(512)"))


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
