from __future__ import annotations

import logging
import re
from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.config import get_settings

log = logging.getLogger(__name__)

Base = declarative_base()

_DB_READY = False


def is_db_ready() -> bool:
    return _DB_READY


def _exec_sql(conn, stmt: str, *, critical: bool = False, params: dict | None = None) -> None:
    """Run migration SQL. Critical money migrations raise; schema ones log."""
    try:
        if params:
            conn.execute(text(stmt), params)
        else:
            conn.execute(text(stmt))
    except Exception:
        if critical:
            log.exception("Critical migration failed: %s", stmt[:160].replace("\n", " "))
            raise
        log.warning("Migration skipped: %s", stmt[:160].replace("\n", " "), exc_info=True)

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
    global _DB_READY
    from app.models import (  # noqa: F401
        ActivityLog, AddonProduct, CatalogAddonLink, CatalogAlternative, CatalogLookup,
        CatalogProduct, City, Customer, EntityHistory, PriceHistory, Route, Staff, Vendor,
        VendorOrder, VendorOrderLine, VendorOrderPlacement, VendorOpenLine,
        CustomerOrder, CustomerOrderLine, CustomerOrderPlacement, CustomerOpenLine,
        CustomerBill, CustomerBillLine, BillSeries, FreightAgent, FreightLedgerEntry, Expense,
        CustomerArAccount, ArLedgerEntry, PaymentMode,
        StockBalance, StockLedger, StockReceipt, StockReceiptLine,
        DebitNote, VendorApAccount, ApLedgerEntry, ManualLoss,
        CustomerReturn, CustomerReturnLine,
    )

    try:
        Base.metadata.create_all(bind=engine)
        _migrate_deleted_at()
        _migrate_vendor_orders_stock()
        _migrate_finance()
        _migrate_opening_balances()
        _migrate_debit_note_direction()
        _migrate_orders_v2()
        _migrate_orders_v3_reasons()
        _migrate_customer_orders_v3()
        _migrate_customer_orders_v5_fix()
        _migrate_documents_v4()
        _migrate_indexes()
        _migrate_catalog_year_unique()
        _migrate_vendor_receive_split()
        _migrate_customer_returns()
        _migrate_customer_additional_details()
        _migrate_ledger_reverses()
        _migrate_signed_ledgers()
        _migrate_money_uniques()
        _migrate_vendor_city_optional()
        _migrate_payment_modes()
        _migrate_freight_docs()
        _migrate_bill_cancel()
        _migrate_bill_date()
        _migrate_bill_transport()
        _migrate_vendor_billing_terms()
        _migrate_vendor_billing_v2()
        with engine.begin() as conn:
            conn.execute(text("SELECT 1"))
        _DB_READY = True
        log.info("init_db complete — DB ready")
    except Exception:
        _DB_READY = False
        log.exception("init_db FAILED")
        raise


def _migrate_vendor_city_optional() -> None:
    """Vendor city is optional — only customers need city for route collection."""
    with engine.begin() as conn:
        try:
            conn.execute(text("ALTER TABLE jc_vendors ALTER COLUMN city_id DROP NOT NULL"))
        except Exception:
            pass


def _migrate_bill_transport() -> None:
    """Mode of transport on customer bills. Backfill from freight agent."""
    stmts = [
        "ALTER TABLE jc_customer_bills ADD COLUMN IF NOT EXISTS transport_mode VARCHAR(20)",
        "ALTER TABLE jc_customer_bills ADD COLUMN IF NOT EXISTS transport_receipt_number VARCHAR(120)",
        """
        UPDATE jc_customer_bills
        SET transport_mode = 'bus'
        WHERE freight_agent_id IS NOT NULL AND transport_mode IS NULL
        """,
    ]
    for stmt in stmts:
        try:
            with engine.begin() as conn:
                if _is_sqlite:
                    stmt = stmt.replace(" ADD COLUMN IF NOT EXISTS ", " ADD COLUMN ")
                conn.execute(text(stmt))
        except Exception:
            log.warning("Migration step skipped", exc_info=True)


