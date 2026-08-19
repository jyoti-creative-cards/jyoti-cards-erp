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


def _migrate_v14_catalog_lookups_postgres() -> None:
    """Create portal_catalog_lookups table; make vendor_product_id nullable; seed defaults."""
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS portal_catalog_lookups (
                id SERIAL PRIMARY KEY,
                lookup_type VARCHAR(20) NOT NULL,
                value VARCHAR(120) NOT NULL,
                is_current BOOLEAN NOT NULL DEFAULT false,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_catalog_lookup_type_value UNIQUE (lookup_type, value)
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_catalog_lookups_type ON portal_catalog_lookups(lookup_type)"
        ))
        # Seed default units
        for u in ["pcs", "bundle", "box", "dozen", "set", "pair", "roll", "sheet"]:
            conn.execute(text(
                "INSERT INTO portal_catalog_lookups (lookup_type, value) VALUES ('unit', :v) ON CONFLICT DO NOTHING"
            ), {"v": u})
        # Seed current year group — compute dynamically
        import datetime as _dt
        _now = _dt.datetime.now()
        _y1 = _now.year if _now.month >= 4 else _now.year - 1
        _current_yg = f"{_y1}-{str(_y1 + 1)[-2:]}"
        conn.execute(text(
            "INSERT INTO portal_catalog_lookups (lookup_type, value, is_current) VALUES ('year_group', :v, true) ON CONFLICT DO NOTHING"
        ), {"v": _current_yg})
        # Make vendor_product_id optional
        conn.execute(text(
            "ALTER TABLE portal_catalog_products ALTER COLUMN vendor_product_id DROP NOT NULL"
        ))
        # Drop unique constraint on (vendor_id, vendor_product_id) to allow NULL vendor_product_ids
        conn.execute(text(
            "ALTER TABLE portal_catalog_products DROP CONSTRAINT IF EXISTS uq_catalog_vendor_product_ext"
        ))


