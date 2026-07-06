from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import String, cast, create_engine, or_, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session, declarative_base, sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from app.config import get_settings

Base = declarative_base()

import re as _re

_settings = get_settings()
_db_url = _settings.database_url.strip()
_is_sqlite = _db_url.lower().startswith("sqlite:")


def _supabase_to_pooler(url: str) -> str:
    """Transform a Supabase direct connection URL to the pgBouncer pooler URL.

    Direct:  postgresql://postgres:PWD@db.PROJECT.supabase.co:5432/postgres
    Pooler:  postgresql://postgres.PROJECT:PWD@aws-1-ap-southeast-1.pooler.supabase.com:6543/postgres
    """
    m = _re.match(
        r"postgresql(?:\+psycopg2)?://postgres:([^@]+)@db\.([a-z0-9]+)\.supabase\.co:5432/(.+)",
        url,
    )
    if not m:
        return url
    pwd, project, dbname = m.group(1), m.group(2), m.group(3)
    pooler_host = "aws-1-ap-southeast-1.pooler.supabase.com"
    new_url = f"postgresql://postgres.{project}:{pwd}@{pooler_host}:6543/{dbname}"
    print(f"[session] auto-transformed Supabase direct URL → pgBouncer pooler")
    return new_url


if not _is_sqlite and "db." in _db_url and ".supabase.co:5432" in _db_url:
    _db_url = _supabase_to_pooler(_db_url)

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
    pool_size=5 if not _is_sqlite else 1,
    max_overflow=10 if not _is_sqlite else 0,
    pool_recycle=300 if not _is_sqlite else -1,
    pool_timeout=30,
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
                username VARCHAR(100) NOT NULL UNIQUE,
                password_hash VARCHAR(512) NOT NULL,
                role VARCHAR(20) NOT NULL DEFAULT 'staff',
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                permissions JSONB NOT NULL DEFAULT '[]',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        # Fix schema if table was created with old email-based schema (email was NOT NULL, no username)
        conn.execute(text("ALTER TABLE portal_staff_users ADD COLUMN IF NOT EXISTS username VARCHAR(100)"))
        # Make legacy columns nullable so they don't block inserts from the new model
        conn.execute(text("""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='portal_staff_users' AND column_name='email'
                    AND is_nullable='NO'
                ) THEN
                    ALTER TABLE portal_staff_users ALTER COLUMN email DROP NOT NULL;
                END IF;
            END $$;
        """))
        # Drop phone column if it exists (removed from model)
        conn.execute(text("ALTER TABLE portal_staff_users DROP COLUMN IF EXISTS phone"))
        # Backfill NULL usernames with generated values from email or name
        conn.execute(text("""
            UPDATE portal_staff_users
            SET username = LOWER(REGEXP_REPLACE(COALESCE(email, name), '[^a-zA-Z0-9_\\-]', '.', 'g')) || '.' || id::text
            WHERE username IS NULL
        """))
        # Add unique index on username
        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_indexes
                    WHERE tablename='portal_staff_users' AND indexname='uq_staff_username'
                ) THEN
                    CREATE UNIQUE INDEX uq_staff_username ON portal_staff_users(username)
                    WHERE username IS NOT NULL;
                END IF;
            END $$;
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


def _migrate_v8_vendor_gst_postgres() -> None:
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE portal_vendors ADD COLUMN IF NOT EXISTS gst_number VARCHAR(20)"))


def _migrate_v9_customer_gst_postgres() -> None:
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE portal_customers ADD COLUMN IF NOT EXISTS gst_number VARCHAR(20)"))


def _migrate_v10_vendor_city_id_postgres() -> None:
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE portal_vendors ADD COLUMN IF NOT EXISTS city_id INTEGER REFERENCES portal_cities(id) ON DELETE SET NULL"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_stock_adj_product_created ON portal_stock_adjustments (catalog_product_id, created_at)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_stock_receipt_vendor_created ON portal_stock_receipts (vendor_id, created_at)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_customer_orders_status ON portal_customer_orders (status, deleted_at)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_customer_orders_customer ON portal_customer_orders (customer_id, id DESC)"
        ))