def _migrate_vendor_billing_terms() -> None:
    """Typed billing columns replacing billing_context JSON."""
    stmts = [
        "ALTER TABLE jc_vendors ADD COLUMN IF NOT EXISTS billing_pct NUMERIC(5,2) NOT NULL DEFAULT 100",
        "ALTER TABLE jc_vendors ADD COLUMN IF NOT EXISTS additional_charge NUMERIC(10,2) NOT NULL DEFAULT 100",
        "ALTER TABLE jc_vendors ADD COLUMN IF NOT EXISTS additional_charge_label VARCHAR(50) NOT NULL DEFAULT 'Additional charge'",
        "ALTER TABLE jc_vendors ADD COLUMN IF NOT EXISTS discount_pct NUMERIC(5,2) NOT NULL DEFAULT 0",
        "ALTER TABLE jc_vendors ADD COLUMN IF NOT EXISTS gst_included BOOLEAN NOT NULL DEFAULT TRUE",
        "ALTER TABLE jc_vendors ADD COLUMN IF NOT EXISTS gst_rate_pct NUMERIC(5,2) NOT NULL DEFAULT 18",
        "ALTER TABLE jc_vendors ADD COLUMN IF NOT EXISTS billing_notes TEXT",
        "UPDATE jc_vendors SET billing_pct = 50, additional_charge = 100, additional_charge_label = 'Packing charges', discount_pct = 0, gst_included = TRUE, gst_rate_pct = 18 WHERE business_name = 'VEE PEE CREATIONS'",
        "UPDATE jc_vendors SET billing_pct = 100, additional_charge = 0, additional_charge_label = 'Additional charge', discount_pct = 0, gst_included = TRUE, gst_rate_pct = 18 WHERE business_name = 'SINGHAL PRINT & GRAPHICS'",
        "UPDATE jc_vendors SET billing_pct = 100, additional_charge = 100, additional_charge_label = 'Freight charges', discount_pct = 6, gst_included = TRUE, gst_rate_pct = 18 WHERE business_name = 'GARG ENTERPRISES'",
    ]
    for stmt in stmts:
        try:
            with engine.begin() as conn:
                s = stmt.replace(" ADD COLUMN IF NOT EXISTS ", " ADD COLUMN ") if _is_sqlite else stmt
                conn.execute(text(s))
        except Exception:
            log.warning("Migration step skipped", exc_info=True)


def _migrate_vendor_billing_v2() -> None:
    """One-receipt-per-bill: bill_status + frozen expected amounts + debit note source."""
    stmts = [
        "ALTER TABLE jc_stock_receipts ADD COLUMN IF NOT EXISTS bill_status VARCHAR(20) NOT NULL DEFAULT 'pending_bill'",
        "ALTER TABLE jc_stock_receipts ADD COLUMN IF NOT EXISTS expected_bill_amount NUMERIC(14,2)",
        "ALTER TABLE jc_stock_receipts ADD COLUMN IF NOT EXISTS expected_extra_cash NUMERIC(14,2)",
        "ALTER TABLE jc_stock_receipts ADD COLUMN IF NOT EXISTS billed_at TIMESTAMPTZ",
        "ALTER TABLE jc_debit_notes ADD COLUMN IF NOT EXISTS source VARCHAR(10) NOT NULL DEFAULT 'manual'",
        "UPDATE jc_stock_receipts SET bill_status = 'billed', billed_at = received_at WHERE receipt_type = 'vendor_bill'",
    ]
    for stmt in stmts:
        try:
            with engine.begin() as conn:
                s = stmt.replace(" ADD COLUMN IF NOT EXISTS ", " ADD COLUMN ") if _is_sqlite else stmt
                conn.execute(text(s))
        except Exception:
            log.warning("Migration step skipped", exc_info=True)


def _migrate_bill_date() -> None:
    """Invoice date ≠ created_at. Backfill invoice day from the old stamped created_at."""
    with engine.begin() as conn:
        if _is_sqlite:
            _exec_sql(conn, "ALTER TABLE jc_customer_bills ADD COLUMN bill_date DATE")
            _exec_sql(conn, "UPDATE jc_customer_bills SET bill_date = date(created_at) WHERE bill_date IS NULL")
        else:
            _exec_sql(conn, "ALTER TABLE jc_customer_bills ADD COLUMN IF NOT EXISTS bill_date DATE")
            _exec_sql(
                conn,
                """
                UPDATE jc_customer_bills
                SET bill_date = ((created_at AT TIME ZONE 'UTC') AT TIME ZONE 'Asia/Kolkata')::date
                WHERE bill_date IS NULL AND created_at IS NOT NULL
                """,
            )