def _migrate_v15_addon_products_and_catalog_fixes_postgres() -> None:
    """
    Expand portal_addon_products with vendor identity fields.
    Restore vendor_product_id NOT NULL on catalog products.
    Make selling_price nullable on catalog products.
    """
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        # ── Expand addon_products ──────────────────────────────────────────────
        conn.execute(text(
            "ALTER TABLE portal_addon_products ADD COLUMN IF NOT EXISTS our_product_id VARCHAR(120)"
        ))
        conn.execute(text(
            "ALTER TABLE portal_addon_products ADD COLUMN IF NOT EXISTS vendor_id INTEGER REFERENCES portal_vendors(id) ON DELETE RESTRICT"
        ))
        conn.execute(text(
            "ALTER TABLE portal_addon_products ADD COLUMN IF NOT EXISTS vendor_product_id VARCHAR(255)"
        ))
        conn.execute(text(
            "ALTER TABLE portal_addon_products ADD COLUMN IF NOT EXISTS category VARCHAR(120)"
        ))
        conn.execute(text(
            "ALTER TABLE portal_addon_products ADD COLUMN IF NOT EXISTS buying_price NUMERIC(14,4) NOT NULL DEFAULT 0"
        ))
        conn.execute(text(
            "ALTER TABLE portal_addon_products ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ"
        ))
        conn.execute(text(
            "ALTER TABLE portal_addon_products ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
        ))
        # Unique constraint on our_product_id (only where not null)
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_addon_our_product_id ON portal_addon_products(our_product_id) WHERE our_product_id IS NOT NULL"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_addon_vendor_id ON portal_addon_products(vendor_id) WHERE vendor_id IS NOT NULL"
        ))
        # Backfill our_product_id and vendor_product_id for legacy rows that have NULLs
        conn.execute(text(
            "UPDATE portal_addon_products SET our_product_id = 'ADDON-' || id::text WHERE our_product_id IS NULL"
        ))
        conn.execute(text(
            "UPDATE portal_addon_products SET vendor_product_id = our_product_id WHERE vendor_product_id IS NULL"
        ))
        # After backfill, enforce NOT NULL
        conn.execute(text(
            "ALTER TABLE portal_addon_products ALTER COLUMN our_product_id SET NOT NULL"
        ))
        conn.execute(text(
            "ALTER TABLE portal_addon_products ALTER COLUMN vendor_product_id SET NOT NULL"
        ))
        # Rename quantity_per_card → quantity_per_unit if old column exists
        conn.execute(text("""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'portal_catalog_product_addons' AND column_name = 'quantity_per_card'
                ) THEN
                    ALTER TABLE portal_catalog_product_addons RENAME COLUMN quantity_per_card TO quantity_per_unit;
                END IF;
            END$$
        """))

        # ── Catalog fixes ──────────────────────────────────────────────────────
        # Backfill NULL vendor_product_ids before restoring NOT NULL
        conn.execute(text(
            "UPDATE portal_catalog_products SET vendor_product_id = our_product_id WHERE vendor_product_id IS NULL OR vendor_product_id = ''"
        ))
        # Restore vendor_product_id NOT NULL
        conn.execute(text(
            "ALTER TABLE portal_catalog_products ALTER COLUMN vendor_product_id SET NOT NULL"
        ))
        # Re-add unique constraint on (vendor_id, vendor_product_id) - use partial to allow empty strings safely
        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'uq_catalog_vendor_product_ext'
                ) THEN
                    ALTER TABLE portal_catalog_products
                    ADD CONSTRAINT uq_catalog_vendor_product_ext UNIQUE (vendor_id, vendor_product_id);
                END IF;
            END$$
        """))
        # Make selling_price nullable
        conn.execute(text(
            "ALTER TABLE portal_catalog_products ALTER COLUMN selling_price DROP NOT NULL"
        ))
        conn.execute(text(
            "ALTER TABLE portal_catalog_products ALTER COLUMN selling_price DROP DEFAULT"
        ))


def _migrate_v16_price_history_fixes_postgres() -> None:
    """Make selling_price nullable in portal_product_prices."""
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE portal_product_prices ALTER COLUMN selling_price DROP NOT NULL"
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
        catalog_lookup,
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
        vendor_order_line,
        vendor_order_note,
        vendor_receipt_line,
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
    _migrate_v14_catalog_lookups_postgres()
    _migrate_v15_addon_products_and_catalog_fixes_postgres()
    _migrate_v16_price_history_fixes_postgres()
    _migrate_v17_addon_link_unique_constraint_postgres()
    _migrate_v18_vendor_order_placed_status_postgres()
    _migrate_v19_vendor_receipt_lines_postgres()
    _migrate_v20_vendor_order_normalization_postgres()
    _migrate_v21_remove_procured_status_postgres()
    _migrate_v22_sub_order_no_postgres()
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


def _migrate_v17_addon_link_unique_constraint_postgres() -> None:
    """Add unique constraint on (catalog_product_id, addon_product_id) for portal_catalog_product_addons."""
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        # Remove duplicate links keeping only the lowest id per pair
        conn.execute(text("""
            DELETE FROM portal_catalog_product_addons
            WHERE id NOT IN (
                SELECT MIN(id)
                FROM portal_catalog_product_addons
                GROUP BY catalog_product_id, addon_product_id
            )
        """))
        conn.execute(text("""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'uq_catalog_addon_link'
                ) THEN
                    ALTER TABLE portal_catalog_product_addons
                    ADD CONSTRAINT uq_catalog_addon_link
                    UNIQUE (catalog_product_id, addon_product_id);
                END IF;
            END$$
        """))


def _migrate_v19_vendor_receipt_lines_postgres() -> None:
    """Create portal_vendor_receipt_lines table — one row per item per partial shipment."""
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS portal_vendor_receipt_lines (
                id                  SERIAL PRIMARY KEY,
                vendor_bill_id      INTEGER REFERENCES portal_vendor_bills(id) ON DELETE SET NULL,
                vendor_order_id     INTEGER REFERENCES portal_vendor_orders(id) ON DELETE SET NULL,
                vendor_id           INTEGER REFERENCES portal_vendors(id) ON DELETE SET NULL,
                catalog_product_id  INTEGER REFERENCES portal_catalog_products(id) ON DELETE SET NULL,
                product_name        VARCHAR(500),
                order_line_id       VARCHAR(64),
                qty_received        INTEGER NOT NULL DEFAULT 0,
                qty_billed          INTEGER NOT NULL DEFAULT 0,
                order_price         NUMERIC(14,4),
                billed_price        NUMERIC(14,4),
                qty_discrepancy     INTEGER,
                price_discrepancy   NUMERIC(14,4),
                receipt_date        TIMESTAMPTZ,
                notes               TEXT,
                created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        # Indexes for common queries
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_vrl_vendor_order_id
                ON portal_vendor_receipt_lines(vendor_order_id)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_vrl_catalog_product_id
                ON portal_vendor_receipt_lines(catalog_product_id)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_vrl_vendor_id
                ON portal_vendor_receipt_lines(vendor_id)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_vrl_receipt_date
                ON portal_vendor_receipt_lines(receipt_date)
        """))


