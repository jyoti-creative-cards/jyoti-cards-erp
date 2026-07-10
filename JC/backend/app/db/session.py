from __future__ import annotations

import re
from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.config import get_settings

Base = declarative_base()

_settings = get_settings()
_db_url = _settings.database_url.strip()
_is_sqlite = _db_url.lower().startswith("sqlite:")


def _supabase_to_pooler(url: str) -> str:
    m = re.match(
        r"postgresql(?:\+psycopg2)?://postgres:([^@]+)@db\.([a-z0-9]+)\.supabase\.co:5432/(.+)",
        url,
    )
    if not m:
        return url
    pwd, project, dbname = m.group(1), m.group(2), m.group(3)
    return f"postgresql://postgres.{project}:{pwd}@aws-1-ap-southeast-1.pooler.supabase.com:6543/{dbname}"


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


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from app.models import (  # noqa: F401
        ActivityLog, AddonProduct, CatalogAddonLink, CatalogAlternative, CatalogLookup,
        CatalogProduct, City, Customer, EntityHistory, PriceHistory, Route, Staff, Vendor,
        VendorOrder, VendorOrderLine, VendorOrderPlacement, VendorOpenLine,
        CustomerOrder, CustomerOrderLine, CustomerOrderPlacement, CustomerOpenLine,
        CustomerBill, CustomerBillLine, BillSeries, FreightAgent, FreightLedgerEntry, Expense,
        CustomerArAccount, ArLedgerEntry,
        StockBalance, StockLedger, StockReceipt, StockReceiptLine,
        DebitNote, VendorApAccount, ApLedgerEntry, ManualLoss,
    )

    Base.metadata.create_all(bind=engine)
    _migrate_deleted_at()
    _migrate_vendor_orders_stock()
    _migrate_finance()
    _migrate_debit_note_direction()
    _migrate_orders_v2()
    _migrate_orders_v3_reasons()
    _migrate_customer_orders_v3()
    _migrate_customer_orders_v5_fix()
    _migrate_documents_v4()
    _migrate_indexes()
    with engine.begin() as conn:
        conn.execute(text("SELECT 1"))


def _migrate_debit_note_direction() -> None:
    """Add direction column and backfill from signed qty/amount."""
    stmts = [
        "ALTER TABLE jc_debit_notes ADD COLUMN IF NOT EXISTS direction VARCHAR(20)",
        """
        UPDATE jc_debit_notes
        SET direction = CASE
            WHEN note_type = 'item' AND COALESCE(quantity, 0) < 0 THEN 'extra'
            WHEN note_type = 'item' THEN 'short'
            WHEN note_type = 'value' AND amount < 0 THEN 'over'
            WHEN note_type = 'value' THEN 'under'
            ELSE direction
        END
        WHERE direction IS NULL
        """,
    ]
    with engine.begin() as conn:
        for stmt in stmts:
            try:
                conn.execute(text(stmt))
            except Exception:
                pass


def _migrate_vendor_orders_stock() -> None:
    stmts = [
        "ALTER TABLE jc_vendor_orders ADD COLUMN IF NOT EXISTS bucket VARCHAR(20) NOT NULL DEFAULT 'placed'",
        "ALTER TABLE jc_vendor_order_lines ADD COLUMN IF NOT EXISTS quantity_remaining INTEGER",
        "ALTER TABLE jc_vendor_order_lines ADD COLUMN IF NOT EXISTS quantity_billed INTEGER",
        "ALTER TABLE jc_vendor_order_lines ADD COLUMN IF NOT EXISTS billed_amount NUMERIC(14,2)",
        "UPDATE jc_vendor_order_lines SET quantity_remaining = quantity WHERE quantity_remaining IS DISTINCT FROM quantity",
    ]
    with engine.begin() as conn:
        for stmt in stmts:
            try:
                conn.execute(text(stmt))
            except Exception:
                pass