def _migrate_bill_cancel() -> None:
    for stmt in (
        "ALTER TABLE jc_customer_bills ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMPTZ",
        "ALTER TABLE jc_customer_bills ADD COLUMN IF NOT EXISTS cancel_reason TEXT",
    ):
        try:
            with engine.begin() as conn:
                conn.execute(text(stmt))
        except Exception:
            log.warning("Migration step skipped", exc_info=True)


def _migrate_freight_docs() -> None:
    # Each statement in its own transaction — Postgres aborts the whole txn after one error.
    stmts = [
        "ALTER TABLE jc_freight_ledger_entries ADD COLUMN IF NOT EXISTS payment_receipt_key VARCHAR(500)",
        "ALTER TABLE jc_freight_ledger_entries ADD COLUMN IF NOT EXISTS document_key VARCHAR(500)",
        "ALTER TABLE jc_customer_bills ADD COLUMN IF NOT EXISTS freight_picked_at TIMESTAMPTZ",
        "ALTER TABLE jc_customer_bills ADD COLUMN IF NOT EXISTS freight_picked_by VARCHAR(200)",
        "ALTER TABLE jc_customer_bills ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMPTZ",
        "ALTER TABLE jc_customer_bills ADD COLUMN IF NOT EXISTS cancel_reason TEXT",
        # Existing charged bills were already "picked" under old flow
        """
        UPDATE jc_customer_bills b
        SET freight_picked_at = e.created_at,
            freight_picked_by = COALESCE(e.created_by_name, 'migration')
        FROM jc_freight_ledger_entries e
        WHERE e.customer_bill_id = b.id
          AND e.entry_type = 'charge'
          AND b.freight_picked_at IS NULL
        """,
    ]
    for stmt in stmts:
        try:
            with engine.begin() as conn:
                conn.execute(text(stmt))
        except Exception:
            log.warning("Migration step skipped", exc_info=True)


def _migrate_payment_modes() -> None:
    """Payment modes setup + AR payment_mode column."""
    with engine.begin() as conn:
        if _is_sqlite:
            _exec_sql(conn, "ALTER TABLE jc_ar_ledger_entries ADD COLUMN payment_mode VARCHAR(80)", critical=False)
        else:
            _exec_sql(
                conn,
                "ALTER TABLE jc_ar_ledger_entries ADD COLUMN IF NOT EXISTS payment_mode VARCHAR(80)",
                critical=False,
            )


def _migrate_ledger_reverses() -> None:
    """Columns for reverse/void payment + receipt-edit adjustments."""
    with engine.begin() as conn:
        if _is_sqlite:
            for table in ("jc_ar_ledger_entries", "jc_ap_ledger_entries"):
                _exec_sql(conn, f"ALTER TABLE {table} ADD COLUMN reverses_entry_id INTEGER", critical=False)
        else:
            _exec_sql(
                conn,
                "ALTER TABLE jc_ar_ledger_entries ADD COLUMN IF NOT EXISTS reverses_entry_id INTEGER",
                critical=True,
            )
            _exec_sql(
                conn,
                "ALTER TABLE jc_ap_ledger_entries ADD COLUMN IF NOT EXISTS reverses_entry_id INTEGER",
                critical=True,
            )
        _exec_sql(
            conn,
            "CREATE INDEX IF NOT EXISTS ix_ar_reverses_entry_id ON jc_ar_ledger_entries (reverses_entry_id)",
            critical=False,
        )
        _exec_sql(
            conn,
            "CREATE INDEX IF NOT EXISTS ix_ap_reverses_entry_id ON jc_ap_ledger_entries (reverses_entry_id)",
            critical=False,
        )