def _migrate_v11_normalize_open_status_postgres() -> None:
    """Normalize all legacy 'open' and 'confirmed' customer orders to 'received'."""
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE portal_customer_orders SET status = 'received' WHERE status IN ('open', 'confirmed')"
        ))


def _migrate_v12_vendor_bill_columns_postgres() -> None:
    """Add vendor_order_id, vendor_id, bill_number, bill_amount to portal_vendor_bills."""
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE portal_vendor_bills ADD COLUMN IF NOT EXISTS vendor_order_id INTEGER REFERENCES portal_vendor_orders(id) ON DELETE SET NULL"))
        conn.execute(text("ALTER TABLE portal_vendor_bills ADD COLUMN IF NOT EXISTS vendor_id INTEGER REFERENCES portal_vendors(id) ON DELETE SET NULL"))
        conn.execute(text("ALTER TABLE portal_vendor_bills ADD COLUMN IF NOT EXISTS bill_number VARCHAR(200)"))
        conn.execute(text("ALTER TABLE portal_vendor_bills ADD COLUMN IF NOT EXISTS bill_amount NUMERIC(14,4)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_vendor_bills_vendor_order ON portal_vendor_bills(vendor_order_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_vendor_bills_vendor ON portal_vendor_bills(vendor_id)"))
        # Also add items column to customer bills for per-bill line tracking
        conn.execute(text("ALTER TABLE portal_customer_bills ADD COLUMN IF NOT EXISTS items JSONB"))
        # Drop NOT NULL on purchase_order_id since PO system was removed
        conn.execute(text("ALTER TABLE portal_vendor_bills ALTER COLUMN purchase_order_id DROP NOT NULL"))
        conn.execute(text("ALTER TABLE portal_ap_bills ALTER COLUMN purchase_order_id DROP NOT NULL"))


def _migrate_v13_vendor_company_name_notnull_postgres() -> None:
    """Make portal_vendors.company_name NOT NULL (backfill from person_name)."""
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        # Backfill NULL company_name from person_name before adding NOT NULL
        conn.execute(text(
            "UPDATE portal_vendors SET company_name = person_name WHERE company_name IS NULL OR company_name = ''"
        ))
        conn.execute(text(
            "ALTER TABLE portal_vendors ALTER COLUMN company_name SET NOT NULL"
        ))


def _migrate_v9_vendor_order_debit_note_postgres() -> None:
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE portal_debit_notes ADD COLUMN IF NOT EXISTS vendor_order_id INTEGER REFERENCES portal_vendor_orders(id) ON DELETE RESTRICT"))
        conn.execute(text("ALTER TABLE portal_debit_notes ALTER COLUMN purchase_order_id DROP NOT NULL"))
        conn.execute(text("ALTER TABLE portal_debit_notes ADD COLUMN IF NOT EXISTS note_type VARCHAR(20) NOT NULL DEFAULT 'value'"))
        conn.execute(text("ALTER TABLE portal_debit_notes ADD COLUMN IF NOT EXISTS items JSONB"))


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
        vendor_order,
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
    _migrate_v5_vendor_receipt_postgres()
    _migrate_v6b_order_versions_postgres()
    _migrate_v7_bill_narration_postgres()
    _migrate_v6_vendor_orders_postgres()
    _migrate_v8_vendor_gst_postgres()
    _migrate_v9_customer_gst_postgres()
    _migrate_v9_vendor_order_debit_note_postgres()
    _migrate_v10_vendor_city_id_postgres()
    _migrate_v11_normalize_open_status_postgres()
    _migrate_v12_vendor_bill_columns_postgres()
    _migrate_v13_vendor_company_name_notnull_postgres()
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