def _migrate_finance() -> None:
    """Backfill AP bill entries + add total_billed_amount column."""
    stmts = [
        "ALTER TABLE jc_stock_receipts ADD COLUMN IF NOT EXISTS total_billed_amount NUMERIC(14,2)",
    ]
    with engine.begin() as conn:
        for stmt in stmts:
            try:
                conn.execute(text(stmt))
            except Exception:
                pass

    from app.models.stock import StockReceipt, StockReceiptLine
    from app.models.accounts_payable import ApLedgerEntry
    from app.services.ap_ledger import get_or_create_ap_account, receipt_bill_amount
    from decimal import Decimal

    db = SessionLocal()
    try:
        existing_receipt_ids = {
            r[0] for r in db.query(ApLedgerEntry.receipt_id).filter(ApLedgerEntry.entry_type == "bill", ApLedgerEntry.receipt_id.isnot(None)).all()
        }
        receipts = db.query(StockReceipt).order_by(StockReceipt.id.asc()).all()
        for receipt in receipts:
            if receipt.id in existing_receipt_ids:
                continue
            bill_total = receipt_bill_amount(db, receipt.id)
            if bill_total <= 0:
                continue
            get_or_create_ap_account(db, receipt.vendor_id)
            db.add(
                ApLedgerEntry(
                    vendor_id=receipt.vendor_id,
                    entry_type="bill",
                    amount=bill_total.quantize(Decimal("0.01")),
                    receipt_id=receipt.id,
                    description=f"Bill {receipt.bill_number or receipt.id} — ₹{bill_total}",
                    created_by_type=receipt.received_by_type,
                    created_by_id=receipt.received_by_id,
                    created_by_name=receipt.received_by_name,
                    created_at=receipt.received_at,
                )
            )
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()

    # Backfill debit-note ledger entries missing from AP
    db = SessionLocal()
    try:
        from app.models.debit_note import DebitNote
        from app.models.accounts_payable import ApLedgerEntry
        from app.services.ap_ledger import get_or_create_ap_account, debit_note_payable_effect
        from decimal import Decimal

        linked = {
            r[0]
            for r in db.query(ApLedgerEntry.debit_note_id)
            .filter(ApLedgerEntry.entry_type == "debit_note", ApLedgerEntry.debit_note_id.isnot(None))
            .all()
        }
        for note in db.query(DebitNote).order_by(DebitNote.id.asc()).all():
            if note.id in linked:
                continue
            get_or_create_ap_account(db, note.vendor_id)
            effect = debit_note_payable_effect(note.amount, note.note_type)
            db.add(
                ApLedgerEntry(
                    vendor_id=note.vendor_id,
                    entry_type="debit_note",
                    amount=effect,
                    receipt_id=note.receipt_id,
                    debit_note_id=note.id,
                    description=f"Debit note — ₹{note.amount} ({note.direction or ''})",
                    created_by_type=note.created_by_type,
                    created_by_id=note.created_by_id,
                    created_by_name=note.created_by_name,
                    created_at=note.created_at,
                )
            )
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def _migrate_orders_v2() -> None:
    stmts = [
        "ALTER TABLE jc_vendor_order_placements ADD COLUMN IF NOT EXISTS closed_at TIMESTAMPTZ",
        "ALTER TABLE jc_stock_balances ADD COLUMN IF NOT EXISTS low_stock_threshold INTEGER NOT NULL DEFAULT 5",
    ]
    with engine.begin() as conn:
        for stmt in stmts:
            try:
                conn.execute(text(stmt))
            except Exception:
                pass
    from app.models.vendor import Vendor
    from app.models.vendor_open_line import VendorOpenLine
    from app.services.order_summary import placed_qty_by_product, received_qty_by_product
    from app.services.open_lines import add_to_open

    db = SessionLocal()
    try:
        if db.query(VendorOpenLine).count() > 0:
            return
        vendors = db.query(Vendor).filter(Vendor.is_active.is_(True), Vendor.deleted_at.is_(None)).all()
        for v in vendors:
            placed = placed_qty_by_product(db, v.id)
            received = received_qty_by_product(db, v.id)
            for cat_id, pq in placed.items():
                pending = max(0, pq - received.get(cat_id, 0))
                if pending > 0:
                    add_to_open(db, v.id, [(cat_id, pending)])
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def _migrate_orders_v3_reasons() -> None:
    stmts = [
        "ALTER TABLE jc_vendor_order_placements ADD COLUMN IF NOT EXISTS cancel_reason TEXT",
        "ALTER TABLE jc_vendor_order_placements ADD COLUMN IF NOT EXISTS close_reason TEXT",
        "ALTER TABLE jc_vendor_open_lines ADD COLUMN IF NOT EXISTS cancel_reason TEXT",
        "ALTER TABLE jc_vendor_open_lines ADD COLUMN IF NOT EXISTS close_reason TEXT",
    ]
    with engine.begin() as conn:
        for stmt in stmts:
            try:
                conn.execute(text(stmt))
            except Exception:
                pass