def _migrate_signed_ledgers() -> None:
    """One convention: amount is signed. + increases outstanding, − decreases.

    Idempotent: only flips still-positive reducing entries (legacy unsigned storage).
    Then reconciles freight balance_due from ledger; seeds opening if ledger empty.
    """
    with engine.begin() as conn:
        _exec_sql(
            conn,
            """
            UPDATE jc_ar_ledger_entries
            SET amount = -amount
            WHERE entry_type IN ('payment', 'credit_note') AND amount > 0
            """,
            critical=True,
        )
        _exec_sql(
            conn,
            """
            UPDATE jc_freight_ledger_entries
            SET amount = -amount
            WHERE entry_type = 'settlement' AND amount > 0
            """,
            critical=True,
        )
        _exec_sql(
            conn,
            """
            UPDATE jc_ap_ledger_entries
            SET amount = -amount
            WHERE entry_type = 'payment' AND amount > 0
            """,
            critical=True,
        )
        # Reconcile freight cache from ledger; if no rows but balance_due > 0, seed opening
        try:
            agents = conn.execute(text(
                "SELECT id, COALESCE(balance_due, 0) FROM jc_freight_agents"
            )).fetchall()
            for agent_id, bal in agents:
                ledger_sum = conn.execute(text(
                    "SELECT COALESCE(SUM(amount), 0) FROM jc_freight_ledger_entries WHERE freight_agent_id = :id"
                ), {"id": agent_id}).scalar()
                ledger_sum = ledger_sum or 0
                bal = bal or 0
                cnt = conn.execute(text(
                    "SELECT COUNT(*) FROM jc_freight_ledger_entries WHERE freight_agent_id = :id"
                ), {"id": agent_id}).scalar() or 0
                if cnt == 0 and float(bal) > 0.009:
                    conn.execute(text(
                        """
                        INSERT INTO jc_freight_ledger_entries
                          (freight_agent_id, entry_type, amount, notes, created_by_name)
                        VALUES
                          (:id, 'opening_balance', :amt, 'Migrated opening from balance_due', 'system')
                        """
                    ), {"id": agent_id, "amt": bal})
                    ledger_sum = bal
                if abs(float(ledger_sum) - float(bal)) > 0.009:
                    conn.execute(text(
                        "UPDATE jc_freight_agents SET balance_due = :amt WHERE id = :id"
                    ), {"id": agent_id, "amt": ledger_sum})
        except Exception:
            log.exception("Freight ledger reconcile during signed migration FAILED")
            raise