def _migrate_v18_vendor_order_placed_status_postgres() -> None:
    """Rename vendor order status 'open' → 'placed' to clarify lifecycle."""
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE portal_vendor_orders
            SET status = 'placed'
            WHERE status = 'open'
        """))


def _migrate_v20_vendor_order_normalization_postgres() -> None:
    """Normalise vendor orders:
    - Create portal_vendor_order_lines (replaces JSONB items blob)
    - Create portal_vendor_order_notes (per-stage notes thread)
    - Migrate existing JSONB items → rows
    - Migrate existing order-level notes → notes rows (stage='placed')
    - Drop legacy columns: items, notes, bill_number, bill_amount, bill_key, bill_uploaded_at
    """
    if engine.dialect.name != "postgresql":
        return

    with engine.begin() as conn:
        # ── 1. Create portal_vendor_order_lines ──────────────────────────────
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS portal_vendor_order_lines (
                id                  SERIAL PRIMARY KEY,
                line_id             VARCHAR(64)  NOT NULL UNIQUE,
                vendor_order_id     INTEGER      NOT NULL
                    REFERENCES portal_vendor_orders(id) ON DELETE CASCADE,
                catalog_product_id  INTEGER
                    REFERENCES portal_catalog_products(id) ON DELETE SET NULL,
                product_name        VARCHAR(500),
                our_product_id      VARCHAR(120),
                qty_ordered         INTEGER      NOT NULL DEFAULT 0,
                qty_received        INTEGER      NOT NULL DEFAULT 0,
                qty_billed          INTEGER      NOT NULL DEFAULT 0,
                unit_price          NUMERIC(14,4) NOT NULL DEFAULT 0,
                billed_price        NUMERIC(14,4),
                date_ordered        TIMESTAMPTZ,
                date_received       TIMESTAMPTZ,
                notes               TEXT,
                created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_vol_vendor_order_id
                ON portal_vendor_order_lines(vendor_order_id)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_vol_catalog_product_id
                ON portal_vendor_order_lines(catalog_product_id)
        """))

        # ── 2. Create portal_vendor_order_notes ──────────────────────────────
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS portal_vendor_order_notes (
                id               SERIAL PRIMARY KEY,
                vendor_order_id  INTEGER NOT NULL
                    REFERENCES portal_vendor_orders(id) ON DELETE CASCADE,
                stage            VARCHAR(20) NOT NULL DEFAULT 'placed',
                body             TEXT        NOT NULL,
                created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_von_vendor_order_id
                ON portal_vendor_order_notes(vendor_order_id)
        """))

    # ── 3. Migrate JSONB items → rows (Python loop for JSONB parsing) ────────
    import json as _json
    from sqlalchemy import text as _text

    with engine.begin() as conn:
        # Check if the items column still exists (idempotency guard)
        items_col_exists = conn.execute(_text("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'portal_vendor_orders' AND column_name = 'items'
        """)).fetchone()

        if items_col_exists:
            rows = conn.execute(_text("""
                SELECT vo.id, vo.items, vo.notes
                FROM portal_vendor_orders vo
                WHERE vo.items IS NOT NULL
                  AND vo.items::text != '[]'
                  AND vo.items::text != 'null'
                  AND NOT EXISTS (
                      SELECT 1 FROM portal_vendor_order_lines vol
                      WHERE vol.vendor_order_id = vo.id
                  )
            """)).fetchall()

            for row in rows:
                order_id, items_raw, order_notes = row[0], row[1], row[2]
                if isinstance(items_raw, str):
                    try:
                        items = _json.loads(items_raw)
                    except Exception:
                        items = []
                elif isinstance(items_raw, list):
                    items = items_raw
                else:
                    items = []

                for item in items:
                    lid = item.get("line_id") or __import__("uuid").uuid4().hex
                    conn.execute(_text("""
                        INSERT INTO portal_vendor_order_lines
                            (line_id, vendor_order_id, catalog_product_id, product_name,
                             our_product_id, qty_ordered, qty_received, qty_billed,
                             unit_price, billed_price, date_ordered, notes)
                        VALUES
                            (:line_id, :order_id, :cid, :pname,
                             :our_id, :qty_ord, :qty_rcv, :qty_billed,
                             :unit_price, :billed_price, :date_ord, :item_notes)
                        ON CONFLICT (line_id) DO NOTHING
                    """), {
                        "line_id": lid,
                        "order_id": order_id,
                        "cid": item.get("catalog_product_id"),
                        "pname": item.get("product_name"),
                        "our_id": item.get("product_name"),
                        "qty_ord": int(item.get("qty_ordered") or 0),
                        "qty_rcv": int(item.get("qty_received") or 0),
                        "qty_billed": int(item.get("qty_billed") or 0),
                        "unit_price": float(item.get("unit_price") or 0),
                        "billed_price": float(item.get("billed_price")) if item.get("billed_price") else None,
                        "date_ord": item.get("date_ordered"),
                        "item_notes": item.get("notes"),
                    })

                # Migrate order-level notes → notes table (stage='placed')
                if order_notes and order_notes.strip():
                    conn.execute(_text("""
                        INSERT INTO portal_vendor_order_notes (vendor_order_id, stage, body)
                        SELECT :order_id, 'placed', :body
                        WHERE NOT EXISTS (
                            SELECT 1 FROM portal_vendor_order_notes
                            WHERE vendor_order_id = :order_id AND stage = 'placed'
                              AND body = :body
                        )
                    """), {"order_id": order_id, "body": order_notes.strip()})

    # ── 4. Drop legacy columns ────────────────────────────────────────────────
    with engine.begin() as conn:
        for col in ("items", "notes", "bill_number", "bill_amount", "bill_key", "bill_uploaded_at"):
            conn.execute(_text(
                f"ALTER TABLE portal_vendor_orders DROP COLUMN IF EXISTS {col}"
            ))