def _migrate_v3_features_postgres() -> None:
    """Add v3 columns: vendor_bill_no and bill_photo_key on stock receipts."""
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE portal_stock_receipts ADD COLUMN IF NOT EXISTS vendor_bill_no VARCHAR(200)"))
        conn.execute(text("ALTER TABLE portal_stock_receipts ADD COLUMN IF NOT EXISTS bill_photo_key VARCHAR(512)"))


def _migrate_v5_vendor_receipt_postgres() -> None:
    """Add v5: vendor-level receipt support on stock_receipts table."""
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        # Make purchase_order_id nullable (for vendor-level receipts)
        conn.execute(text("""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='portal_stock_receipts' AND column_name='purchase_order_id'
                    AND is_nullable='NO'
                ) THEN
                    ALTER TABLE portal_stock_receipts ALTER COLUMN purchase_order_id DROP NOT NULL;
                END IF;
            END $$;
        """))
        # Add vendor_id column
        conn.execute(text("""
            ALTER TABLE portal_stock_receipts
            ADD COLUMN IF NOT EXISTS vendor_id INTEGER REFERENCES portal_vendors(id) ON DELETE SET NULL
        """))
        # Add extra_charges column
        conn.execute(text("ALTER TABLE portal_stock_receipts ADD COLUMN IF NOT EXISTS extra_charges NUMERIC(14,4)"))
        # Add image_key column (alias for receipt_image_key used in vendor receipt flow)
        conn.execute(text("ALTER TABLE portal_stock_receipts ADD COLUMN IF NOT EXISTS image_key VARCHAR(512)"))


def _migrate_v7_bill_narration_postgres() -> None:
    """Add narration, bill_status, cancelled_by, cancelled_reason; drop unique on customer_order_id."""
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE portal_customer_bills ADD COLUMN IF NOT EXISTS narration TEXT"))
        conn.execute(text("ALTER TABLE portal_customer_bills ADD COLUMN IF NOT EXISTS bill_status VARCHAR(20) NOT NULL DEFAULT 'active'"))
        conn.execute(text("ALTER TABLE portal_customer_bills ADD COLUMN IF NOT EXISTS cancelled_by VARCHAR(200)"))
        conn.execute(text("ALTER TABLE portal_customer_bills ADD COLUMN IF NOT EXISTS cancelled_reason TEXT"))
        # Drop the unique constraint so multiple bill versions can exist per order
        # Constraint name may vary; try both common naming patterns
        try:
            conn.execute(text("ALTER TABLE portal_customer_bills DROP CONSTRAINT IF EXISTS portal_customer_bills_customer_order_id_key"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE portal_customer_bills DROP CONSTRAINT IF EXISTS uq_portal_customer_bills_customer_order_id"))
        except Exception:
            pass


def _migrate_v6b_order_versions_postgres() -> None:
    """Add versions JSONB column to portal_customer_orders."""
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE portal_customer_orders ADD COLUMN IF NOT EXISTS versions JSONB"))


def _migrate_v6_vendor_orders_postgres() -> None:
    """Add v6: portal_vendor_orders table + customer order qty_billed tracking."""
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS portal_vendor_orders (
                id SERIAL PRIMARY KEY,
                vendor_id INTEGER NOT NULL REFERENCES portal_vendors(id) ON DELETE CASCADE,
                status VARCHAR(20) NOT NULL DEFAULT 'open',
                items JSONB NOT NULL DEFAULT '[]',
                notes TEXT,
                bill_number VARCHAR(200),
                bill_amount NUMERIC(14,4),
                bill_key VARCHAR(512),
                bill_uploaded_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_portal_vendor_orders_vendor_id ON portal_vendor_orders(vendor_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_portal_vendor_orders_status ON portal_vendor_orders(status)"))
        # Add qty_billed to customer order items (tracked in JSON items array — no column needed)
        # Allow customer order status 'open' in addition to existing values
        # (no constraint to alter — status is a plain VARCHAR)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