def _migrate_customer_orders_v3() -> None:
    """Rebuild flat jc_customer_orders into bucket + placements model."""
    with engine.begin() as conn:
        for stmt in [
            "ALTER TABLE jc_customer_orders ADD COLUMN IF NOT EXISTS bucket VARCHAR(20)",
            "ALTER TABLE jc_customer_orders ADD COLUMN IF NOT EXISTS is_open BOOLEAN",
        ]:
            try:
                conn.execute(text(stmt))
            except Exception:
                pass

    db = SessionLocal()
    try:
        from sqlalchemy import inspect
        insp = inspect(engine)
        cols = {c["name"] for c in insp.get_columns("jc_customer_orders")} if insp.has_table("jc_customer_orders") else set()
        if "catalog_product_id" not in cols:
            return

        from app.models.customer import Customer
        from app.models.customer_order import CustomerOrder, CustomerOrderLine, CustomerOrderPlacement, CustomerOpenLine
        from app.services.customer_order_flow import add_to_customer_open, get_or_create_customer_order

        legacy_rows = db.execute(text(
            "SELECT id, customer_id, catalog_product_id, our_product_id, quantity, unit_price, "
            "status, customer_notes, created_at FROM jc_customer_orders WHERE catalog_product_id IS NOT NULL"
        )).fetchall()

        for row in legacy_rows:
            cid = int(row.customer_id)
            received = get_or_create_customer_order(db, cid, "received", "received")
            placement = CustomerOrderPlacement(
                customer_order_id=received.id,
                status="received",
                customer_notes=row.customer_notes,
                placed_at=row.created_at,
            )
            db.add(placement)
            db.flush()
            db.add(
                CustomerOrderLine(
                    placement_id=placement.id,
                    catalog_product_id=int(row.catalog_product_id),
                    our_product_id=str(row.our_product_id),
                    quantity=int(row.quantity),
                    quantity_billed=0,
                    unit_price=row.unit_price,
                    status="active",
                )
            )
            add_to_customer_open(db, cid, [(int(row.catalog_product_id), int(row.quantity), row.unit_price)])

        db.commit()

        with engine.begin() as conn:
            conn.execute(text("DELETE FROM jc_customer_orders WHERE catalog_product_id IS NOT NULL"))
            for stmt in [
                "ALTER TABLE jc_customer_orders DROP COLUMN IF EXISTS catalog_product_id",
                "ALTER TABLE jc_customer_orders DROP COLUMN IF EXISTS our_product_id",
                "ALTER TABLE jc_customer_orders DROP COLUMN IF EXISTS quantity",
                "ALTER TABLE jc_customer_orders DROP COLUMN IF EXISTS unit_price",
                "ALTER TABLE jc_customer_orders DROP COLUMN IF EXISTS customer_notes",
                "UPDATE jc_customer_orders SET bucket = COALESCE(bucket, 'received'), is_open = COALESCE(is_open, true)",
            ]:
                try:
                    conn.execute(text(stmt))
                except Exception:
                    pass
    except Exception:
        db.rollback()
    finally:
        db.close()