def _migrate_v21_remove_procured_status_postgres() -> None:
    """Move all 'procured' and 'closed' vendor orders back to 'placed'."""
    if engine.dialect.name != "postgresql":
        return
    from sqlalchemy import text as _text
    with engine.begin() as conn:
        conn.execute(_text("""
            UPDATE portal_vendor_orders
            SET status = 'placed'
            WHERE status IN ('procured', 'closed')
        """))


def _migrate_v22_sub_order_no_postgres() -> None:
    """Add sub_order_no column to portal_vendor_order_lines (idempotent)."""
    if engine.dialect.name != "postgresql":
        return
    from sqlalchemy import text as _text
    with engine.begin() as conn:
        col_exists = conn.execute(_text("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'portal_vendor_order_lines'
              AND column_name = 'sub_order_no'
        """)).fetchone()
        if not col_exists:
            conn.execute(_text("""
                ALTER TABLE portal_vendor_order_lines
                ADD COLUMN sub_order_no INTEGER NOT NULL DEFAULT 1
            """))
            # Back-fill: assign sequential sub_order_no per vendor_order_id, grouped by date_ordered day
            conn.execute(_text("""
                UPDATE portal_vendor_order_lines vol
                SET sub_order_no = sub.rn
                FROM (
                    SELECT id,
                           DENSE_RANK() OVER (
                               PARTITION BY vendor_order_id
                               ORDER BY DATE(date_ordered AT TIME ZONE 'UTC'), id
                           ) AS rn
                    FROM portal_vendor_order_lines
                ) sub
                WHERE vol.id = sub.id
            """))


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