def _migrate_money_uniques() -> None:
    """Prevent double-post of bills / credits / openings / freight charges."""
    stmts = [
        # One AR bill row per customer bill
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_ar_bill_id
        ON jc_ar_ledger_entries (bill_id)
        WHERE entry_type = 'bill' AND bill_id IS NOT NULL
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_ar_return_id
        ON jc_ar_ledger_entries (return_id)
        WHERE entry_type = 'credit_note' AND return_id IS NOT NULL
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_ar_opening_per_customer
        ON jc_ar_ledger_entries (customer_id)
        WHERE entry_type = 'opening_balance'
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_ap_receipt_bill
        ON jc_ap_ledger_entries (receipt_id)
        WHERE entry_type = 'bill' AND receipt_id IS NOT NULL
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_ap_debit_note_id
        ON jc_ap_ledger_entries (debit_note_id)
        WHERE entry_type = 'debit_note' AND debit_note_id IS NOT NULL
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_ap_opening_per_vendor
        ON jc_ap_ledger_entries (vendor_id)
        WHERE entry_type = 'opening_balance'
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_freight_charge_bill
        ON jc_freight_ledger_entries (customer_bill_id)
        WHERE entry_type = 'charge' AND customer_bill_id IS NOT NULL
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_freight_opening_per_agent
        ON jc_freight_ledger_entries (freight_agent_id)
        WHERE entry_type = 'opening_balance'
        """,
    ]
    with engine.begin() as conn:
        for s in stmts:
            _exec_sql(conn, s, critical=True)


def _migrate_customer_additional_details() -> None:
    with engine.begin() as conn:
        try:
            conn.execute(text("ALTER TABLE jc_customers ADD COLUMN IF NOT EXISTS additional_details TEXT"))
        except Exception:
            log.warning("Migration step skipped", exc_info=True)


def _migrate_customer_returns() -> None:
    """AR ledger return_id for credit notes."""
    stmts = [
        "ALTER TABLE jc_ar_ledger_entries ADD COLUMN IF NOT EXISTS return_id INTEGER",
    ]
    with engine.begin() as conn:
        for stmt in stmts:
            try:
                conn.execute(text(stmt))
            except Exception:
                log.warning("Migration step skipped", exc_info=True)


def _migrate_vendor_receive_split() -> None:
    """Receive-then-bill: notes + received_placement_id + order receipt number."""
    stmts = [
        "ALTER TABLE jc_stock_receipts ADD COLUMN IF NOT EXISTS notes TEXT",
        "ALTER TABLE jc_stock_receipts ADD COLUMN IF NOT EXISTS received_placement_id INTEGER",
        "ALTER TABLE jc_stock_receipts ADD COLUMN IF NOT EXISTS order_receipt_number VARCHAR(120)",
    ]
    with engine.begin() as conn:
        for stmt in stmts:
            try:
                conn.execute(text(stmt))
            except Exception:
                log.warning("Migration step skipped", exc_info=True)


def _migrate_catalog_year_unique() -> None:
    """Allow same our_product_id across different year_group values.

    Never DROP the year unique index on boot — that takes an AccessExclusiveLock
    and deadlocks live traffic (admin /cities spinner, etc.).
    """
    if _is_sqlite:
        # SQLite cannot easily drop named unique constraints; skip if recreate needed.
        return
    with engine.begin() as conn:
        # One-time cleanup of legacy unique on our_product_id only.
        for stmt in (
            "ALTER TABLE jc_catalog_products DROP CONSTRAINT IF EXISTS uq_jc_catalog_our_product_id",
            "DROP INDEX IF EXISTS uq_jc_catalog_our_product_id",
        ):
            try:
                conn.execute(text(stmt))
            except Exception:
                log.warning("Migration step skipped", exc_info=True)
        try:
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_jc_catalog_our_year_group "
                    "ON jc_catalog_products (lower(our_product_id), COALESCE(year_group, '')) "
                    "WHERE is_active IS TRUE AND deleted_at IS NULL"
                )
            )
        except Exception:
            log.warning("Migration step skipped", exc_info=True)


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
                log.warning("Migration step skipped", exc_info=True)


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
                log.warning("Migration step skipped", exc_info=True)


def _migrate_opening_balances() -> None:
    stmts = [
        "ALTER TABLE jc_ar_ledger_entries ADD COLUMN IF NOT EXISTS value_date DATE",
        "ALTER TABLE jc_ap_ledger_entries ADD COLUMN IF NOT EXISTS value_date DATE",
    ]
    with engine.begin() as conn:
        for stmt in stmts:
            try:
                conn.execute(text(stmt))
            except Exception:
                log.warning("Migration step skipped", exc_info=True)


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
                log.warning("Migration step skipped", exc_info=True)

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
                log.warning("Migration step skipped", exc_info=True)
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
                log.warning("Migration step skipped", exc_info=True)


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
                log.warning("Migration step skipped", exc_info=True)

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
                    log.warning("Migration step skipped", exc_info=True)
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
                    log.warning("Migration step skipped", exc_info=True)
        try:
            conn.execute(text(
                "UPDATE jc_customer_orders SET bucket = COALESCE(bucket, 'received'), "
                "is_open = COALESCE(is_open, true) WHERE bucket IS NULL OR is_open IS NULL"
            ))
        except Exception:
            log.warning("Migration step skipped", exc_info=True)


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
                log.warning("Migration step skipped", exc_info=True)


def _migrate_indexes() -> None:
    # CREATE IF NOT EXISTS only — never DROP/rebuild on boot (locks live traffic).
    stmts = [
        "CREATE INDEX IF NOT EXISTS ix_jc_entity_history_lookup ON jc_entity_history (entity_type, entity_id)",
        "CREATE INDEX IF NOT EXISTS ix_jc_activity_entity ON jc_activity_logs (entity_type, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_jc_vendor_orders_vendor_open ON jc_vendor_orders (vendor_id, bucket, is_open)",
        "CREATE INDEX IF NOT EXISTS ix_jc_ar_ledger_customer_type ON jc_ar_ledger_entries (customer_id, entry_type)",
        "CREATE INDEX IF NOT EXISTS ix_jc_ap_ledger_vendor_type ON jc_ap_ledger_entries (vendor_id, entry_type)",
        "CREATE INDEX IF NOT EXISTS ix_jc_customers_active_list ON jc_customers (is_active) WHERE deleted_at IS NULL",
    ]
    if not _is_sqlite:
        stmts.append(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_jc_vendor_orders_one_open "
            "ON jc_vendor_orders (vendor_id, bucket) WHERE is_open = true"
        )
    with engine.begin() as conn:
        try:
            conn.execute(text("SET LOCAL lock_timeout = '3s'"))
            conn.execute(text("SET LOCAL statement_timeout = '30s'"))
        except Exception:
            log.warning("Migration step skipped", exc_info=True)
        for stmt in stmts:
            try:
                conn.execute(text(stmt))
            except Exception:
                log.warning("Migration step skipped", exc_info=True)


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
                log.warning("Migration step skipped", exc_info=True)