def _migrate_customer_orders_v5_fix() -> None:
    """Drop legacy flat-order columns left on jc_customer_orders after v3 migration."""
    from sqlalchemy import inspect

    insp = inspect(engine)
    if not insp.has_table("jc_customer_orders"):
        return
    cols = {c["name"] for c in insp.get_columns("jc_customer_orders")}
    if "catalog_product_id" not in cols:
        return

    db = SessionLocal()
    try:
        from app.models.customer_order import CustomerOrderLine, CustomerOrderPlacement
        from app.services.customer_order_flow import add_to_customer_open, get_or_create_customer_order

        legacy_rows = db.execute(text(
            "SELECT id, customer_id, catalog_product_id, our_product_id, quantity, unit_price, "
            "status, customer_notes, created_at FROM jc_customer_orders WHERE catalog_product_id IS NOT NULL"
        )).fetchall()

        for row in legacy_rows:
            cid = int(row.customer_id)
            received = get_or_create_customer_order(db, cid, "received", "received")
            placement = CustomerOrderPlacement(
                customer_order_id=received.id,
                status="received",
                customer_notes=row.customer_notes,
                placed_at=row.created_at,
            )
            db.add(placement)
            db.flush()
            db.add(
                CustomerOrderLine(
                    placement_id=placement.id,
                    catalog_product_id=int(row.catalog_product_id),
                    our_product_id=str(row.our_product_id),
                    quantity=int(row.quantity),
                    quantity_billed=0,
                    unit_price=row.unit_price,
                    status="active",
                )
            )
            add_to_customer_open(db, cid, [(int(row.catalog_product_id), int(row.quantity), row.unit_price)])
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()

    legacy_cols = [
        "catalog_product_id", "our_product_id", "quantity", "unit_price", "customer_notes",
    ]
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM jc_customer_orders WHERE catalog_product_id IS NOT NULL"))
        for col in legacy_cols:
            try:
                conn.execute(text(f"ALTER TABLE jc_customer_orders DROP COLUMN IF EXISTS {col}"))
            except Exception:
                try:
                    conn.execute(text(f"ALTER TABLE jc_customer_orders ALTER COLUMN {col} DROP NOT NULL"))
                except Exception:
                    pass
        try:
            conn.execute(text(
                "UPDATE jc_customer_orders SET bucket = COALESCE(bucket, 'received'), "
                "is_open = COALESCE(is_open, true) WHERE bucket IS NULL OR is_open IS NULL"
            ))
        except Exception:
            pass


def _migrate_documents_v4() -> None:
    cols = {
        "jc_customer_order_placements": "document_key VARCHAR(500)",
        "jc_customer_order_lines": "addons_json JSONB",
        "jc_customer_bills": "document_key VARCHAR(500)",
        "jc_vendor_order_placements": "document_key VARCHAR(500)",
        "jc_stock_receipts": "receipt_document_key VARCHAR(500)",
    }
    with engine.begin() as conn:
        for table, coldef in cols.items():
            try:
                if _is_sqlite:
                    colname = coldef.split()[0]
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {colname} TEXT"))
                else:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {coldef}"))
            except Exception:
                pass


def _migrate_indexes() -> None:
    stmts = [
        "CREATE INDEX IF NOT EXISTS ix_jc_entity_history_lookup ON jc_entity_history (entity_type, entity_id)",
        "CREATE INDEX IF NOT EXISTS ix_jc_activity_entity ON jc_activity_logs (entity_type, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_jc_vendor_orders_vendor_open ON jc_vendor_orders (vendor_id, bucket, is_open)",
    ]
    if not _is_sqlite:
        stmts.append(
            "DROP INDEX IF EXISTS uq_jc_vendor_orders_one_open"
        )
        stmts.append(
            "DROP INDEX IF EXISTS ix_jc_vendor_orders_vendor_open"
        )
        stmts.extend([
            "CREATE INDEX IF NOT EXISTS ix_jc_vendor_orders_vendor_open ON jc_vendor_orders (vendor_id, bucket, is_open)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_jc_vendor_orders_one_open "
            "ON jc_vendor_orders (vendor_id, bucket) WHERE is_open = true",
        ])
    with engine.begin() as conn:
        for stmt in stmts:
            try:
                conn.execute(text(stmt))
            except Exception:
                pass


def _migrate_deleted_at() -> None:
    cols = {
        "jc_routes": "deleted_at TIMESTAMPTZ",
        "jc_cities": "deleted_at TIMESTAMPTZ",
        "jc_customers": "deleted_at TIMESTAMPTZ",
        "jc_vendors": "deleted_at TIMESTAMPTZ",
        "jc_catalog_products": "deleted_at TIMESTAMPTZ",
        "jc_addon_products": "deleted_at TIMESTAMPTZ",
        "jc_staff": "deleted_at TIMESTAMPTZ",
    }
    with engine.begin() as conn:
        for table, coldef in cols.items():
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {coldef}"))
            except Exception:
                pass
