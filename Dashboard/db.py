from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import sys
import threading
import uuid
from datetime import date
from typing import Any, Dict, List, Optional, Sequence

_DASH_DIR = os.path.dirname(os.path.abspath(__file__))
if _DASH_DIR not in sys.path:
    sys.path.insert(0, _DASH_DIR)

from pg_support import connect_postgres

try:
    import storage_s3 as _storage_s3
except ImportError:
    _storage_s3 = None  # type: ignore


def _load_dashboard_models():
    """Load `Dashboard/models.py` as a unique module name. Reloads when the file on disk changes."""
    import importlib
    import importlib.util

    path = os.path.join(_DASH_DIR, "models.py")
    name = "_dashboard_schema_models"
    mtime = os.path.getmtime(path)
    mod = sys.modules.get(name)
    if mod is not None and getattr(mod, "_db_models_mtime", None) == mtime:
        if hasattr(mod, "CREATE_AR_PAYMENTS_TABLE"):
            return mod
    if mod is not None:
        mod = importlib.reload(mod)
    else:
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load schema from {path}")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    if not hasattr(mod, "CREATE_AR_PAYMENTS_TABLE"):
        raise ImportError(
            f"{path} is missing CREATE_AR_PAYMENTS_TABLE (reinstall or fix models.py)"
        )
    mod._db_models_mtime = mtime
    return mod


_m = _load_dashboard_models()
CREATE_AR_PAYMENTS_TABLE = _m.CREATE_AR_PAYMENTS_TABLE
CREATE_AP_PAYMENTS_TABLE = _m.CREATE_AP_PAYMENTS_TABLE
CREATE_CUSTOMERS_TABLE = _m.CREATE_CUSTOMERS_TABLE
CREATE_CUSTOMER_ORDER_BILLINGS_TABLE = _m.CREATE_CUSTOMER_ORDER_BILLINGS_TABLE
CREATE_CUSTOMER_ORDERS_TABLE = _m.CREATE_CUSTOMER_ORDERS_TABLE
CREATE_PO_BILLINGS_TABLE = _m.CREATE_PO_BILLINGS_TABLE
CREATE_PURCHASE_ORDERS_TABLE = _m.CREATE_PURCHASE_ORDERS_TABLE
CREATE_STOCK_RECEIPTS_TABLE = _m.CREATE_STOCK_RECEIPTS_TABLE
CREATE_VENDOR_PRODUCTS_TABLE = _m.CREATE_VENDOR_PRODUCTS_TABLE
CREATE_VENDORS_TABLE = _m.CREATE_VENDORS_TABLE
CREATE_PRODUCT_ALTERNATIVES_TABLE = _m.CREATE_PRODUCT_ALTERNATIVES_TABLE
CREATE_WAREHOUSES_TABLE = _m.CREATE_WAREHOUSES_TABLE
CREATE_PURCHASE_ORDER_DOCS_TABLE = _m.CREATE_PURCHASE_ORDER_DOCS_TABLE
CREATE_PURCHASE_ORDER_DOC_LINES_TABLE = _m.CREATE_PURCHASE_ORDER_DOC_LINES_TABLE
CREATE_GOODS_RECEIPT_DOCS_TABLE = _m.CREATE_GOODS_RECEIPT_DOCS_TABLE
CREATE_GOODS_RECEIPT_LINES_TABLE = _m.CREATE_GOODS_RECEIPT_LINES_TABLE
CREATE_VENDOR_BILL_DOCS_TABLE = _m.CREATE_VENDOR_BILL_DOCS_TABLE
CREATE_VENDOR_BILL_LINES_TABLE = _m.CREATE_VENDOR_BILL_LINES_TABLE
CREATE_STOCK_MOVEMENTS_TABLE = _m.CREATE_STOCK_MOVEMENTS_TABLE
CREATE_SALES_ORDER_DOCS_TABLE = _m.CREATE_SALES_ORDER_DOCS_TABLE
CREATE_SALES_ORDER_DOC_LINES_TABLE = _m.CREATE_SALES_ORDER_DOC_LINES_TABLE
CREATE_DELIVERY_DOCS_TABLE = _m.CREATE_DELIVERY_DOCS_TABLE
CREATE_DELIVERY_LINES_TABLE = _m.CREATE_DELIVERY_LINES_TABLE
CREATE_CUSTOMER_INVOICE_DOCS_TABLE = _m.CREATE_CUSTOMER_INVOICE_DOCS_TABLE
CREATE_CUSTOMER_INVOICE_LINES_TABLE = _m.CREATE_CUSTOMER_INVOICE_LINES_TABLE
ArPayment = _m.ArPayment
ApPayment = _m.ApPayment
Customer = _m.Customer
CustomerOrder = _m.CustomerOrder
CustomerOrderShipment = _m.CustomerOrderShipment
CustomerOrderBilling = _m.CustomerOrderBilling
PoBilling = _m.PoBilling
PurchaseOrder = _m.PurchaseOrder
StockReceipt = _m.StockReceipt
Vendor = _m.Vendor
VendorProduct = _m.VendorProduct
Warehouse = _m.Warehouse

_DASH = _DASH_DIR
UPLOADS_ROOT = os.path.join(_DASH, "uploads")
VP_UPLOAD_SUB = "vendor_products"
DOC_UPLOAD_SUB = "documents"

PBKDF2_ITERS = 200_000

# Customer portal: "low stock" band (still orderable if on_hand > 0)
LOW_STOCK_THRESHOLD = 5.0

# DDL / migrations run once per process; serialized so concurrent Streamlit runs don’t deadlock.
_PG_SCHEMA_INITIALIZED = False
_INIT_DB_DONE = False
_init_db_lock = threading.Lock()


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


def effective_low_stock_threshold(raw: Optional[float]) -> float:
    try:
        if raw is not None and float(raw) > 0:
            return float(raw)
    except (TypeError, ValueError):
        pass
    return float(LOW_STOCK_THRESHOLD)


def get_db_path() -> str:
    """Display label only — data lives in Postgres via ``DATABASE_URL``."""
    return "postgresql"


def get_uploads_path() -> str:
    return UPLOADS_ROOT


def _abs_doc_dir(doc_group: str) -> str:
    return os.path.join(UPLOADS_ROOT, DOC_UPLOAD_SUB, doc_group)


def _abs_product_dir(product_id: int) -> str:
    return os.path.join(UPLOADS_ROOT, VP_UPLOAD_SUB, str(product_id))


def _database_url_required() -> str:
    u = (os.environ.get("DATABASE_URL") or "").strip()
    if not u:
        raise RuntimeError(
            "DATABASE_URL is required (Supabase Postgres). Set it in Streamlit Secrets or the environment."
        )
    return u


def _connect():
    """PostgreSQL only (Supabase)."""
    _database_url_required()
    return connect_postgres()


def _table_exists(name: str) -> bool:
    from pg_support import table_exists_pg

    with _connect() as c:
        return table_exists_pg(c, name)


def hash_password(plain: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt, PBKDF2_ITERS)
    return (
        "pbkdf2_256$"
        + str(PBKDF2_ITERS)
        + "$"
        + base64.b64encode(salt).decode("ascii")
        + "$"
        + base64.b64encode(dk).decode("ascii")
    )


def verify_password(stored: str, plain: str) -> bool:
    try:
        parts = stored.split("$", 3)
        if len(parts) != 4 or parts[0] != "pbkdf2_256":
            return False
        iters = int(parts[1])
        salt = base64.b64decode(parts[2].encode("ascii"))
        want = base64.b64decode(parts[3].encode("ascii"))
    except (ValueError, OSError, TypeError):
        return False
    try:
        got = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt, iters)
    except (ValueError, OSError, TypeError):
        return False
    return hmac.compare_digest(got, want)


def _as_int_migrated(val: object) -> Optional[int]:
    if val is None:
        return None
    if isinstance(val, int) and not isinstance(val, bool):
        return val
    s = str(val).strip()
    if not s:
        return None
    try:
        return int(s, 10)
    except (ValueError, TypeError):
        m = re.search(r"-?\d+", s)
        if not m:
            return None
        try:
            return int(m.group(), 10)
        except (ValueError, TypeError):
            return None


def _migrated_billing(d: dict) -> Optional[int]:
    c, b = d.get("billing_custom"), d.get("billing_condition")
    n = _as_int_migrated(c)
    if n is not None:
        return n
    sb = (str(b) if b is not None else "").strip()
    if sb in ("50", "100"):
        return int(sb, 10)
    if sb == "custom" or not sb:
        return None
    return _as_int_migrated(b)


def _rel_vendor_product_path(product_id: int, filename: str) -> str:
    return f"{VP_UPLOAD_SUB}/{product_id}/{filename}"


def _load_image_paths(s: Optional[str]) -> list[str]:
    if not s or not str(s).strip():
        return []
    try:
        p = json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return []
    if isinstance(p, list):
        return [str(x) for x in p if x is not None and str(x).strip()]
    return []


def _dump_image_paths(paths: list[str]) -> str:
    return json.dumps(paths, ensure_ascii=True)


def _abs_from_rel(rel: str) -> str:
    return os.path.join(UPLOADS_ROOT, rel.replace("/", os.sep))


def _remove_product_files_by_rel_list(paths: list[str]) -> None:
    for rel in paths:
        delete_product_image_rel(rel)


def _rmtree_product_dir(product_id: int) -> None:
    p = _abs_product_dir(product_id)
    if os.path.isdir(p):
        try:
            shutil.rmtree(p, ignore_errors=True)
        except OSError:
            pass


def save_product_uploads_streamlit(
    product_id: int, uploaded_files: Optional[Sequence[object]]
) -> list[str]:
    if not uploaded_files:
        return []
    if _storage_s3 is not None and _storage_s3.s3_enabled():
        return _storage_s3.put_product_uploads(product_id, uploaded_files)
    d = _abs_product_dir(product_id)
    os.makedirs(d, exist_ok=True)
    out: list[str] = []
    for u in uploaded_files:
        name = getattr(u, "name", None) or "upload"
        _, ext = os.path.splitext(name)
        ext = (ext or "").lower() if ext else ".bin"
        if ext not in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".bin"):
            ext = ".bin"
        fn = f"img_{uuid.uuid4().hex}{ext if ext else '.bin'}"
        ap = os.path.join(d, fn)
        data = u.getvalue()  # type: ignore[union-attr]
        with open(ap, "wb") as f:
            f.write(data)
        out.append(_rel_vendor_product_path(product_id, fn))
    return out


def product_image_full_path(rel: str) -> str:
    if not rel or str(rel).strip().startswith("s3:"):
        return ""
    return _abs_from_rel(rel)


def product_image_src(rel: Optional[str]) -> Optional[str]:
    """Filesystem path or presigned HTTPS URL for ``st.image``."""
    if not rel or not str(rel).strip():
        return None
    r = str(rel).strip()
    if r.startswith("s3:"):
        if _storage_s3 is None or not _storage_s3.s3_enabled():
            return None
        key = r[3:].lstrip("/")
        try:
            return _storage_s3.presigned_get_url(key)
        except Exception:
            return None
    ap = _abs_from_rel(r)
    return ap if os.path.isfile(ap) else None


def delete_product_image_rel(rel: str) -> None:
    """Remove one stored image (local file or S3 object)."""
    r = (rel or "").strip()
    if not r:
        return
    if r.startswith("s3:"):
        if _storage_s3 is not None and _storage_s3.s3_enabled():
            _storage_s3.delete_key(r[3:])
        return
    ap = _abs_from_rel(r)
    try:
        if os.path.isfile(ap):
            os.remove(ap)
    except OSError:
        pass


def _save_document_upload_bytes(doc_group: str, stem: str, file_bytes: bytes, name_hint: str) -> str:
    d = _abs_doc_dir(doc_group)
    os.makedirs(d, exist_ok=True)
    ext = (os.path.splitext((name_hint or "upload.bin") or "upload.bin")[1] or ".bin").lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp", ".pdf", ".bin"):
        ext = ".bin"
    fn = f"{stem}_{uuid.uuid4().hex[:10]}{ext}"
    ap = os.path.join(d, fn)
    with open(ap, "wb") as f:
        f.write(file_bytes)
    return os.path.join(DOC_UPLOAD_SUB, doc_group, fn).replace("\\", "/")


def _save_document_streamlit_upload(doc_group: str, stem: str, uploaded: Optional[object]) -> Optional[str]:
    if uploaded is None:
        return None
    data = uploaded.getvalue()  # type: ignore[union-attr]
    return _save_document_upload_bytes(doc_group, stem, data, getattr(uploaded, "name", "upload.bin"))


def document_full_path(rel: Optional[str]) -> Optional[str]:
    if not rel or not str(rel).strip():
        return None
    return _abs_from_rel(str(rel))


def _next_doc_no(prefix: str, table: str, col: str = "doc_no") -> str:
    init_db()
    pfx = (prefix or "DOC").strip().upper()
    with _connect() as conn:
        row = conn.execute(
            f"SELECT {col} AS doc_no FROM {table} WHERE {col} LIKE ? ORDER BY id DESC LIMIT 1",
            (f"{pfx}-%",),
        ).fetchone()
    last = str(row["doc_no"]) if row and row["doc_no"] else ""
    m = re.search(r"(\d+)$", last)
    n = int(m.group(1)) + 1 if m else 1
    return f"{pfx}-{n:05d}"


def gst_split_inclusive(amount_incl_gst: float, gst_rate_pct: Optional[float]) -> tuple[float, float, float]:
    gross = round(float(amount_incl_gst or 0.0), 2)
    rate = float(gst_rate_pct or 0.0)
    if abs(rate) < 0.0001:
        return (gross, 0.0, gross)
    base = round(gross / (1.0 + (rate / 100.0)), 2)
    gst = round(gross - base, 2)
    return (base, gst, gross)


def gst_add_exclusive(base_amount: float, gst_rate_pct: Optional[float]) -> tuple[float, float, float]:
    base = round(float(base_amount or 0.0), 2)
    rate = float(gst_rate_pct or 0.0)
    gst = round(base * (rate / 100.0), 2)
    gross = round(base + gst, 2)
    return (base, gst, gross)


def _ensure_vendor_product_pricing_columns() -> None:
    if not _table_exists("vendor_products"):
        return
    cols = _table_cols("vendor_products")
    with _connect() as conn:
        if "cost_price" not in cols:
            conn.execute("ALTER TABLE vendor_products ADD COLUMN cost_price REAL")
        if "tax_rate" not in cols:
            conn.execute("ALTER TABLE vendor_products ADD COLUMN tax_rate REAL")
        if "tax_inclusive" not in cols:
            conn.execute("ALTER TABLE vendor_products ADD COLUMN tax_inclusive INTEGER")
        if "low_stock_threshold" not in cols:
            conn.execute("ALTER TABLE vendor_products ADD COLUMN low_stock_threshold REAL")
        conn.commit()


def _ensure_product_alternatives_table() -> None:
    """Defined in ``init_postgres_schema``."""
    return


def _ensure_purchase_order_extras() -> None:
    if not _table_exists("purchase_orders"):
        return
    cols = _table_cols("purchase_orders")
    with _connect() as conn:
        if "status" not in cols:
            conn.execute(
                "ALTER TABLE purchase_orders ADD COLUMN status TEXT NOT NULL DEFAULT 'open'"
            )
        if "transport_name" not in cols:
            conn.execute("ALTER TABLE purchase_orders ADD COLUMN transport_name TEXT")
        if "transport_number" not in cols:
            conn.execute("ALTER TABLE purchase_orders ADD COLUMN transport_number TEXT")
        conn.execute(
            "UPDATE purchase_orders SET status = 'open' WHERE status IS NULL OR status = ''"
        )
        cols2 = _table_cols("purchase_orders")
        if "status" in cols2:
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_po_status ON purchase_orders (status)"
            )
        conn.commit()


def _ensure_po_billings_table() -> None:
    """Defined in ``init_postgres_schema``."""
    return


def _ensure_vendor_issuer_columns() -> None:
    if not _table_exists("vendors"):
        return
    cols = _table_cols("vendors")
    with _connect() as conn:
        alters = [
            ("issuer_legal_name", "TEXT"),
            ("issuer_address", "TEXT"),
            ("issuer_city_pin", "TEXT"),
            ("issuer_gstin", "TEXT"),
            ("issuer_phone", "TEXT"),
            ("issuer_email", "TEXT"),
        ]
        for name, typ in alters:
            if name not in cols:
                conn.execute(f"ALTER TABLE vendors ADD COLUMN {name} {typ}")
        conn.commit()


def _ensure_po_billings_snapshot_columns() -> None:
    if not _table_exists("po_billings"):
        return
    cols = _table_cols("po_billings")
    with _connect() as conn:
        alters = [
            ("snap_vendor_person", "TEXT"),
            ("snap_vendor_company", "TEXT"),
            ("snap_vendor_phone", "TEXT"),
            ("snap_issuer_legal_name", "TEXT"),
            ("snap_issuer_address", "TEXT"),
            ("snap_issuer_city_pin", "TEXT"),
            ("snap_issuer_gstin", "TEXT"),
            ("snap_issuer_phone", "TEXT"),
            ("snap_issuer_email", "TEXT"),
            ("snap_item_sku", "TEXT"),
            ("snap_item_name", "TEXT"),
        ]
        for name, typ in alters:
            if name not in cols:
                conn.execute(f"ALTER TABLE po_billings ADD COLUMN {name} {typ}")
        conn.commit()


def _ensure_customer_orders_tables() -> None:
    """Tables created by ``init_postgres_schema``; only column migrations here."""
    _ensure_customer_order_delivery_columns()


def _ensure_customer_order_delivery_columns() -> None:
    if not _table_exists("customer_orders"):
        return
    cols = _table_cols("customer_orders")
    with _connect() as conn:
        for col, typ in (
            ("delivery_receipt_number", "TEXT"),
            ("delivery_contact", "TEXT"),
            ("delivery_notes", "TEXT"),
            ("receipt_image_path", "TEXT"),
            ("delivery_receipt_pdf_path", "TEXT"),
            ("whatsapp_ship_notice_sent", "INTEGER DEFAULT 0"),
        ):
            if col not in cols:
                conn.execute(f"ALTER TABLE customer_orders ADD COLUMN {col} {typ}")
        conn.commit()


def _ensure_customer_order_shipments_table() -> None:
    """Schema from ``init_postgres_schema``."""
    return


def _ensure_accounting_payments() -> None:
    """AR/AP tables come from ``init_postgres_schema``."""
    return


def _migrate_payment_tables_for_documents() -> None:
    """SQLite-only legacy migration — removed."""
    return


def _ensure_document_tables() -> None:
    """Document tables created by ``init_postgres_schema``."""
    return


def _ensure_default_warehouse() -> None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT id FROM warehouses WHERE is_default = 1 ORDER BY id LIMIT 1"
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE warehouses SET is_default = 0 WHERE id <> ? AND is_default <> 0",
                (int(row["id"]),),
            )
        else:
            conn.execute(
                """
                INSERT INTO warehouses (code, name, is_default)
                VALUES ('MAIN', 'Main warehouse', 1)
                """
            )
        conn.commit()


def _table_cols(table: str) -> set:
    from pg_support import table_columns_pg

    with _connect() as c:
        return table_columns_pg(c, table)


def _ensure_gl_columns() -> None:
    import gl as _gl

    _gl.init_gl_full()
    for table, col, typ in (
        ("po_billings", "gl_journal_id", "INTEGER"),
        ("customer_order_billings", "gl_journal_id", "INTEGER"),
        ("customer_order_billings", "payment_reminder_wa_sent_at", "TEXT"),
        ("ar_payments", "gl_journal_id", "INTEGER"),
        ("ap_payments", "gl_journal_id", "INTEGER"),
    ):
        if not _table_exists(table):
            continue
        if col in _table_cols(table):
            continue
        with _connect() as c2:
            c2.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
            c2.commit()


def init_db() -> None:
    """Ensure uploads dir; optionally create/migrate schema once per process (not every rerun)."""
    global _PG_SCHEMA_INITIALIZED, _INIT_DB_DONE
    os.makedirs(UPLOADS_ROOT, exist_ok=True)
    if _env_truthy("DATABASE_SKIP_DDL"):
        return
    if _INIT_DB_DONE:
        return
    with _init_db_lock:
        if _INIT_DB_DONE:
            return
        if not _PG_SCHEMA_INITIALIZED:
            from pg_init_postgres import init_postgres_schema

            init_postgres_schema()
            _PG_SCHEMA_INITIALIZED = True
        _ensure_vendor_product_pricing_columns()
        _ensure_purchase_order_extras()
        _ensure_po_billings_table()
        _ensure_vendor_issuer_columns()
        _ensure_po_billings_snapshot_columns()
        _ensure_customer_orders_tables()
        _ensure_customer_order_shipments_table()
        _ensure_document_tables()
        _ensure_default_warehouse()
        _ensure_accounting_payments()
        _ensure_gl_columns()
        _ensure_product_alternatives_table()
        _INIT_DB_DONE = True


def get_dashboard_stats() -> dict:
    """Summary counts and per-vendor product counts (all vendors, including zero)."""
    init_db()
    with _connect() as conn:
        n_c = int(conn.execute("SELECT COUNT(*) AS c FROM customers").fetchone()["c"])
        n_v = int(conn.execute("SELECT COUNT(*) AS c FROM vendors").fetchone()["c"])
        n_p = int(conn.execute("SELECT COUNT(*) AS c FROM vendor_products").fetchone()["c"])
        n_po = int(
            conn.execute("SELECT COUNT(*) AS c FROM purchase_orders").fetchone()["c"]
        )
        n_sku = int(
            conn.execute(
                "SELECT COUNT(DISTINCT product_id) AS c FROM stock_receipts"
            ).fetchone()["c"]
        )
        n_stk = float(
            conn.execute("SELECT COALESCE(SUM(quantity), 0) AS s FROM stock_receipts")
            .fetchone()["s"]
        )
        n_bill = int(_table_exists("po_billings"))
        n_pb = (
            int(conn.execute("SELECT COUNT(*) AS c FROM po_billings").fetchone()["c"])
            if n_bill
            else 0
        )
        n_co = int(_table_exists("customer_orders"))
        n_co_rows = (
            int(conn.execute("SELECT COUNT(*) AS c FROM customer_orders").fetchone()["c"])
            if n_co
            else 0
        )
        n_cob_t = int(_table_exists("customer_order_billings"))
        n_cob = (
            int(
                conn.execute("SELECT COUNT(*) AS c FROM customer_order_billings").fetchone()[
                    "c"
                ]
            )
            if n_cob_t
            else 0
        )
        rows = conn.execute(
            """
            SELECT v.id, v.person_name, v.company_name,
              (SELECT COUNT(*) FROM vendor_products p WHERE p.vendor_id = v.id) AS n
            FROM vendors v
            ORDER BY v.person_name
            """
        ).fetchall()
        ar_t = int(_table_exists("ar_payments"))
        ap_t = int(_table_exists("ap_payments"))
        po_val = float(
            conn.execute(
                "SELECT COALESCE(SUM(quantity * unit_cost), 0) AS s FROM purchase_orders"
            ).fetchone()["s"]
        )
        po_billed_raw = 0.0
        if n_bill and n_pb:
            po_billed_raw = float(
                conn.execute("SELECT COALESCE(SUM(raw_line_total), 0) AS s FROM po_billings")
                .fetchone()["s"]
            )
        co_billed_raw = 0.0
        if n_cob_t and n_cob:
            co_billed_raw = float(
                conn.execute(
                    "SELECT COALESCE(SUM(raw_line_total), 0) AS s FROM customer_order_billings"
                )
                .fetchone()["s"]
            )
        ar_out = 0.0
        ar_paid = 0.0
        if n_cob_t and n_cob and ar_t:
            ar_paid = float(
                conn.execute("SELECT COALESCE(SUM(amount), 0) AS s FROM ar_payments").fetchone()[
                    "s"
                ]
            )
            ar_out = co_billed_raw - ar_paid
        ap_out = 0.0
        ap_paid = 0.0
        if n_bill and n_pb and ap_t:
            ap_paid = float(
                conn.execute("SELECT COALESCE(SUM(amount), 0) AS s FROM ap_payments").fetchone()[
                    "s"
                ]
            )
            ap_out = po_billed_raw - ap_paid
    vendors = [
        {
            "id": int(r["id"]),
            "person_name": r["person_name"] or "—",
            "company_name": (r["company_name"] or "").strip() or "—",
            "n_products": int(r["n"]),
        }
        for r in rows
    ]
    n_sku_low = 0
    n_sku_out = 0
    try:
        n_sku_low = len(list_catalog_stock_rows(status_filter={"low_stock"}))
        n_sku_out = len(list_catalog_stock_rows(status_filter={"out_of_stock"}))
    except Exception:
        pass
    with _connect() as conn2:
        pipe_rev = float(
            conn2.execute(
                f"""
                SELECT COALESCE(SUM(co.quantity * co.unit_price), 0) AS s
                FROM customer_orders co
                WHERE { _sales_pipeline_where() }
                """,
            )
            .fetchone()["s"]
        )
        rev_30 = float(
            conn2.execute(
                f"""
                SELECT COALESCE(SUM(co.quantity * co.unit_price), 0) AS s
                FROM customer_orders co
                WHERE { _sales_pipeline_where() }
                  AND date(co.created_at) >= date('now', '-30 days')
                """,
            )
            .fetchone()["s"]
        )
    return {
        "n_customers": n_c,
        "n_vendors": n_v,
        "n_products": n_p,
        "n_purchase_orders": n_po,
        "n_stock_sku": n_sku,
        "n_stock_units": n_stk,
        "n_po_billings": n_pb,
        "n_customer_orders": n_co_rows,
        "n_customer_order_billings": n_cob,
        "n_sku_low_stock": n_sku_low,
        "n_sku_out_of_stock": n_sku_out,
        "pipeline_sales_revenue": pipe_rev,
        "pipeline_sales_30d": rev_30,
        "vendors": vendors,
        "po_value_committed": po_val,
        "po_billed_raw_total": po_billed_raw,
        "co_billed_raw_total": co_billed_raw,
        "ar_paid_total": ar_paid,
        "ap_paid_total": ap_paid,
        "ar_outstanding": ar_out,
        "ap_outstanding": ap_out,
        "net_position": ar_out - ap_out,
    }


def _sales_pipeline_where() -> str:
    return (
        "LOWER(TRIM(COALESCE(co.status, ''))) IN "
        "('placed', 'confirmed', 'in_progress', 'shipped', 'delivered')"
    )


def list_warehouses() -> List[Warehouse]:
    init_db()
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM warehouses ORDER BY is_default DESC, id ASC").fetchall()
    return [Warehouse(**dict(r)) for r in rows]


def get_default_warehouse() -> Warehouse:
    init_db()
    with _connect() as conn:
        r = conn.execute(
            "SELECT * FROM warehouses WHERE is_default = 1 ORDER BY id LIMIT 1"
        ).fetchone()
    if not r:
        raise ValueError("Default warehouse not configured")
    return Warehouse(**dict(r))


def get_document_dashboard_stats() -> dict[str, Any]:
    init_db()
    with _connect() as conn:
        return {
            "purchase_orders": int(conn.execute("SELECT COUNT(*) AS c FROM purchase_order_docs").fetchone()["c"]),
            "goods_receipts": int(conn.execute("SELECT COUNT(*) AS c FROM goods_receipt_docs").fetchone()["c"]),
            "vendor_bills": int(conn.execute("SELECT COUNT(*) AS c FROM vendor_bill_docs").fetchone()["c"]),
            "sales_orders": int(conn.execute("SELECT COUNT(*) AS c FROM sales_order_docs").fetchone()["c"]),
            "deliveries": int(conn.execute("SELECT COUNT(*) AS c FROM delivery_docs").fetchone()["c"]),
            "customer_invoices": int(conn.execute("SELECT COUNT(*) AS c FROM customer_invoice_docs").fetchone()["c"]),
            "three_way_disputes": int(
                conn.execute(
                    "SELECT COUNT(*) AS c FROM vendor_bill_docs WHERE LOWER(TRIM(COALESCE(match_status,''))) = 'dispute'"
                ).fetchone()["c"]
            ),
        }


def stock_on_hand_v2(
    product_id: int, warehouse_id: Optional[int] = None, conn: Optional[Any] = None
) -> float:
    where = ["product_id = ?"]
    args: list[object] = [int(product_id)]
    if warehouse_id is not None:
        where.append("warehouse_id = ?")
        args.append(int(warehouse_id))
    own = conn is None
    if own:
        init_db()
        conn = _connect()
    try:
        row = conn.execute(
            f"SELECT COALESCE(SUM(quantity), 0) AS s FROM stock_movements WHERE {' AND '.join(where)}",
            args,
        ).fetchone()
        row2 = conn.execute(
            "SELECT COALESCE(SUM(quantity), 0) AS s FROM stock_receipts WHERE product_id = ?",
            (int(product_id),),
        ).fetchone()
    finally:
        if own and conn is not None:
            conn.close()
    return float(row["s"] if row else 0.0) + float(row2["s"] if row2 else 0.0)


def list_stock_positions_v2() -> list[dict[str, Any]]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT
                vp.id AS product_id,
                vp.our_product_id,
                vp.name,
                vp.category,
                vp.low_stock_threshold,
                COALESCE(SUM(sm.quantity), 0) AS on_hand
            FROM vendor_products vp
            LEFT JOIN stock_movements sm ON sm.product_id = vp.id
            GROUP BY vp.id
            ORDER BY LOWER(vp.our_product_id)
            """
        ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        oh = float(d.get("on_hand") or 0.0)
        th = effective_low_stock_threshold(d.get("low_stock_threshold"))
        d["stock_status"] = "out_of_stock" if oh <= 0.0001 else ("low_stock" if oh < th else "in_stock")
        d["reorder_recommended"] = d["stock_status"] in ("low_stock", "out_of_stock")
        d["low_band"] = th
        out.append(d)
    return out


def _post_stock_movement(
    conn: Any,
    *,
    warehouse_id: int,
    product_id: int,
    movement_type: str,
    quantity: float,
    ref_type: str,
    ref_id: int,
    ref_line_id: Optional[int],
    notes: Optional[str],
) -> int:
    cur = conn.execute(
        """
        INSERT INTO stock_movements (
            warehouse_id, product_id, movement_type, quantity, ref_type, ref_id, ref_line_id, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(warehouse_id),
            int(product_id),
            movement_type.strip(),
            float(quantity),
            ref_type.strip(),
            int(ref_id),
            int(ref_line_id) if ref_line_id is not None else None,
            (notes or None) or None,
        ),
    )
    return int(cur.lastrowid)


def _recompute_po_doc_status(conn: Any, po_doc_id: int) -> str:
    po_lines = conn.execute(
        "SELECT id, quantity FROM purchase_order_doc_lines WHERE po_doc_id = ?",
        (int(po_doc_id),),
    ).fetchall()
    ordered = sum(float(r["quantity"] or 0) for r in po_lines)
    received = 0.0
    if po_lines:
        ids = [int(r["id"]) for r in po_lines]
        qs = ",".join("?" for _ in ids)
        row = conn.execute(
            f"SELECT COALESCE(SUM(quantity), 0) AS s FROM goods_receipt_lines WHERE po_line_id IN ({qs})",
            ids,
        ).fetchone()
        received = float(row["s"] if row else 0.0)
    dispute_ct = int(
        conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM vendor_bill_docs
            WHERE po_doc_id = ?
              AND LOWER(TRIM(COALESCE(match_status, ''))) = 'dispute'
            """,
            (int(po_doc_id),),
        ).fetchone()["c"]
    )
    if dispute_ct > 0:
        status = "disputed"
    elif received <= 0.0001:
        status = "open"
    elif received + 0.0001 < ordered:
        status = "in_progress"
    else:
        status = "closed"
    conn.execute(
        "UPDATE purchase_order_docs SET status = ?, updated_at = datetime('now') WHERE id = ?",
        (status, int(po_doc_id)),
    )
    return status


def _default_seller_snapshot() -> dict[str, Optional[str]]:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT issuer_legal_name, issuer_address, issuer_city_pin,
                   issuer_gstin, issuer_phone, issuer_email
            FROM vendors
            WHERE COALESCE(NULLIF(TRIM(issuer_legal_name), ''), '') <> ''
            ORDER BY id ASC
            LIMIT 1
            """
        ).fetchone()
    if not row:
        return {
            "legal_name": None,
            "address": None,
            "city_pin": None,
            "gstin": None,
            "phone": None,
            "email": None,
        }
    return {
        "legal_name": row["issuer_legal_name"],
        "address": row["issuer_address"],
        "city_pin": row["issuer_city_pin"],
        "gstin": row["issuer_gstin"],
        "phone": row["issuer_phone"],
        "email": row["issuer_email"],
    }


def create_purchase_order_document(
    vendor_id: int,
    lines: Sequence[dict[str, Any]],
    *,
    notes: Optional[str] = None,
    payment_terms: Optional[int] = None,
    billing: Optional[int] = None,
    transport_name: Optional[str] = None,
    transport_number: Optional[str] = None,
    gst_rate_pct: float = 18.0,
    warehouse_id: Optional[int] = None,
) -> int:
    init_db()
    vendor = get_vendor(int(vendor_id))
    if not vendor:
        raise ValueError("Vendor not found")
    if not lines:
        raise ValueError("At least one PO line is required")
    wh = get_default_warehouse() if warehouse_id is None else None
    wh_id = int(warehouse_id or (wh.id if wh else 0))
    doc_no = _next_doc_no("PO", "purchase_order_docs")
    clean_lines: list[dict[str, Any]] = []
    base_total = gst_total = grand_total = 0.0
    for idx, line in enumerate(lines, start=1):
        pid = int(line.get("product_id") or 0)
        qty = float(line.get("quantity") or 0)
        unit = float(line.get("unit_cost") or 0)
        if pid <= 0 or qty <= 0 or unit < 0:
            raise ValueError("Each PO line needs product, positive quantity, and unit cost")
        pr = get_vendor_product(pid)
        if not pr:
            raise ValueError(f"Product #{pid} not found")
        if int(pr.vendor_id) != int(vendor_id):
            raise ValueError(f"Product {pr.our_product_id} does not belong to this vendor")
        lb, lg, lt = gst_add_exclusive(qty * unit, line.get("gst_rate_pct", gst_rate_pct))
        clean_lines.append(
            {
                "line_no": idx,
                "product_id": pid,
                "sku": pr.our_product_id,
                "item_name": pr.name,
                "quantity": qty,
                "unit_cost": unit,
                "gst_rate_pct": float(line.get("gst_rate_pct", gst_rate_pct) or gst_rate_pct),
                "line_base_total": lb,
                "line_gst_total": lg,
                "line_grand_total": lt,
                "notes": (line.get("notes") or None),
            }
        )
        base_total += lb
        gst_total += lg
        grand_total += lt
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO purchase_order_docs (
                doc_no, vendor_id, warehouse_id, status, payment_terms, billing, gst_rate_pct,
                transport_name, transport_number, notes, updated_at
            )
            VALUES (?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                doc_no,
                int(vendor_id),
                wh_id,
                payment_terms if payment_terms is not None else vendor.payment_terms,
                billing if billing is not None else vendor.billing,
                float(gst_rate_pct),
                (transport_name or None) or None,
                (transport_number or None) or None,
                (notes or None) or None,
            ),
        )
        doc_id = int(cur.lastrowid)
        for row in clean_lines:
            conn.execute(
                """
                INSERT INTO purchase_order_doc_lines (
                    po_doc_id, line_no, product_id, sku, item_name, quantity, unit_cost, gst_rate_pct,
                    line_base_total, line_gst_total, line_grand_total, notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc_id,
                    row["line_no"],
                    row["product_id"],
                    row["sku"],
                    row["item_name"],
                    row["quantity"],
                    row["unit_cost"],
                    row["gst_rate_pct"],
                    row["line_base_total"],
                    row["line_gst_total"],
                    row["line_grand_total"],
                    row["notes"],
                ),
            )
        _recompute_po_doc_status(conn, doc_id)
        conn.commit()
    pdf_bytes = build_purchase_order_pdf(doc_id)
    rel_pdf = _save_document_upload_bytes("purchase_orders", f"po_{doc_id:05d}", pdf_bytes, f"{doc_no}.pdf")
    with _connect() as conn:
        conn.execute(
            "UPDATE purchase_order_docs SET pdf_path = ?, updated_at = datetime('now') WHERE id = ?",
            (rel_pdf, doc_id),
        )
        conn.commit()
    return doc_id


def list_purchase_order_documents() -> list[dict[str, Any]]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT p.*, v.person_name AS vendor_name, v.company_name
            FROM purchase_order_docs p
            JOIN vendors v ON v.id = p.vendor_id
            ORDER BY p.created_at DESC, p.id DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def get_purchase_order_document(doc_id: int) -> Optional[dict[str, Any]]:
    init_db()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM purchase_order_docs WHERE id = ?", (int(doc_id),)).fetchone()
    return dict(row) if row else None


def list_purchase_order_document_lines(doc_id: int) -> list[dict[str, Any]]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM purchase_order_doc_lines WHERE po_doc_id = ? ORDER BY line_no ASC, id ASC",
            (int(doc_id),),
        ).fetchall()
    return [dict(r) for r in rows]


def build_purchase_order_pdf(doc_id: int) -> bytes:
    from bill_pdf import build_multi_line_document_pdf

    doc = get_purchase_order_document(doc_id)
    if not doc:
        raise ValueError("Purchase order document not found")
    vendor = get_vendor(int(doc["vendor_id"]))
    if not vendor:
        raise ValueError("Vendor missing")
    lines = list_purchase_order_document_lines(doc_id)
    seller = _default_seller_snapshot()
    return build_multi_line_document_pdf(
        title="PURCHASE ORDER",
        doc_no=str(doc["doc_no"]),
        doc_date=str(doc.get("created_at") or "")[:10] or date.today().isoformat(),
        party_heading="Vendor",
        party_name=(vendor.person_name or "—"),
        party_company=vendor.company_name,
        party_phone=vendor.primary_phone,
        party_address=None,
        meta_rows=[
            ["Status", str(doc.get("status") or "open").title()],
            ["Payment terms", str(doc.get("payment_terms") or "—")],
            ["Transport", " / ".join([x for x in [doc.get("transport_name"), doc.get("transport_number")] if x]) or "—"],
        ],
        line_rows=[
            {
                "sku": r["sku"],
                "item_name": r["item_name"],
                "quantity": r["quantity"],
                "unit_rate": r["unit_cost"],
                "base_total": r["line_base_total"],
                "gst_total": r["line_gst_total"],
                "grand_total": r["line_grand_total"],
            }
            for r in lines
        ],
        total_rows=[
            ["Taxable total", f"Rs. {sum(float(r['line_base_total']) for r in lines):,.2f}"],
            ["GST total", f"Rs. {sum(float(r['line_gst_total']) for r in lines):,.2f}"],
            ["Grand total", f"Rs. {sum(float(r['line_grand_total']) for r in lines):,.2f}"],
        ],
        notes=doc.get("notes"),
        seller=seller,
        subtitle="Vendor rate is base price; GST is calculated over and above the entered cost.",
    )


def create_goods_receipt_document(
    po_doc_id: int,
    lines: Sequence[dict[str, Any]],
    *,
    vendor_receipt_ref: Optional[str] = None,
    grn_number: Optional[str] = None,
    notes: Optional[str] = None,
    receipt_image_bytes: Optional[bytes] = None,
    receipt_image_name: str = "receipt.jpg",
) -> int:
    init_db()
    po = get_purchase_order_document(po_doc_id)
    if not po:
        raise ValueError("PO document not found")
    po_lines = {int(r["id"]): r for r in list_purchase_order_document_lines(po_doc_id)}
    if not lines:
        raise ValueError("At least one receipt line is required")
    receipt_no = _next_doc_no("GRN", "goods_receipt_docs", "receipt_no")
    rel_img = (
        _save_document_upload_bytes("goods_receipts", f"grn_{receipt_no}", receipt_image_bytes, receipt_image_name)
        if receipt_image_bytes
        else None
    )
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO goods_receipt_docs (
                receipt_no, po_doc_id, warehouse_id, status, vendor_receipt_ref, grn_number,
                receipt_image_path, notes, updated_at
            )
            VALUES (?, ?, ?, 'posted', ?, ?, ?, ?, datetime('now'))
            """,
            (
                receipt_no,
                int(po_doc_id),
                int(po["warehouse_id"]),
                (vendor_receipt_ref or None) or None,
                (grn_number or None) or None,
                rel_img,
                (notes or None) or None,
            ),
        )
        rid = int(cur.lastrowid)
        for line in lines:
            po_line_id = int(line.get("po_line_id") or 0)
            qty = float(line.get("quantity") or 0)
            if po_line_id not in po_lines or qty <= 0:
                raise ValueError("Each receipt line needs a valid PO line and positive quantity")
            po_line = po_lines[po_line_id]
            conn.execute(
                """
                INSERT INTO goods_receipt_lines (goods_receipt_id, po_line_id, product_id, quantity, notes)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    rid,
                    po_line_id,
                    int(po_line["product_id"]),
                    qty,
                    (line.get("notes") or None),
                ),
            )
            _post_stock_movement(
                conn,
                warehouse_id=int(po["warehouse_id"]),
                product_id=int(po_line["product_id"]),
                movement_type="receipt",
                quantity=qty,
                ref_type="goods_receipt",
                ref_id=rid,
                ref_line_id=po_line_id,
                notes=(line.get("notes") or notes),
            )
        _recompute_po_doc_status(conn, int(po_doc_id))
        conn.commit()
    return rid


def list_goods_receipt_documents() -> list[dict[str, Any]]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT g.*, p.doc_no AS po_doc_no
            FROM goods_receipt_docs g
            JOIN purchase_order_docs p ON p.id = g.po_doc_id
            ORDER BY g.created_at DESC, g.id DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def get_goods_receipt_document(receipt_id: int) -> Optional[dict[str, Any]]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM goods_receipt_docs WHERE id = ?", (int(receipt_id),)).fetchone()
    return dict(row) if row else None


def list_goods_receipt_lines(receipt_id: int) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM goods_receipt_lines WHERE goods_receipt_id = ? ORDER BY id ASC",
            (int(receipt_id),),
        ).fetchall()
    return [dict(r) for r in rows]


def _received_qty_for_po_line(po_line_id: int) -> float:
    with _connect() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(quantity), 0) AS s FROM goods_receipt_lines WHERE po_line_id = ?",
            (int(po_line_id),),
        ).fetchone()
    return float(row["s"] if row else 0.0)


def create_vendor_bill_document(
    po_doc_id: int,
    lines: Sequence[dict[str, Any]],
    *,
    goods_receipt_id: Optional[int] = None,
    bill_date: Optional[str] = None,
    vendor_invoice_ref: Optional[str] = None,
    vendor_gstin: Optional[str] = None,
    notes: Optional[str] = None,
    bill_image_bytes: Optional[bytes] = None,
    bill_image_name: str = "bill.jpg",
) -> int:
    init_db()
    po = get_purchase_order_document(po_doc_id)
    if not po:
        raise ValueError("PO document not found")
    po_lines = {int(r["id"]): r for r in list_purchase_order_document_lines(po_doc_id)}
    vendor = get_vendor(int(po["vendor_id"]))
    if not vendor:
        raise ValueError("Vendor not found")
    if not lines:
        raise ValueError("At least one vendor bill line is required")
    bill_no = _next_doc_no("VB", "vendor_bill_docs", "bill_no")
    rel_img = (
        _save_document_upload_bytes("vendor_bills", f"vendor_bill_{bill_no}", bill_image_bytes, bill_image_name)
        if bill_image_bytes
        else None
    )
    base_total = gst_total = grand_total = 0.0
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO vendor_bill_docs (
                bill_no, vendor_id, po_doc_id, goods_receipt_id, status, bill_date, vendor_invoice_ref,
                vendor_gstin, bill_image_path, notes, base_total, gst_total, grand_total,
                match_status, match_summary, updated_at
            )
            VALUES (?, ?, ?, ?, 'recorded', ?, ?, ?, ?, ?, 0, 0, 0, 'pending', NULL, datetime('now'))
            """,
            (
                bill_no,
                int(po["vendor_id"]),
                int(po_doc_id),
                int(goods_receipt_id) if goods_receipt_id is not None else None,
                (bill_date or date.today().isoformat())[:10],
                (vendor_invoice_ref or None) or None,
                (vendor_gstin or vendor.issuer_gstin or None),
                rel_img,
                (notes or None) or None,
            ),
        )
        bill_id = int(cur.lastrowid)
        for line in lines:
            po_line_id = int(line.get("po_line_id") or 0)
            qty = float(line.get("quantity") or 0)
            unit = float(line.get("unit_cost") or 0)
            if po_line_id not in po_lines or qty <= 0 or unit < 0:
                raise ValueError("Each vendor bill line needs PO line, quantity, and unit cost")
            po_line = po_lines[po_line_id]
            lb, lg, lt = gst_add_exclusive(qty * unit, line.get("gst_rate_pct", po_line["gst_rate_pct"]))
            conn.execute(
                """
                INSERT INTO vendor_bill_lines (
                    vendor_bill_id, po_line_id, product_id, quantity, unit_cost, gst_rate_pct,
                    line_base_total, line_gst_total, line_grand_total
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bill_id,
                    po_line_id,
                    int(po_line["product_id"]),
                    qty,
                    unit,
                    float(line.get("gst_rate_pct", po_line["gst_rate_pct"]) or po_line["gst_rate_pct"] or 18),
                    lb,
                    lg,
                    lt,
                ),
            )
            base_total += lb
            gst_total += lg
            grand_total += lt
        conn.execute(
            """
            UPDATE vendor_bill_docs
            SET base_total = ?, gst_total = ?, grand_total = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (round(base_total, 2), round(gst_total, 2), round(grand_total, 2), bill_id),
        )
        _recompute_po_doc_status(conn, int(po_doc_id))
        conn.commit()
    _post_gl_purchase_bill(bill_id, grand_total)
    compare_vendor_bill_three_way(bill_id)
    return bill_id


def list_vendor_bill_documents() -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT b.*, p.doc_no AS po_doc_no, v.person_name AS vendor_name
            FROM vendor_bill_docs b
            JOIN purchase_order_docs p ON p.id = b.po_doc_id
            JOIN vendors v ON v.id = b.vendor_id
            ORDER BY b.created_at DESC, b.id DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def get_vendor_bill_document(bill_id: int) -> Optional[dict[str, Any]]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM vendor_bill_docs WHERE id = ?", (int(bill_id),)).fetchone()
    return dict(row) if row else None


def list_vendor_bill_lines(bill_id: int) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM vendor_bill_lines WHERE vendor_bill_id = ? ORDER BY id ASC", (int(bill_id),)).fetchall()
    return [dict(r) for r in rows]


def compare_vendor_bill_three_way(bill_id: int) -> dict[str, Any]:
    bill = get_vendor_bill_document(bill_id)
    if not bill:
        raise ValueError("Vendor bill not found")
    po_lines = {int(r["id"]): r for r in list_purchase_order_document_lines(int(bill["po_doc_id"]))}
    bill_lines = list_vendor_bill_lines(bill_id)
    findings: list[str] = []
    status = "matched"
    for line in bill_lines:
        po_line = po_lines.get(int(line["po_line_id"]))
        if not po_line:
            findings.append(f"PO line {line['po_line_id']} missing")
            status = "dispute"
            continue
        po_qty = float(po_line["quantity"])
        recv_qty = _received_qty_for_po_line(int(po_line["id"]))
        bill_qty = float(line["quantity"])
        po_rate = float(po_line["unit_cost"])
        bill_rate = float(line["unit_cost"])
        if bill_qty - recv_qty > 0.0001:
            findings.append(f"Line {po_line['line_no']}: billed qty {bill_qty:g} exceeds received {recv_qty:g}")
            status = "dispute"
        if recv_qty - po_qty > 0.0001:
            findings.append(f"Line {po_line['line_no']}: received qty {recv_qty:g} exceeds ordered {po_qty:g}")
            status = "dispute"
        if abs(bill_rate - po_rate) > 0.005:
            findings.append(f"Line {po_line['line_no']}: billed rate {bill_rate:.2f} differs from PO rate {po_rate:.2f}")
            status = "dispute"
        if status != "dispute" and (abs(bill_qty - recv_qty) > 0.0001 or abs(recv_qty - po_qty) > 0.0001):
            status = "variance"
            findings.append(f"Line {po_line['line_no']}: qty ordered {po_qty:g}, received {recv_qty:g}, billed {bill_qty:g}")
    summary = "Matched" if not findings else " | ".join(findings)
    with _connect() as conn:
        conn.execute(
            "UPDATE vendor_bill_docs SET match_status = ?, match_summary = ?, updated_at = datetime('now') WHERE id = ?",
            (status, summary, int(bill_id)),
        )
        row = conn.execute("SELECT po_doc_id FROM vendor_bill_docs WHERE id = ?", (int(bill_id),)).fetchone()
        if row and row["po_doc_id"] is not None:
            _recompute_po_doc_status(conn, int(row["po_doc_id"]))
        conn.commit()
    return {"match_status": status, "summary": summary, "bill_id": int(bill_id)}


def create_sales_order_document(
    customer_id: int,
    lines: Sequence[dict[str, Any]],
    *,
    notes: Optional[str] = None,
    gst_rate_pct: float = 18.0,
    warehouse_id: Optional[int] = None,
) -> int:
    init_db()
    customer = get_customer(int(customer_id))
    if not customer:
        raise ValueError("Customer not found")
    if not lines:
        raise ValueError("At least one sales order line is required")
    wh = get_default_warehouse() if warehouse_id is None else None
    wh_id = int(warehouse_id or (wh.id if wh else 0))
    doc_no = _next_doc_no("SO", "sales_order_docs")
    clean_lines: list[dict[str, Any]] = []
    for idx, line in enumerate(lines, start=1):
        pid = int(line.get("product_id") or 0)
        qty = float(line.get("quantity") or 0)
        unit_incl = float(line.get("unit_price_incl_gst") or 0)
        if pid <= 0 or qty <= 0 or unit_incl <= 0:
            raise ValueError("Each sales line needs product, positive quantity, and inclusive selling price")
        pr = get_vendor_product(pid)
        if not pr:
            raise ValueError(f"Product #{pid} not found")
        _, _, gross_unit = gst_split_inclusive(unit_incl, line.get("gst_rate_pct", gst_rate_pct))
        line_base, line_gst, line_total = gst_split_inclusive(qty * gross_unit, line.get("gst_rate_pct", gst_rate_pct))
        if stock_on_hand_v2(pid, wh_id) + 0.0001 < qty:
            raise ValueError(f"Not enough stock for {pr.our_product_id}")
        clean_lines.append(
            {
                "line_no": idx,
                "product_id": pid,
                "sku": pr.our_product_id,
                "item_name": pr.name,
                "quantity": qty,
                "unit_price_incl_gst": gross_unit,
                "gst_rate_pct": float(line.get("gst_rate_pct", gst_rate_pct) or gst_rate_pct),
                "line_base_total": line_base,
                "line_gst_total": line_gst,
                "line_grand_total": line_total,
                "notes": (line.get("notes") or None),
            }
        )
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO sales_order_docs (
                doc_no, customer_id, warehouse_id, status, gst_rate_pct, notes, updated_at
            )
            VALUES (?, ?, ?, 'placed', ?, ?, datetime('now'))
            """,
            (doc_no, int(customer_id), wh_id, float(gst_rate_pct), (notes or None) or None),
        )
        so_id = int(cur.lastrowid)
        for row in clean_lines:
            conn.execute(
                """
                INSERT INTO sales_order_doc_lines (
                    sales_order_id, line_no, product_id, sku, item_name, quantity, unit_price_incl_gst,
                    gst_rate_pct, line_base_total, line_gst_total, line_grand_total, notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    so_id,
                    row["line_no"],
                    row["product_id"],
                    row["sku"],
                    row["item_name"],
                    row["quantity"],
                    row["unit_price_incl_gst"],
                    row["gst_rate_pct"],
                    row["line_base_total"],
                    row["line_gst_total"],
                    row["line_grand_total"],
                    row["notes"],
                ),
            )
        conn.commit()
    _wa_sales_order_doc_booked(so_id)
    return so_id


def list_sales_order_documents() -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT s.*, c.name AS customer_name, c.company_name
            FROM sales_order_docs s
            JOIN customers c ON c.id = s.customer_id
            ORDER BY s.created_at DESC, s.id DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def get_sales_order_document(so_id: int) -> Optional[dict[str, Any]]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM sales_order_docs WHERE id = ?", (int(so_id),)).fetchone()
    return dict(row) if row else None


def list_sales_order_document_lines(so_id: int) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM sales_order_doc_lines WHERE sales_order_id = ? ORDER BY line_no ASC", (int(so_id),)).fetchall()
    return [dict(r) for r in rows]


def create_delivery_document(
    sales_order_id: int,
    lines: Sequence[dict[str, Any]],
    *,
    delivery_receipt_number: Optional[str] = None,
    delivery_contact: Optional[str] = None,
    notes: Optional[str] = None,
    receipt_image_bytes: Optional[bytes] = None,
    receipt_image_name: str = "delivery.jpg",
) -> int:
    init_db()
    so = get_sales_order_document(sales_order_id)
    if not so:
        raise ValueError("Sales order not found")
    so_lines = {int(r["id"]): r for r in list_sales_order_document_lines(sales_order_id)}
    if not lines:
        raise ValueError("At least one delivery line is required")
    delivery_no = _next_doc_no("DN", "delivery_docs", "delivery_no")
    rel_img = (
        _save_document_upload_bytes("deliveries", f"delivery_{delivery_no}", receipt_image_bytes, receipt_image_name)
        if receipt_image_bytes
        else None
    )
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO delivery_docs (
                delivery_no, sales_order_id, warehouse_id, status, delivery_receipt_number,
                delivery_contact, receipt_image_path, notes, updated_at
            )
            VALUES (?, ?, ?, 'posted', ?, ?, ?, ?, datetime('now'))
            """,
            (
                delivery_no,
                int(sales_order_id),
                int(so["warehouse_id"]),
                (delivery_receipt_number or None) or None,
                (delivery_contact or None) or None,
                rel_img,
                (notes or None) or None,
            ),
        )
        did = int(cur.lastrowid)
        for line in lines:
            so_line_id = int(line.get("sales_order_line_id") or 0)
            qty = float(line.get("quantity") or 0)
            if so_line_id not in so_lines or qty <= 0:
                raise ValueError("Each delivery line needs a valid sales order line and positive quantity")
            so_line = so_lines[so_line_id]
            if stock_on_hand_v2(int(so_line["product_id"]), int(so["warehouse_id"]), conn=conn) + 0.0001 < qty:
                raise ValueError(f"Not enough stock for line {so_line['line_no']}")
            conn.execute(
                """
                INSERT INTO delivery_lines (
                    delivery_doc_id, sales_order_line_id, product_id, quantity, unit_price_incl_gst
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    did,
                    so_line_id,
                    int(so_line["product_id"]),
                    qty,
                    float(so_line["unit_price_incl_gst"]),
                ),
            )
            _post_stock_movement(
                conn,
                warehouse_id=int(so["warehouse_id"]),
                product_id=int(so_line["product_id"]),
                movement_type="delivery",
                quantity=-qty,
                ref_type="delivery",
                ref_id=did,
                ref_line_id=so_line_id,
                notes=(notes or line.get("notes")),
            )
        conn.execute(
            "UPDATE sales_order_docs SET status = 'shipped', updated_at = datetime('now') WHERE id = ?",
            (int(sales_order_id),),
        )
        conn.commit()
    _wa_delivery_doc_update(did)
    return did


def list_delivery_documents() -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT d.*, s.doc_no AS sales_order_no, c.name AS customer_name
            FROM delivery_docs d
            JOIN sales_order_docs s ON s.id = d.sales_order_id
            JOIN customers c ON c.id = s.customer_id
            ORDER BY d.created_at DESC, d.id DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def create_customer_invoice_document(
    sales_order_id: int,
    *,
    delivery_doc_id: Optional[int] = None,
    invoice_date: Optional[str] = None,
    notes: Optional[str] = None,
) -> int:
    from bill_pdf import build_multi_line_document_pdf

    init_db()
    so = get_sales_order_document(sales_order_id)
    if not so:
        raise ValueError("Sales order not found")
    customer = get_customer(int(so["customer_id"]))
    if not customer:
        raise ValueError("Customer not found")
    lines = list_sales_order_document_lines(sales_order_id)
    if not lines:
        raise ValueError("Sales order has no lines")
    invoice_no = _next_doc_no("INV", "customer_invoice_docs", "invoice_no")
    base_total = sum(float(r["line_base_total"]) for r in lines)
    gst_total = sum(float(r["line_gst_total"]) for r in lines)
    grand_total = sum(float(r["line_grand_total"]) for r in lines)
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO customer_invoice_docs (
                invoice_no, sales_order_id, customer_id, delivery_doc_id, status, invoice_date,
                gst_rate_pct, notes, base_total, gst_total, grand_total, updated_at
            )
            VALUES (?, ?, ?, ?, 'issued', ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                invoice_no,
                int(sales_order_id),
                int(so["customer_id"]),
                int(delivery_doc_id) if delivery_doc_id is not None else None,
                (invoice_date or date.today().isoformat())[:10],
                float(so.get("gst_rate_pct") or 18.0),
                (notes or so.get("notes") or None),
                round(base_total, 2),
                round(gst_total, 2),
                round(grand_total, 2),
            ),
        )
        inv_id = int(cur.lastrowid)
        for line in lines:
            conn.execute(
                """
                INSERT INTO customer_invoice_lines (
                    customer_invoice_id, sales_order_line_id, product_id, quantity, unit_price_incl_gst,
                    gst_rate_pct, line_base_total, line_gst_total, line_grand_total
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    inv_id,
                    int(line["id"]),
                    int(line["product_id"]),
                    float(line["quantity"]),
                    float(line["unit_price_incl_gst"]),
                    float(line["gst_rate_pct"]),
                    float(line["line_base_total"]),
                    float(line["line_gst_total"]),
                    float(line["line_grand_total"]),
                ),
            )
        conn.commit()
    pdf_bytes = build_multi_line_document_pdf(
        title="TAX INVOICE",
        doc_no=invoice_no,
        doc_date=(invoice_date or date.today().isoformat())[:10],
        party_heading="Customer",
        party_name=customer.name,
        party_company=customer.company_name,
        party_phone=customer.phone,
        party_address=customer.address,
        meta_rows=[
            ["Sales order", str(so["doc_no"])],
            ["Status", str(so.get("status") or "shipped").title()],
        ],
        line_rows=[
            {
                "sku": r["sku"],
                "item_name": r["item_name"],
                "quantity": r["quantity"],
                "unit_rate": r["unit_price_incl_gst"],
                "base_total": r["line_base_total"],
                "gst_total": r["line_gst_total"],
                "grand_total": r["line_grand_total"],
            }
            for r in lines
        ],
        total_rows=[
            ["Taxable total", f"Rs. {base_total:,.2f}"],
            ["GST total", f"Rs. {gst_total:,.2f}"],
            ["Invoice total", f"Rs. {grand_total:,.2f}"],
        ],
        notes=notes or so.get("notes"),
        seller=_default_seller_snapshot(),
        subtitle="Selling price entered in the system is GST-inclusive; taxable value and GST are split automatically.",
    )
    cogs = 0.0
    for line in lines:
        pr = get_vendor_product(int(line["product_id"]))
        cogs += float(line["quantity"]) * float(pr.cost_price or 0.0) if pr else 0.0
    _post_gl_sale_cogs(inv_id, grand_total, cogs)
    rel_pdf = _save_document_upload_bytes("customer_invoices", f"invoice_{inv_id:05d}", pdf_bytes, f"{invoice_no}.pdf")
    with _connect() as conn:
        conn.execute(
            "UPDATE customer_invoice_docs SET pdf_path = ?, updated_at = datetime('now') WHERE id = ?",
            (rel_pdf, int(inv_id)),
        )
        conn.commit()
    return inv_id


def list_customer_invoice_documents() -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT i.*, s.doc_no AS sales_order_no, c.name AS customer_name
            FROM customer_invoice_docs i
            JOIN sales_order_docs s ON s.id = i.sales_order_id
            JOIN customers c ON c.id = i.customer_id
            ORDER BY i.created_at DESC, i.id DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def get_document_history(entity_type: str, entity_id: int) -> dict[str, list[dict[str, Any]]]:
    init_db()
    et = (entity_type or "").strip().lower()
    eid = int(entity_id)
    out: dict[str, list[dict[str, Any]]] = {
        "purchase_orders": [],
        "goods_receipts": [],
        "vendor_bills": [],
        "sales_orders": [],
        "deliveries": [],
        "customer_invoices": [],
    }
    with _connect() as conn:
        if et == "vendor":
            out["purchase_orders"] = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM purchase_order_docs WHERE vendor_id = ? ORDER BY created_at DESC, id DESC",
                    (eid,),
                ).fetchall()
            ]
            out["vendor_bills"] = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM vendor_bill_docs WHERE vendor_id = ? ORDER BY created_at DESC, id DESC",
                    (eid,),
                ).fetchall()
            ]
        elif et == "customer":
            out["sales_orders"] = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM sales_order_docs WHERE customer_id = ? ORDER BY created_at DESC, id DESC",
                    (eid,),
                ).fetchall()
            ]
            out["customer_invoices"] = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM customer_invoice_docs WHERE customer_id = ? ORDER BY created_at DESC, id DESC",
                    (eid,),
                ).fetchall()
            ]
        elif et == "product":
            out["purchase_orders"] = [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT DISTINCT p.*
                    FROM purchase_order_docs p
                    JOIN purchase_order_doc_lines l ON l.po_doc_id = p.id
                    WHERE l.product_id = ?
                    ORDER BY p.created_at DESC, p.id DESC
                    """,
                    (eid,),
                ).fetchall()
            ]
            out["goods_receipts"] = [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT DISTINCT g.*
                    FROM goods_receipt_docs g
                    JOIN goods_receipt_lines l ON l.goods_receipt_id = g.id
                    WHERE l.product_id = ?
                    ORDER BY g.created_at DESC, g.id DESC
                    """,
                    (eid,),
                ).fetchall()
            ]
            out["vendor_bills"] = [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT DISTINCT b.*
                    FROM vendor_bill_docs b
                    JOIN vendor_bill_lines l ON l.vendor_bill_id = b.id
                    WHERE l.product_id = ?
                    ORDER BY b.created_at DESC, b.id DESC
                    """,
                    (eid,),
                ).fetchall()
            ]
            out["sales_orders"] = [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT DISTINCT s.*
                    FROM sales_order_docs s
                    JOIN sales_order_doc_lines l ON l.sales_order_id = s.id
                    WHERE l.product_id = ?
                    ORDER BY s.created_at DESC, s.id DESC
                    """,
                    (eid,),
                ).fetchall()
            ]
            out["deliveries"] = [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT DISTINCT d.*
                    FROM delivery_docs d
                    JOIN delivery_lines l ON l.delivery_doc_id = d.id
                    WHERE l.product_id = ?
                    ORDER BY d.created_at DESC, d.id DESC
                    """,
                    (eid,),
                ).fetchall()
            ]
            out["customer_invoices"] = [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT DISTINCT i.*
                    FROM customer_invoice_docs i
                    JOIN customer_invoice_lines l ON l.customer_invoice_id = i.id
                    WHERE l.product_id = ?
                    ORDER BY i.created_at DESC, i.id DESC
                    """,
                    (eid,),
                ).fetchall()
            ]
    return out


def list_sales_line_rows(
    start_iso: str, end_iso: str, category_sub: str = ""
) -> list[dict]:
    """Order lines in date range; revenue = qty × unit_price. Dates: YYYY-MM-DD (inclusive)."""
    init_db()
    t0 = (start_iso or "1970-01-01")[:10]
    t1 = (end_iso or "2099-12-31")[:10]
    wcat = ""
    args: list[object] = [t0, t1]
    cs = (category_sub or "").strip()
    if cs:
        wcat = "AND LOWER(TRIM(COALESCE(vp.category, ''))) LIKE LOWER(?) "
        args.append(f"%{cs}%")
    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT
                co.id AS order_id, co.created_at, co.status,
                co.quantity, co.unit_price, (co.quantity * co.unit_price) AS line_revenue,
                co.customer_id, c.name AS customer_name,
                co.product_id, vp.our_product_id, vp.name AS product_name,
                COALESCE(NULLIF(TRIM(vp.category), ''), '(uncategorized)') AS category
            FROM customer_orders co
            JOIN customers c ON c.id = co.customer_id
            JOIN vendor_products vp ON vp.id = co.product_id
            WHERE date(co.created_at) >= date(?) AND date(co.created_at) <= date(?)
              AND {_sales_pipeline_where()}
            {wcat}
            ORDER BY co.created_at DESC, co.id DESC
            """,
            args,
        ).fetchall()
    return [dict(x) for x in rows]


def sales_revenue_series(
    start_iso: str, end_iso: str, grain: str
) -> list[dict]:
    """Bucket pipeline order revenue by day, week, or month (YYYY-MM-DD range inclusive)."""
    from collections import defaultdict
    from datetime import date, datetime

    rows = list_sales_line_rows(start_iso, end_iso, "")
    g = (grain or "day").strip().lower()
    b: dict[str, float] = defaultdict(float)
    for r in rows:
        ca = (r.get("created_at") or "")[:19]
        try:
            d = datetime.fromisoformat(
                (ca + "T00:00:00" if "T" not in ca and len(ca) == 10 else ca).replace(" ", "T")
            ).date()
        except (TypeError, ValueError):
            continue
        if g == "month":
            key = f"{d.year:04d}-{d.month:02d}"
        elif g == "week":
            ic = d.isocalendar()
            key = f"{ic[0]}-W{ic[1]:02d}"
        else:
            key = d.isoformat()
        b[key] += float(r.get("line_revenue") or 0.0)
    srt = sorted(b.items(), key=lambda x: x[0])
    return [{"period": a, "revenue": round(v, 2)} for a, v in srt]


def top_categories_by_revenue(
    start_iso: str, end_iso: str, n: int = 12
) -> list[dict]:
    init_db()
    rows = list_sales_line_rows(start_iso, end_iso, "")
    bucket: dict[str, float] = {}
    for r in rows:
        c = r.get("category") or "(uncategorized)"
        bucket[c] = bucket.get(c, 0.0) + float(r.get("line_revenue") or 0.0)
    srt = sorted(bucket.items(), key=lambda x: -x[1])[: max(1, n)]
    return [{"category": a, "revenue": round(b, 2)} for a, b in srt]


def top_products_by_revenue(
    start_iso: str, end_iso: str, n: int = 12
) -> list[dict]:
    init_db()
    rows = list_sales_line_rows(start_iso, end_iso, "")
    bucket: dict[str, float] = {}
    labels: dict[str, str] = {}
    for r in rows:
        k = f"{r.get('our_product_id', '')}::{int(r.get('product_id', 0))}"
        labels[k] = f"{r.get('our_product_id', '')} — {r.get('product_name', '')}"
        bucket[k] = bucket.get(k, 0.0) + float(r.get("line_revenue") or 0.0)
    srt = sorted(bucket.items(), key=lambda x: -x[1])[: max(1, n)]
    out: list[dict] = []
    for k, v in srt:
        _pid = int(k.split("::")[-1])
        out.append(
            {
                "product_id": _pid,
                "label": labels.get(k) or k,
                "revenue": round(v, 2),
            }
        )
    return out


def customers_who_bought_category(
    category_sub: str, start_iso: str, end_iso: str
) -> list[dict]:
    """Distinct customers with revenue in a category (substring match)."""
    init_db()
    if not (category_sub or "").strip():
        return []
    rows = list_sales_line_rows(start_iso, end_iso, category_sub.strip())
    m: dict[int, dict] = {}
    for r in rows:
        cid = int(r["customer_id"])
        rev = float(r.get("line_revenue") or 0.0)
        if cid not in m:
            m[cid] = {"customer_id": cid, "name": r["customer_name"], "revenue": 0.0}
        m[cid]["revenue"] = round(m[cid]["revenue"] + rev, 2)
    return sorted(m.values(), key=lambda x: -x["revenue"])


def get_vendors_with_product_count() -> int:
    """Count of vendors that have at least one product."""
    init_db()
    with _connect() as conn:
        c = int(
            conn.execute(
                "SELECT COUNT(DISTINCT vendor_id) AS c FROM vendor_products"
            ).fetchone()["c"]
        )
    return c


def list_customers() -> List[Customer]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, name, company_name, phone, alternate_phone, address, password_hash, created_at "
            "FROM customers ORDER BY name"
        ).fetchall()
    return [Customer(**dict(r)) for r in rows]


def get_customer(cid: int) -> Optional[Customer]:
    with _connect() as conn:
        r = conn.execute("SELECT * FROM customers WHERE id = ?", (cid,)).fetchone()
    return Customer(**dict(r)) if r else None


def insert_customer(
    name: str,
    company_name: str,
    phone: str,
    alt_phone: str,
    address: str,
    plain_password: str,
) -> int:
    h = hash_password(plain_password)
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO customers (name, company_name, phone, alternate_phone, address, password_hash)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (name.strip(), (company_name or None), phone.strip(), (alt_phone or None), (address or None), h),
        )
        conn.commit()
        cid = int(cur.lastrowid)
    # Meta WhatsApp — `templates/account_creation.py` + `send_wa_for_new_account_safe`. Token: `.env`.
    if (os.environ.get("WHATSAPP_DISABLE") or "").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        try:
            from whatsapp_meta import send_wa_for_new_account_safe

            send_wa_for_new_account_safe(
                name.strip(), phone.strip(), plain_password
            )
        except Exception as ex:
            print("WhatsApp welcome (ignored):", ex, file=sys.stderr)
    return cid


def update_customer(
    cid: int,
    name: str,
    company_name: str,
    phone: str,
    alt_phone: str,
    address: str,
    new_password: Optional[str],
) -> None:
    if new_password and new_password.strip():
        h = hash_password(new_password.strip())
        with _connect() as conn:
            conn.execute(
                """
                UPDATE customers SET
                    name = ?, company_name = ?, phone = ?, alternate_phone = ?, address = ?,
                    password_hash = ?
                WHERE id = ?
                """,
                (
                    name.strip(),
                    (company_name or None),
                    phone.strip(),
                    (alt_phone or None),
                    (address or None),
                    h,
                    cid,
                ),
            )
            conn.commit()
    else:
        with _connect() as conn:
            conn.execute(
                """
                UPDATE customers SET
                    name = ?, company_name = ?, phone = ?, alternate_phone = ?, address = ?
                WHERE id = ?
                """,
                (
                    name.strip(),
                    (company_name or None),
                    phone.strip(),
                    (alt_phone or None),
                    (address or None),
                    cid,
                ),
            )
            conn.commit()


def delete_customer(cid: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM customers WHERE id = ?", (cid,))
        conn.commit()


def list_vendors() -> List[Vendor]:
    init_db()
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM vendors ORDER BY person_name").fetchall()
    return [Vendor(**dict(r)) for r in rows]


def get_vendor(vid: int) -> Optional[Vendor]:
    init_db()
    with _connect() as conn:
        r = conn.execute("SELECT * FROM vendors WHERE id = ?", (vid,)).fetchone()
    return Vendor(**dict(r)) if r else None


def insert_vendor(
    person_name: str,
    company_name: str,
    primary_phone: str,
    secondary_phone: str,
    payment_terms: Optional[int],
    billing: Optional[int],
    notes: str,
    issuer_legal_name: Optional[str] = None,
    issuer_address: Optional[str] = None,
    issuer_city_pin: Optional[str] = None,
    issuer_gstin: Optional[str] = None,
    issuer_phone: Optional[str] = None,
    issuer_email: Optional[str] = None,
) -> int:
    init_db()
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO vendors (person_name, company_name, primary_phone, secondary_phone,
                payment_terms, billing, notes,
                issuer_legal_name, issuer_address, issuer_city_pin, issuer_gstin, issuer_phone, issuer_email)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                person_name.strip(),
                (company_name or None) or None,
                primary_phone.strip(),
                (secondary_phone or None) or None,
                payment_terms,
                billing,
                (notes or None) or None,
                (issuer_legal_name or None) or None,
                (issuer_address or None) or None,
                (issuer_city_pin or None) or None,
                (issuer_gstin or None) or None,
                (issuer_phone or None) or None,
                (issuer_email or None) or None,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def update_vendor(
    vid: int,
    person_name: str,
    company_name: str,
    primary_phone: str,
    secondary_phone: str,
    payment_terms: Optional[int],
    billing: Optional[int],
    notes: str,
    issuer_legal_name: Optional[str] = None,
    issuer_address: Optional[str] = None,
    issuer_city_pin: Optional[str] = None,
    issuer_gstin: Optional[str] = None,
    issuer_phone: Optional[str] = None,
    issuer_email: Optional[str] = None,
) -> None:
    init_db()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE vendors SET
                person_name = ?, company_name = ?, primary_phone = ?, secondary_phone = ?,
                payment_terms = ?, billing = ?, notes = ?,
                issuer_legal_name = ?, issuer_address = ?, issuer_city_pin = ?,
                issuer_gstin = ?, issuer_phone = ?, issuer_email = ?
            WHERE id = ?
            """,
            (
                person_name.strip(),
                (company_name or None) or None,
                primary_phone.strip(),
                (secondary_phone or None) or None,
                payment_terms,
                billing,
                (notes or None) or None,
                (issuer_legal_name or None) or None,
                (issuer_address or None) or None,
                (issuer_city_pin or None) or None,
                (issuer_gstin or None) or None,
                (issuer_phone or None) or None,
                (issuer_email or None) or None,
                vid,
            ),
        )
        conn.commit()


def _purge_vendor_dependencies(vendor_id: int) -> None:
    """Remove rows that FK-block deleting this vendor (doc POs, bills, legacy PO/AP, stock)."""
    vid = int(vendor_id)
    with _connect() as conn:
        if not conn.execute("SELECT 1 FROM vendors WHERE id = ?", (vid,)).fetchone():
            raise ValueError("Vendor not found")
        pids = [int(r["id"]) for r in conn.execute(
            "SELECT id FROM vendor_products WHERE vendor_id = ?", (vid,)
        ).fetchall()]
    if pids:
        qs = ",".join("?" * len(pids))
        with _connect() as conn:
            checks: list[tuple[str, str]] = [
                (
                    f"SELECT COUNT(*) AS c FROM customer_orders WHERE product_id IN ({qs})",
                    "customer order(s)",
                ),
                (
                    f"SELECT COUNT(*) AS c FROM customer_order_billings WHERE product_id IN ({qs})",
                    "customer billing row(s)",
                ),
                (
                    f"SELECT COUNT(*) AS c FROM sales_order_doc_lines WHERE product_id IN ({qs})",
                    "sales order line(s)",
                ),
                (
                    f"SELECT COUNT(*) AS c FROM customer_invoice_lines WHERE product_id IN ({qs})",
                    "customer invoice line(s)",
                ),
                (
                    f"SELECT COUNT(*) AS c FROM delivery_lines WHERE product_id IN ({qs})",
                    "delivery line(s)",
                ),
            ]
            parts: list[str] = []
            for sql, label in checks:
                n = int(conn.execute(sql, pids).fetchone()["c"])
                if n:
                    parts.append(f"{n} {label}")
            if parts:
                raise ValueError(
                    "Cannot delete vendor: "
                    + "; ".join(parts)
                    + ". Remove or change those records first."
                )

    with _connect() as conn:
        ap_doc = [
            int(r["id"])
            for r in conn.execute(
                """
                SELECT p.id FROM ap_payments p
                JOIN vendor_bill_docs b ON b.id = p.vendor_bill_doc_id
                WHERE b.vendor_id = ?
                """,
                (vid,),
            ).fetchall()
        ]
    for ap_id in ap_doc:
        delete_ap_payment(ap_id)

    with _connect() as conn:
        conn.execute("DELETE FROM vendor_bill_docs WHERE vendor_id = ?", (vid,))
        conn.commit()

    with _connect() as conn:
        gr_rows = conn.execute(
            """
            SELECT g.id FROM goods_receipt_docs g
            JOIN purchase_order_docs p ON p.id = g.po_doc_id
            WHERE p.vendor_id = ?
            """,
            (vid,),
        ).fetchall()
        gr_ids = [int(r["id"]) for r in gr_rows]
    if gr_ids:
        gqs = ",".join("?" * len(gr_ids))
        with _connect() as conn:
            conn.execute(
                f"DELETE FROM stock_movements WHERE ref_type = 'goods_receipt' AND ref_id IN ({gqs})",
                gr_ids,
            )
            conn.execute(f"DELETE FROM goods_receipt_docs WHERE id IN ({gqs})", gr_ids)
            conn.commit()

    with _connect() as conn:
        conn.execute("DELETE FROM purchase_order_docs WHERE vendor_id = ?", (vid,))
        conn.commit()

    if pids:
        pqs = ",".join("?" * len(pids))
        with _connect() as conn:
            conn.execute(
                f"DELETE FROM stock_movements WHERE product_id IN ({pqs})",
                pids,
            )
            conn.execute(f"DELETE FROM stock_receipts WHERE product_id IN ({pqs})", pids)
            conn.commit()

    with _connect() as conn:
        ap_legacy = [
            int(r["id"])
            for r in conn.execute(
                """
                SELECT p.id FROM ap_payments p
                JOIN po_billings b ON b.id = p.po_billing_id
                WHERE b.vendor_id = ?
                """,
                (vid,),
            ).fetchall()
        ]
    for ap_id in ap_legacy:
        delete_ap_payment(ap_id)

    with _connect() as conn:
        pob_ids = [
            int(r["id"])
            for r in conn.execute(
                "SELECT id FROM po_billings WHERE vendor_id = ?", (vid,)
            ).fetchall()
        ]
    for bid in pob_ids:
        delete_po_billing(bid)

    with _connect() as conn:
        conn.execute("DELETE FROM purchase_orders WHERE vendor_id = ?", (vid,))
        conn.commit()


def delete_vendor(vid: int) -> None:
    init_db()
    _purge_vendor_dependencies(int(vid))
    with _connect() as conn:
        pids = conn.execute(
            "SELECT id FROM vendor_products WHERE vendor_id = ?", (int(vid),)
        ).fetchall()
    for r in pids:
        _rmtree_product_dir(int(r["id"]))
    with _connect() as conn:
        conn.execute("DELETE FROM vendors WHERE id = ?", (int(vid),))
        conn.commit()


def product_image_rel_paths(stored: Optional[str]) -> list[str]:
    return _load_image_paths(stored)


def list_vendor_products() -> List[VendorProduct]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, vendor_id, vendor_product_id, our_product_id, name, category, cost_price, tax_rate,
                tax_inclusive, image_paths, low_stock_threshold, created_at
            FROM vendor_products
            ORDER BY name, our_product_id
            """
        ).fetchall()
    return [VendorProduct(**dict(r)) for r in rows]


def list_vendor_products_by_vendor(vendor_id: int) -> List[VendorProduct]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, vendor_id, vendor_product_id, our_product_id, name, category, cost_price, tax_rate,
                tax_inclusive, image_paths, low_stock_threshold, created_at
            FROM vendor_products
            WHERE vendor_id = ?
            ORDER BY name, our_product_id
            """,
            (vendor_id,),
        ).fetchall()
    return [VendorProduct(**dict(r)) for r in rows]


def get_vendor_product(pid: int) -> Optional[VendorProduct]:
    init_db()
    with _connect() as conn:
        r = conn.execute("SELECT * FROM vendor_products WHERE id = ?", (pid,)).fetchone()
    return VendorProduct(**dict(r)) if r else None


def insert_vendor_product(
    vendor_id: int,
    vendor_product_id: str,
    our_product_id: str,
    name: str,
    category: Optional[str],
    cost_price: Optional[float],
    tax_rate: Optional[float],
    tax_inclusive: Optional[int],
    low_stock_threshold: Optional[float] = None,
) -> int:
    init_db()
    cat = (category or "").strip() or None
    th = None if low_stock_threshold is None else float(low_stock_threshold)
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO vendor_products (vendor_id, vendor_product_id, our_product_id, name, category,
                cost_price, tax_rate, tax_inclusive, image_paths, low_stock_threshold)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                vendor_id,
                vendor_product_id.strip(),
                our_product_id.strip(),
                name.strip(),
                cat,
                cost_price,
                tax_rate,
                tax_inclusive,
                _dump_image_paths([]),
                th,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def set_vendor_product_image_paths(pid: int, paths: list[str]) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE vendor_products SET image_paths = ? WHERE id = ?",
            (_dump_image_paths(paths), pid),
        )
        conn.commit()


def update_vendor_product(
    pid: int,
    vendor_id: int,
    vendor_product_id: str,
    our_product_id: str,
    name: str,
    category: Optional[str],
    cost_price: Optional[float],
    tax_rate: Optional[float],
    tax_inclusive: Optional[int],
    image_paths: list[str],
    low_stock_threshold: Optional[float] = None,
) -> None:
    init_db()
    cat = (category or "").strip() or None
    th = None if low_stock_threshold is None else float(low_stock_threshold)
    with _connect() as conn:
        conn.execute(
            """
            UPDATE vendor_products SET
                vendor_id = ?,
                vendor_product_id = ?,
                our_product_id = ?,
                name = ?,
                category = ?,
                cost_price = ?,
                tax_rate = ?,
                tax_inclusive = ?,
                image_paths = ?,
                low_stock_threshold = ?
            WHERE id = ?
            """,
            (
                vendor_id,
                vendor_product_id.strip(),
                our_product_id.strip(),
                name.strip(),
                cat,
                cost_price,
                tax_rate,
                tax_inclusive,
                _dump_image_paths(image_paths),
                th,
                pid,
            ),
        )
        conn.commit()


def delete_vendor_product(pid: int) -> None:
    init_db()
    with _connect() as conn:
        n = int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM purchase_orders WHERE product_id = ?",
                (pid,),
            ).fetchone()["c"]
        )
        n2 = int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM stock_receipts WHERE product_id = ?",
                (pid,),
            ).fetchone()["c"]
        )
    if n:
        raise ValueError(
            f"Cannot delete this product: {n} purchase order(s) reference it. Remove or change those POs first."
        )
    if n2:
        raise ValueError(
            f"Cannot delete: {n2} stock / receipt line(s) use this product. Remove or edit those first."
        )
    p = get_vendor_product(pid)
    if p:
        _remove_product_files_by_rel_list(product_image_rel_paths(p.image_paths))
    _rmtree_product_dir(pid)
    with _connect() as conn:
        conn.execute("DELETE FROM vendor_products WHERE id = ?", (pid,))
        conn.commit()


def list_purchase_orders() -> List[PurchaseOrder]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM purchase_orders ORDER BY created_at DESC, id DESC"
        ).fetchall()
    return [PurchaseOrder(**dict(r)) for r in rows]


def get_purchase_order(poid: int) -> Optional[PurchaseOrder]:
    init_db()
    with _connect() as conn:
        r = conn.execute("SELECT * FROM purchase_orders WHERE id = ?", (poid,)).fetchone()
    return PurchaseOrder(**dict(r)) if r else None


def _recompute_po_status(conn, po_id: int) -> None:
    o = conn.execute("SELECT * FROM purchase_orders WHERE id = ?", (po_id,)).fetchone()
    if not o:
        return
    st = (dict(o).get("status") or "open").strip()
    if st == "in_dispute":
        return
    tot = float(
        conn.execute(
            "SELECT COALESCE(SUM(quantity), 0) AS s FROM stock_receipts WHERE po_id = ?",
            (po_id,),
        ).fetchone()["s"]
    )
    order_q = max(float(o["quantity"]), 0.0)
    if tot <= 0.0:
        new = "open"
    elif order_q > 0 and tot >= order_q - 0.0001:
        new = "closed"
    else:
        new = "in_progress"
    if new != st:
        conn.execute("UPDATE purchase_orders SET status = ? WHERE id = ?", (new, po_id))


def sum_received_for_po(po_id: int) -> float:
    init_db()
    with _connect() as conn:
        return float(
            conn.execute(
                "SELECT COALESCE(SUM(quantity), 0) AS s FROM stock_receipts WHERE po_id = ?",
                (po_id,),
            ).fetchone()["s"]
        )


def get_po_status_counts() -> Dict[str, int]:
    init_db()
    with _connect() as conn:
        cur = conn.execute("SELECT status, COUNT(*) AS c FROM purchase_orders GROUP BY status")
        m = {str(r["status"] or "open").strip(): int(r["c"]) for r in cur.fetchall()}
    for s in ("open", "in_progress", "closed", "in_dispute"):
        m.setdefault(s, 0)
    return m


def insert_purchase_order(
    vendor_id: int,
    product_id: int,
    quantity: float,
    unit_cost: float,
    payment_terms: Optional[int],
    billing: Optional[int],
    tax_rate: Optional[float],
    tax_inclusive: Optional[int],
    notes: str,
    transport_name: Optional[str],
    transport_number: Optional[str],
) -> int:
    init_db()
    tname = (transport_name or None) and (transport_name or "").strip() or None
    tno = (transport_number or None) and (transport_number or "").strip() or None
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO purchase_orders (vendor_id, product_id, quantity, unit_cost, payment_terms, billing,
                tax_rate, tax_inclusive, notes, status, transport_name, transport_number)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)
            """,
            (
                vendor_id,
                product_id,
                float(quantity),
                float(unit_cost),
                payment_terms,
                billing,
                tax_rate,
                tax_inclusive,
                (notes or None) or None,
                tname,
                tno,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def update_purchase_order(
    poid: int,
    vendor_id: int,
    product_id: int,
    quantity: float,
    unit_cost: float,
    payment_terms: Optional[int],
    billing: Optional[int],
    tax_rate: Optional[float],
    tax_inclusive: Optional[int],
    notes: str,
    status: str,
    transport_name: Optional[str],
    transport_number: Optional[str],
) -> None:
    init_db()
    st = (status or "open").strip() or "open"
    tname = (transport_name or None) and (transport_name or "").strip() or None
    tno = (transport_number or None) and (transport_number or "").strip() or None
    with _connect() as conn:
        conn.execute(
            """
            UPDATE purchase_orders SET
                vendor_id = ?,
                product_id = ?,
                quantity = ?,
                unit_cost = ?,
                payment_terms = ?,
                billing = ?,
                tax_rate = ?,
                tax_inclusive = ?,
                notes = ?,
                status = ?,
                transport_name = ?,
                transport_number = ?
            WHERE id = ?
            """,
            (
                vendor_id,
                product_id,
                float(quantity),
                float(unit_cost),
                payment_terms,
                billing,
                tax_rate,
                tax_inclusive,
                (notes or None) or None,
                st,
                tname,
                tno,
                poid,
            ),
        )
        _recompute_po_status(conn, poid)
        conn.commit()


def delete_purchase_order(poid: int) -> None:
    init_db()
    with _connect() as conn:
        n = int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM stock_receipts WHERE po_id = ?",
                (poid,),
            ).fetchone()["c"]
        )
    if n:
        raise ValueError(
            f"Cannot delete: {n} stock receipt line(s) reference this PO. Remove or move those first."
        )
    with _connect() as conn:
        conn.execute("DELETE FROM purchase_orders WHERE id = ?", (poid,))
        conn.commit()


def insert_stock_receipt(
    product_id: int,
    po_id: Optional[int],
    quantity: float,
    shipment_id: Optional[str],
    grn_number: Optional[str],
    selling_price: Optional[float],
    notes: str,
) -> int:
    init_db()
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO stock_receipts (product_id, po_id, quantity, shipment_id, grn_number, selling_price, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                product_id,
                int(po_id) if po_id is not None else None,
                float(quantity),
                (shipment_id or None) and (shipment_id or "").strip() or None,
                (grn_number or None) and (grn_number or "").strip() or None,
                selling_price,
                (notes or None) or None,
            ),
        )
        rid = int(cur.lastrowid)
        if po_id is not None:
            _recompute_po_status(conn, int(po_id))
        conn.commit()
    return rid


def update_stock_receipt(
    rid: int,
    product_id: int,
    po_id: Optional[int],
    quantity: float,
    shipment_id: Optional[str],
    grn_number: Optional[str],
    selling_price: Optional[float],
    notes: str,
) -> None:
    init_db()
    with _connect() as conn:
        ro = conn.execute("SELECT po_id FROM stock_receipts WHERE id = ?", (rid,)).fetchone()
        old_poid = int(ro["po_id"]) if ro and ro["po_id"] is not None else None
        conn.execute(
            """
            UPDATE stock_receipts SET
                product_id = ?, po_id = ?, quantity = ?, shipment_id = ?, grn_number = ?,
                selling_price = ?, notes = ?
            WHERE id = ?
            """,
            (
                product_id,
                int(po_id) if po_id is not None else None,
                float(quantity),
                (shipment_id or None) and (shipment_id or "").strip() or None,
                (grn_number or None) and (grn_number or "").strip() or None,
                selling_price,
                (notes or None) or None,
                rid,
            ),
        )
        pids = {p for p in (old_poid, po_id) if p is not None}
        for p in pids:
            _recompute_po_status(conn, int(p))
        conn.commit()


def delete_stock_receipt(rid: int) -> None:
    init_db()
    with _connect() as conn:
        o = conn.execute("SELECT po_id FROM stock_receipts WHERE id = ?", (rid,)).fetchone()
        poid = int(o["po_id"]) if o and o["po_id"] is not None else None
        conn.execute("DELETE FROM stock_receipts WHERE id = ?", (rid,))
        if poid is not None:
            _recompute_po_status(conn, poid)
        conn.commit()


def list_stock_receipts() -> List[StockReceipt]:
    init_db()
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM stock_receipts ORDER BY id DESC").fetchall()
    return [StockReceipt(**dict(r)) for r in rows]


def get_stock_receipt(rid: int) -> Optional[StockReceipt]:
    init_db()
    with _connect() as conn:
        r = conn.execute("SELECT * FROM stock_receipts WHERE id = ?", (rid,)).fetchone()
    return StockReceipt(**dict(r)) if r else None


def _sql_committed_subquery_alias(product_col: str) -> str:
    """Correlated subquery: units on customer orders for that product (pipeline statuses)."""
    return f"""
    COALESCE(
      (SELECT SUM(c.quantity) FROM customer_orders c
       WHERE c.product_id = {product_col}
         AND LOWER(TRIM(COALESCE(c.status, ''))) IN ('placed', 'confirmed', 'in_progress', 'shipped', 'delivered')
      ),
      0
    )""".replace(
        "\n", " "
    )


def product_receipts_total(product_id: int) -> float:
    """Gross: sum of stock_receipts quantities (physical receipts)."""
    init_db()
    with _connect() as conn:
        r = conn.execute(
            """
            SELECT COALESCE(SUM(quantity), 0) AS s
            FROM stock_receipts WHERE product_id = ?
            """,
            (int(product_id),),
        ).fetchone()
    return float(r["s"] if r else 0.0)


def _stock_movement_net(product_id: int) -> float:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(quantity), 0) AS s FROM stock_movements WHERE product_id = ?",
            (int(product_id),),
        ).fetchone()
    return float(row["s"] if row else 0.0)


def product_committed_in_customer_orders(product_id: int) -> float:
    """Units tied to open/shipped customer orders (not yet cancelled in schema)."""
    init_db()
    with _connect() as conn:
        r = conn.execute(
            """
            SELECT COALESCE(SUM(quantity), 0) AS s
            FROM customer_orders
            WHERE product_id = ?
              AND LOWER(TRIM(COALESCE(status, ''))) IN ('placed', 'confirmed', 'in_progress', 'shipped', 'delivered')
            """,
            (int(product_id),),
        ).fetchone()
    return float(r["s"] if r else 0.0)


def list_inventory_aggregated() -> list[dict]:
    init_db()
    comm = _sql_committed_subquery_alias("sr.product_id")
    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT
              sr.product_id,
              MAX(vp.our_product_id) AS our_product_id,
              MAX(vp.name) AS name,
              MAX(vp.category) AS category,
              MAX(vp.low_stock_threshold) AS low_stock_threshold,
              MAX(v.id) AS vendor_id,
              MAX(v.person_name) AS vendor_name,
              SUM(sr.quantity) AS receipts_qty,
              {comm} AS committed_qty,
              (SUM(sr.quantity) - ({comm})) AS on_hand,
              (SELECT s.selling_price FROM stock_receipts s
                 WHERE s.product_id = sr.product_id AND s.selling_price IS NOT NULL
                 ORDER BY s.id DESC LIMIT 1) AS latest_sell
            FROM stock_receipts sr
            JOIN vendor_products vp ON vp.id = sr.product_id
            LEFT JOIN vendors v ON v.id = vp.vendor_id
            GROUP BY sr.product_id
            ORDER BY name
            """
        ).fetchall()
    out: list[dict] = []
    for r in rows:
        d = dict(r)
        oh = float(d.get("on_hand") or 0)
        th = d.get("low_stock_threshold")
        st = (
            "out_of_stock"
            if oh <= 0.0001
            else (
                "low_stock"
                if oh < effective_low_stock_threshold(
                    float(th) if th is not None else None
                )
                else "in_stock"
            )
        )
        d["on_hand"] = oh
        d["stock_status"] = st
        d["low_band"] = effective_low_stock_threshold(
            float(th) if th is not None else None
        )
        out.append(d)
    return out


def list_catalog_stock_rows(
    name_sub: str = "",
    vendor_id: Optional[int] = None,
    status_filter: Optional[set[str]] = None,
) -> list[dict]:
    """All catalog SKUs with on-hand. status_filter: in_stock / low_stock / out_of_stock; None = all."""
    where: list[str] = ["1=1"]
    params: list[object] = []
    t = (name_sub or "").strip()
    if t:
        where.append(
            "(LOWER(vp.our_product_id) LIKE LOWER(?) OR LOWER(vp.name) LIKE LOWER(?))"
        )
        p = f"%{t}%"
        params.extend([p, p])
    if vendor_id is not None:
        where.append("vp.vendor_id = ?")
        params.append(int(vendor_id))
    wh = " AND ".join(where)
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT
              vp.id AS product_id,
              vp.our_product_id,
              vp.name,
              vp.category,
              vp.low_stock_threshold,
              v.id AS vendor_id,
              v.person_name AS vendor_name
            FROM vendor_products vp
            LEFT JOIN vendors v ON v.id = vp.vendor_id
            WHERE {wh}
            ORDER BY LOWER(v.person_name), LOWER(vp.our_product_id)
            """.format(wh=wh),
            params,
        ).fetchall()
    out: list[dict] = []
    sf = status_filter
    for r in rows:
        d = dict(r)
        oh = product_on_hand(int(d["product_id"]))
        th = d.get("low_stock_threshold")
        et = effective_low_stock_threshold(float(th) if th is not None else None)
        st = "out_of_stock" if oh <= 0.0001 else ("low_stock" if oh < et else "in_stock")
        d["on_hand"] = oh
        d["receipts_qty"] = product_receipts_total(int(d["product_id"])) + max(0.0, _stock_movement_net(int(d["product_id"])))
        d["committed_qty"] = product_committed_in_customer_orders(int(d["product_id"]))
        d["stock_status"] = st
        d["low_band"] = et
        if sf is not None and st not in sf:
            continue
        out.append(d)
    return out


def list_product_alternative_ids(product_id: int) -> List[int]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT alt_product_id FROM product_alternatives WHERE product_id = ? ORDER BY id",
            (int(product_id),),
        ).fetchall()
    return [int(r[0]) for r in rows]


def set_product_alternatives(product_id: int, alt_ids: List[int]) -> None:
    init_db()
    pid = int(product_id)
    seen: set[int] = set()
    clean: list[int] = []
    for x in alt_ids:
        a = int(x)
        if a == pid or a in seen:
            continue
        seen.add(a)
        clean.append(a)
    with _connect() as conn:
        conn.execute("DELETE FROM product_alternatives WHERE product_id = ?", (pid,))
        for a in clean:
            conn.execute(
                "INSERT INTO product_alternatives (product_id, alt_product_id) VALUES (?, ?)",
                (pid, a),
            )
        conn.commit()


def instock_alternative_for_portal(
    product_id: int, limit: int = 20
) -> List[dict]:
    """Alternatives of product_id that are in stock (on_hand > 0), for customer portal."""
    init_db()
    lim = max(1, min(60, int(limit)))
    a_ids = list_product_alternative_ids(int(product_id))
    out: List[dict] = []
    for a in a_ids:
        if len(out) >= lim:
            break
        oh = product_on_hand(int(a))
        if oh <= 0.0001:
            continue
        pr = get_vendor_product(int(a))
        if not pr:
            continue
        st = "low_stock" if oh < effective_low_stock_threshold(
            float(pr.low_stock_threshold) if pr.low_stock_threshold is not None else None
        ) else "in_stock"
        paths = product_image_rel_paths(pr.image_paths)
        out.append(
            {
                "id": pr.id,
                "our_product_id": pr.our_product_id,
                "name": pr.name,
                "category": pr.category,
                "on_hand": oh,
                "stock_status": st,
                "image_rel": paths[0] if paths else None,
            }
        )
    return out


def search_all_products_prefix(
    prefix: str, limit: int = 40
) -> List[dict]:
    """Prefix match (SKU or name); includes out-of-stock. For portal."""
    init_db()
    q = (prefix or "").strip()
    if not q:
        return []
    lim = max(1, min(80, int(limit)))
    like = f"{q}%"
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT
              vp.id, vp.our_product_id, vp.name, vp.category, vp.image_paths, vp.low_stock_threshold
            FROM vendor_products vp
            WHERE (
                LOWER(vp.our_product_id) LIKE LOWER(?) OR LOWER(vp.name) LIKE LOWER(?)
              )
            ORDER BY vp.our_product_id
            LIMIT ?
            """,
            (like, f"%{q}%", lim),
        ).fetchall()
    out: List[dict] = []
    for row in rows:
        d = dict(row)
        oh = product_on_hand(int(d["id"]))
        th = d.get("low_stock_threshold")
        et = effective_low_stock_threshold(
            float(th) if th is not None else None
        )
        st = "out_of_stock" if oh <= 0.0001 else (
            "low_stock" if oh < et else "in_stock"
        )
        paths = product_image_rel_paths(d.get("image_paths"))
        out.append(
            {
                "id": int(d["id"]),
                "our_product_id": d["our_product_id"],
                "name": d["name"],
                "category": d.get("category"),
                "on_hand": oh,
                "stock_status": st,
                "image_rel": paths[0] if paths else None,
            }
        )
    return out


def lookup_product_availability(sku_query: str) -> Optional[dict]:
    """Match our_product_id (exact first, then partial). **on_hand** = available (receipts − open orders)."""
    init_db()
    q = (sku_query or "").strip()
    if not q:
        return None
    sel = """
    SELECT vp.id, vp.our_product_id, vp.name, vp.category, vp.image_paths, vp.low_stock_threshold
    """
    with _connect() as conn:
        row = conn.execute(
            f"""
            {sel}
            FROM vendor_products vp
            WHERE LOWER(TRIM(vp.our_product_id)) = LOWER(?)
            LIMIT 1
            """,
            (q,),
        ).fetchone()
        if not row:
            pat = f"%{q}%"
            row = conn.execute(
                f"""
                {sel}
                FROM vendor_products vp
                WHERE LOWER(vp.our_product_id) LIKE LOWER(?)
                   OR LOWER(vp.name) LIKE LOWER(?)
                ORDER BY LENGTH(vp.our_product_id)
                LIMIT 1
                """,
                (pat, pat),
            ).fetchone()
    if not row:
        return None
    d = dict(row)
    oh = product_on_hand(int(d["id"]))
    paths = product_image_rel_paths(d.get("image_paths"))
    th = d.get("low_stock_threshold")
    et = effective_low_stock_threshold(
        float(th) if th is not None else None
    )
    st = (
        "out_of_stock"
        if oh <= 0.0001
        else ("low_stock" if oh < et else "in_stock")
    )
    return {
        "id": int(d["id"]),
        "our_product_id": d["our_product_id"],
        "name": d["name"],
        "category": d.get("category"),
        "on_hand": oh,
        "in_stock": oh > 0.0001,
        "stock_status": st,
        "image_rel": paths[0] if paths else None,
    }


def product_on_hand(product_id: int) -> float:
    """**Available to promise**: receipts minus customer-order pipeline (same as portal + order check)."""
    a = (
        product_receipts_total(product_id)
        + _stock_movement_net(product_id)
        - product_committed_in_customer_orders(int(product_id))
    )
    return a if a > 0.0001 else 0.0


def latest_selling_price_for_product(product_id: int) -> Optional[float]:
    init_db()
    with _connect() as conn:
        r = conn.execute(
            """
            SELECT selling_price FROM stock_receipts
            WHERE product_id = ? AND selling_price IS NOT NULL
            ORDER BY id DESC LIMIT 1
            """,
            (product_id,),
        ).fetchone()
    if r and r["selling_price"] is not None:
        return float(r["selling_price"])
    pr = get_vendor_product(product_id)
    if pr and pr.cost_price is not None:
        return float(pr.cost_price)
    return None


def search_instock_products_prefix(prefix: str, limit: int = 40) -> List[dict]:
    """In-stock only; prefix match on our_product_id or name (customer portal search)."""
    init_db()
    q = (prefix or "").strip()
    if not q:
        return []
    lim = max(1, min(80, int(limit)))
    like = f"{q}%"
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT vp.id, vp.our_product_id, vp.name, vp.category, vp.image_paths, vp.low_stock_threshold
            FROM vendor_products vp
            WHERE (
                LOWER(vp.our_product_id) LIKE LOWER(?)
                OR LOWER(vp.name) LIKE LOWER(?)
              )
            ORDER BY vp.our_product_id
            LIMIT ?
            """,
            (like, like, lim),
        ).fetchall()
    out: List[dict] = []
    for row in rows:
        d = dict(row)
        oh = product_on_hand(int(d["id"]))
        if oh <= 0.0001:
            continue
        paths = product_image_rel_paths(d.get("image_paths"))
        th = d.get("low_stock_threshold")
        st = "low_stock" if oh < effective_low_stock_threshold(
            float(th) if th is not None else None
        ) else "in_stock"
        out.append(
            {
                "id": int(d["id"]),
                "our_product_id": d["our_product_id"],
                "name": d["name"],
                "category": d.get("category"),
                "on_hand": oh,
                "stock_status": st,
                "image_rel": paths[0] if paths else None,
            }
        )
    return out


def _default_issuer_snapshot() -> dict:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT issuer_legal_name, issuer_address, issuer_city_pin,
                   issuer_gstin, issuer_phone, issuer_email
            FROM vendors
            WHERE issuer_legal_name IS NOT NULL AND TRIM(issuer_legal_name) != ''
            LIMIT 1
            """
        ).fetchone()
    if not row:
        return {
            "issuer_legal_name": None,
            "issuer_address": None,
            "issuer_city_pin": None,
            "issuer_gstin": None,
            "issuer_phone": None,
            "issuer_email": None,
        }
    return dict(row)


def insert_customer_order(
    customer_id: int,
    product_id: int,
    quantity: float,
    *,
    unit_price: Optional[float] = None,
    notes: Optional[str] = None,
) -> int:
    init_db()
    if quantity <= 0:
        raise ValueError("Quantity must be positive")
    oh = product_on_hand(product_id)
    if quantity - 0.0001 > oh:
        raise ValueError("Not enough stock for this quantity")
    pr = get_vendor_product(product_id)
    if not pr:
        raise ValueError("Product not found")
    if unit_price is not None and float(unit_price) > 0:
        unit = float(unit_price)
    else:
        u = latest_selling_price_for_product(product_id)
        if u is None or u <= 0:
            raise ValueError("Set selling price on a stock receipt (or cost on product) first")
        unit = float(u)
    cust = get_customer(customer_id)
    if not cust:
        raise ValueError("Customer not found")
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO customer_orders (
                customer_id, product_id, quantity, unit_price, billing_pct, gst_rate_pct,
                status, updated_at, notes
            )
            VALUES (?, ?, ?, ?, ?, ?, 'placed', datetime('now'), ?)
            """,
            (
                customer_id,
                product_id,
                float(quantity),
                float(unit),
                100,
                pr.tax_rate,
                (notes or None) or None,
            ),
        )
        conn.commit()
        oid = int(cur.lastrowid)
    _wa_order_booked(oid)
    return oid


def _wa_order_booked(oid: int) -> None:
    if (os.environ.get("WHATSAPP_DISABLE") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return
    o = get_customer_order(oid)
    if not o:
        return
    c = get_customer(int(o.customer_id))
    if not c or not (c.phone and str(c.phone).strip()):
        return
    pr = get_vendor_product(int(o.product_id))
    item_ref = (
        f"{pr.our_product_id} / {pr.name}" if pr else str(o.product_id)
    )
    try:
        from whatsapp_meta import send_wa_template_safe

        send_wa_template_safe(
            "order_booked",
            c.phone,
            {
                "name": (c.name or "Customer").strip() or "Customer",
                "order_id": str(o.id),
                "item_id": item_ref[:200],
                "quantity": f"{o.quantity:g}",
            },
        )
    except Exception as ex:
        print("WhatsApp order booked (ignored):", ex, file=sys.stderr)


def _wa_sales_order_doc_booked(so_id: int) -> None:
    if (os.environ.get("WHATSAPP_DISABLE") or "").strip().lower() in ("1", "true", "yes"):
        return
    so = get_sales_order_document(so_id)
    if not so:
        return
    cust = get_customer(int(so["customer_id"]))
    if not cust or not (cust.phone and str(cust.phone).strip()):
        return
    lines = list_sales_order_document_lines(so_id)
    if not lines:
        return
    first = lines[0]
    item_ref = f"{first.get('sku') or ''} / {first.get('item_name') or ''}"
    qty = sum(float(x.get("quantity") or 0) for x in lines)
    try:
        from whatsapp_meta import send_wa_template_safe

        send_wa_template_safe(
            "order_booked",
            cust.phone,
            {
                "name": (cust.name or "Customer").strip() or "Customer",
                "order_id": str(so.get("doc_no") or so_id),
                "item_id": item_ref[:200],
                "quantity": f"{qty:g}",
            },
        )
    except Exception as ex:
        print("WhatsApp sales order doc booked (ignored):", ex, file=sys.stderr)


def _wa_delivery_doc_update(delivery_id: int) -> None:
    if (os.environ.get("WHATSAPP_DISABLE") or "").strip().lower() in ("1", "true", "yes"):
        return
    with _connect() as conn:
        d = conn.execute("SELECT * FROM delivery_docs WHERE id = ?", (int(delivery_id),)).fetchone()
    if not d:
        return
    so = get_sales_order_document(int(d["sales_order_id"]))
    if not so:
        return
    cust = get_customer(int(so["customer_id"]))
    if not cust or not (cust.phone and str(cust.phone).strip()):
        return
    img = _resolve_upload_path_stored(d["receipt_image_path"]) if d["receipt_image_path"] else None
    try:
        from whatsapp_meta import send_wa_template_safe

        send_wa_template_safe(
            "delivery_update",
            cust.phone,
            {
                "name": (cust.name or "Customer").strip() or "Customer",
                "receipt": (d["delivery_receipt_number"] or "—"),
                "contact": (d["delivery_contact"] or "—"),
                "notes": (d["notes"] or "—"),
            },
            header_image_path=img,
        )
    except Exception as ex:
        print("WhatsApp delivery doc update (ignored):", ex, file=sys.stderr)


def get_customer_order(oid: int) -> Optional[CustomerOrder]:
    init_db()
    with _connect() as conn:
        r = conn.execute("SELECT * FROM customer_orders WHERE id = ?", (oid,)).fetchone()
    return CustomerOrder(**dict(r)) if r else None


def list_customer_orders() -> List[CustomerOrder]:
    init_db()
    if not _table_exists("customer_orders"):
        return []
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM customer_orders ORDER BY created_at DESC, id DESC"
        ).fetchall()
    return [CustomerOrder(**dict(x)) for x in rows]


def list_customer_orders_for_customer(customer_id: int) -> List[CustomerOrder]:
    init_db()
    if not _table_exists("customer_orders"):
        return []
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM customer_orders
            WHERE customer_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (customer_id,),
        ).fetchall()
    return [CustomerOrder(**dict(x)) for x in rows]


def delete_customer_order(oid: int) -> None:
    init_db()
    with _connect() as conn:
        conn.execute("DELETE FROM customer_orders WHERE id = ?", (oid,))
        conn.commit()


def _resolve_upload_path_stored(relative: Optional[str]) -> Optional[str]:
    if not relative or not str(relative).strip():
        return None
    p = (relative or "").strip().replace("\\", os.sep)
    p = p.lstrip("/")
    a = os.path.join(UPLOADS_ROOT, p)
    return a if os.path.isfile(a) else None


def save_customer_order_receipt(oid: int, file_bytes: bytes, name_hint: str) -> str:
    init_db()
    d = os.path.join(UPLOADS_ROOT, "delivery_receipts")
    os.makedirs(d, exist_ok=True)
    ext = (os.path.splitext((name_hint or "x.jpg") or "x.jpg")[1] or ".jpg").lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        ext = ".jpg"
    fn = f"co_{int(oid):05d}_{uuid.uuid4().hex[:10]}{ext}"
    p = os.path.join(d, fn)
    with open(p, "wb") as f:
        f.write(file_bytes)
    return os.path.join("delivery_receipts", fn).replace("\\", "/")


def sum_customer_order_shipment_qty(oid: int) -> float:
    init_db()
    if not _table_exists("customer_order_shipments"):
        return 0.0
    with _connect() as conn:
        r = conn.execute(
            """
            SELECT COALESCE(SUM(quantity), 0) AS s
            FROM customer_order_shipments WHERE customer_order_id = ?
            """,
            (int(oid),),
        ).fetchone()
    return float(r["s"] if r else 0.0)


def list_customer_order_shipments(oid: int) -> List[CustomerOrderShipment]:
    init_db()
    if not _table_exists("customer_order_shipments"):
        return []
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM customer_order_shipments
            WHERE customer_order_id = ?
            ORDER BY id ASC
            """,
            (int(oid),),
        ).fetchall()
    return [CustomerOrderShipment(**dict(x)) for x in rows]


def insert_customer_order_shipment(
    customer_order_id: int,
    quantity: float,
    unit_price: float,
    delivery_receipt_number: Optional[str],
    delivery_contact: Optional[str],
    file_bytes: Optional[bytes] = None,
    file_name: str = "r.jpg",
) -> int:
    init_db()
    if quantity <= 0 or unit_price < 0:
        raise ValueError("Quantity and unit price must be valid")
    o = get_customer_order(customer_order_id)
    if not o:
        raise ValueError("Order not found")
    prev_sum = sum_customer_order_shipment_qty(int(customer_order_id))
    if prev_sum + float(quantity) - float(o.quantity) > 0.0001:
        raise ValueError("Shipment qty cannot exceed the order line quantity")
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO customer_order_shipments (
                customer_order_id, quantity, unit_price,
                delivery_receipt_number, delivery_contact, receipt_image_path, created_at
            )
            VALUES (?, ?, ?, ?, ?, NULL, datetime('now'))
            """,
            (
                int(customer_order_id),
                float(quantity),
                float(unit_price),
                (delivery_receipt_number or None) or None,
                (delivery_contact or None) or None,
            ),
        )
        conn.commit()
        ship_id = int(cur.lastrowid)
    relp: Optional[str] = None
    if file_bytes:
        relp = _save_shipment_receipt_path(
            int(customer_order_id), ship_id, file_bytes, file_name
        )
        with _connect() as conn:
            conn.execute(
                "UPDATE customer_order_shipments SET receipt_image_path = ? WHERE id = ?",
                (relp, ship_id),
            )
            conn.commit()
    nst = "shipped"
    with _connect() as conn:
        conn.execute(
            """
            UPDATE customer_orders SET
                status = ?,
                delivery_receipt_number = ?,
                delivery_contact = ?,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (
                nst,
                (delivery_receipt_number or None) or None,
                (delivery_contact or None) or None,
                int(customer_order_id),
            ),
        )
        conn.commit()
    img_abs = _resolve_upload_path_stored(relp) if relp else None
    _notify_customer_order_shipped(int(customer_order_id), header_image_abs=img_abs)
    return ship_id


def _save_shipment_receipt_path(
    order_id: int, ship_id: int, file_bytes: bytes, name_hint: str
) -> str:
    d = os.path.join(UPLOADS_ROOT, "delivery_receipts")
    os.makedirs(d, exist_ok=True)
    ext = (os.path.splitext((name_hint or "x.jpg") or "x.jpg")[1] or ".jpg").lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        ext = ".jpg"
    fn = f"co_{int(order_id):05d}_s{int(ship_id):06d}{uuid.uuid4().hex[:8]}{ext}"
    p = os.path.join(d, fn)
    with open(p, "wb") as f:
        f.write(file_bytes)
    return os.path.join("delivery_receipts", fn).replace("\\", "/")


def save_customer_order_delivery_receipt_pdf(order_id: int) -> Optional[str]:
    """Build delivery receipt PDF, save under uploads/order_receipt_pdfs/, store path on order."""
    init_db()
    o = get_customer_order(int(order_id))
    if not o:
        return None
    c = get_customer(int(o.customer_id))
    pr = get_vendor_product(int(o.product_id))
    doc_date = (o.updated_at or o.created_at or "")[:10] or "—"
    sku = (pr.our_product_id or "") if pr else ""
    title = (pr.name or "") if pr else ""
    line = float(o.quantity) * float(o.unit_price)
    from bill_pdf import build_customer_order_shipped_receipt_pdf

    pdf_bytes = build_customer_order_shipped_receipt_pdf(
        order_id=int(o.id),
        customer_name=(c.name or "Customer").strip() if c else "Customer",
        customer_phone=(c.phone if c else None),
        customer_address=(c.address if c else None),
        item_sku=str(sku),
        item_name=str(title),
        quantity=float(o.quantity),
        unit_price=float(o.unit_price),
        line_total=line,
        delivery_receipt_number=o.delivery_receipt_number,
        delivery_contact=o.delivery_contact,
        delivery_notes=o.delivery_notes,
        order_notes=o.notes,
        doc_date=doc_date,
        seller=_default_seller_snapshot(),
    )
    d = os.path.join(UPLOADS_ROOT, "order_receipt_pdfs")
    os.makedirs(d, exist_ok=True)
    fn = f"co_{int(order_id):05d}_receipt.pdf"
    rel = f"order_receipt_pdfs/{fn}".replace("\\", "/")
    ap = os.path.join(d, fn)
    with open(ap, "wb") as f:
        f.write(pdf_bytes)
    with _connect() as conn:
        conn.execute(
            """
            UPDATE customer_orders SET delivery_receipt_pdf_path = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (rel, int(order_id)),
        )
        conn.commit()
    return rel


def _notify_customer_order_shipped(
    order_id: int,
    *,
    header_image_abs: Optional[str] = None,
) -> None:
    """
    One WhatsApp per ship: delivery_update template only (PDF is optional extra message).
    Meta templates take image header — PDF must be a separate document message (see WHATSAPP_SEND_ORDER_RECEIPT_PDF).
    Duplicate sends suppressed via whatsapp_ship_notice_sent.
    """
    init_db()
    o = get_customer_order(int(order_id))
    if not o:
        return
    if int(getattr(o, "whatsapp_ship_notice_sent", 0) or 0) == 1:
        return
    save_pdf_disk = (os.environ.get("WHATSAPP_SAVE_ORDER_RECEIPT_PDF") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    send_pdf_wa = (os.environ.get("WHATSAPP_SEND_ORDER_RECEIPT_PDF") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    if save_pdf_disk or send_pdf_wa:
        save_customer_order_delivery_receipt_pdf(int(order_id))
        o = get_customer_order(int(order_id)) or o
    if (os.environ.get("WHATSAPP_DISABLE") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return
    c = get_customer(int(o.customer_id))
    if not c or not (c.phone and str(c.phone).strip()):
        return
    img = header_image_abs or _resolve_upload_path_stored(
        getattr(o, "receipt_image_path", None)
    )
    try:
        from whatsapp_meta import send_wa_document_safe, send_wa_template
    except Exception as ex:
        print("WhatsApp import (ignored):", ex, file=sys.stderr)
        return
    r = send_wa_template(
        "delivery_update",
        c.phone,
        {
            "name": (c.name or "Customer").strip() or "Customer",
            "receipt": (getattr(o, "delivery_receipt_number", None) or "—"),
            "contact": (getattr(o, "delivery_contact", None) or "—"),
            "notes": (
                getattr(o, "delivery_notes", None)
                or getattr(o, "notes", None)
                or "—"
            ),
        },
        header_image_path=img,
    )
    if r.get("ok") is True:
        with _connect() as conn:
            conn.execute(
                """
                UPDATE customer_orders SET whatsapp_ship_notice_sent = 1, updated_at = datetime('now')
                WHERE id = ?
                """,
                (int(order_id),),
            )
            conn.commit()
    else:
        print("WhatsApp shipped update failed:", r, file=sys.stderr)
    if not send_pdf_wa:
        return
    o2 = get_customer_order(int(order_id))
    pdf_rel = getattr(o2, "delivery_receipt_pdf_path", None) if o2 else None
    pdf_abs = _resolve_upload_path_stored(pdf_rel) if pdf_rel else None
    if pdf_abs and os.path.isfile(pdf_abs):
        try:
            send_wa_document_safe(
                c.phone,
                pdf_abs,
                filename=os.path.basename(pdf_abs),
                caption="Order receipt (PDF)",
            )
        except Exception as ex:
            print("WhatsApp receipt PDF (ignored):", ex, file=sys.stderr)


def _co_whatsapp_after_status_change(
    o: CustomerOrder, prev_status: str, new_status: str
) -> None:
    if (os.environ.get("WHATSAPP_DISABLE") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return
    p0 = (prev_status or "placed").strip().lower()
    p1 = (new_status or "placed").strip().lower()
    if p0 == p1:
        return
    c = get_customer(int(o.customer_id))
    if not c or not (c.phone and str(c.phone).strip()):
        return
    try:
        from whatsapp_meta import send_wa_template_safe
    except Exception as ex:
        print("WhatsApp import (ignored):", ex, file=sys.stderr)
        return
    pr = get_vendor_product(int(o.product_id))
    item_ref = f"{pr.our_product_id} / {pr.name}" if pr else str(o.product_id)
    line_amt = float(o.quantity) * float(o.unit_price)
    if p1 == "confirmed" and p0 != "confirmed":
        try:
            send_wa_template_safe(
                "order_confirmed",
                c.phone,
                {
                    "name": (c.name or "Customer").strip() or "Customer",
                    "order_id": str(o.id),
                    "item_id": item_ref[:200],
                    "quantity": f"{o.quantity:g}",
                    "amount": f"{line_amt:.2f}",
                },
            )
        except Exception as ex:
            print("WhatsApp order confirmed (ignored):", ex, file=sys.stderr)
        return
    if p1 == "shipped":
        img = _resolve_upload_path_stored(getattr(o, "receipt_image_path", None))
        try:
            _notify_customer_order_shipped(int(o.id), header_image_abs=img)
        except Exception as ex:
            print("WhatsApp shipped update (ignored):", ex, file=sys.stderr)


def update_customer_order(
    oid: int,
    *,
    status: Optional[str] = None,
    shipment_id: Optional[str] = None,
    transport_name: Optional[str] = None,
    transport_number: Optional[str] = None,
    notes: Optional[str] = None,
    delivery_receipt_number: Optional[str] = None,
    delivery_contact: Optional[str] = None,
    delivery_notes: Optional[str] = None,
    receipt_image_path: Optional[str] = None,
) -> None:
    init_db()
    o = get_customer_order(oid)
    if not o:
        raise ValueError("Order not found")
    prev = (o.status or "placed").strip().lower()
    st = status if status is not None else o.status
    sid = shipment_id if shipment_id is not None else o.shipment_id
    tn = transport_name if transport_name is not None else o.transport_name
    tnum = transport_number if transport_number is not None else o.transport_number
    if notes is not None:
        nt = notes
    elif delivery_notes is not None:
        nt = delivery_notes
    else:
        nt = o.notes
    drn = (
        delivery_receipt_number
        if delivery_receipt_number is not None
        else o.delivery_receipt_number
    )
    dcon = delivery_contact if delivery_contact is not None else o.delivery_contact
    dnt = delivery_notes if delivery_notes is not None else o.delivery_notes
    rpath = (
        receipt_image_path
        if receipt_image_path is not None
        else getattr(o, "receipt_image_path", None)
    )
    nst = (st or "placed").strip()
    pl = (prev or "").strip().lower()
    nl = (nst or "").strip().lower()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE customer_orders SET
                status = ?, shipment_id = ?, transport_name = ?, transport_number = ?,
                notes = ?,
                delivery_receipt_number = ?, delivery_contact = ?, delivery_notes = ?,
                receipt_image_path = ?,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (
                nst,
                (sid or None) or None,
                (tn or None) or None,
                (tnum or None) or None,
                (nt or None) or None,
                (drn or None) or None,
                (dcon or None) or None,
                (dnt or None) or None,
                (rpath or None) or None,
                oid,
            ),
        )
        if pl == "shipped" and nl != "shipped":
            conn.execute(
                "UPDATE customer_orders SET whatsapp_ship_notice_sent = 0 WHERE id = ?",
                (oid,),
            )
        conn.commit()
    o2 = get_customer_order(oid) or o
    _co_whatsapp_after_status_change(o2, prev, nst)


def list_customer_order_ids_eligible_new_billing() -> List[int]:
    init_db()
    if not _table_exists("customer_orders"):
        return []
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT o.id
            FROM customer_orders o
            WHERE LOWER(TRIM(o.status)) IN ('shipped', 'delivered')
              AND NOT EXISTS (
                SELECT 1 FROM customer_order_billings b WHERE b.customer_order_id = o.id
              )
            ORDER BY o.created_at DESC
            """
        ).fetchall()
    return [int(r["id"]) for r in rows]


def get_customer_order_billing(bid: int) -> Optional[CustomerOrderBilling]:
    init_db()
    with _connect() as conn:
        r = conn.execute(
            "SELECT * FROM customer_order_billings WHERE id = ?", (bid,)
        ).fetchone()
    return CustomerOrderBilling(**dict(r)) if r else None


def get_customer_order_billing_by_order_id(
    customer_order_id: int,
) -> Optional[CustomerOrderBilling]:
    init_db()
    with _connect() as conn:
        r = conn.execute(
            "SELECT * FROM customer_order_billings WHERE customer_order_id = ?",
            (customer_order_id,),
        ).fetchone()
    return CustomerOrderBilling(**dict(r)) if r else None


def send_customer_order_payment_reminder_wa(billing_id: int) -> dict[str, Any]:
    """Send WhatsApp `payment_reminder_3` for an existing customer-order billing row."""
    init_db()
    b = get_customer_order_billing(int(billing_id))
    if not b:
        return {"ok": False, "error": "billing not found"}
    if (os.environ.get("WHATSAPP_DISABLE") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return {"ok": False, "error": "WHATSAPP_DISABLE"}
    co = get_customer_order(int(b.customer_order_id))
    if not co:
        return {"ok": False, "error": "order not found"}
    if (co.status or "").strip().lower() != "delivered":
        return {
            "ok": False,
            "error": "Set order status to **Delivered** before sending a payment reminder.",
        }
    cust = get_customer(int(b.customer_id))
    if not cust or not (cust.phone and str(cust.phone).strip()):
        return {"ok": False, "error": "customer phone missing"}
    due = float(b.gst_grand_total or 0.0)
    if due <= 0.0001:
        due = float(b.raw_line_total or 0.0)
    amt_str = f"{due:,.0f}"
    sku = (b.snap_item_sku or "").strip() or "—"
    od = (co.created_at or "")[:10] or "—"
    try:
        from whatsapp_meta import send_wa_template

        r = send_wa_template(
            "payment_reminder",
            cust.phone,
            {
                "name": (cust.name or "Customer").strip() or "Customer",
                "order_id": str(co.id),
                "amount_due": amt_str,
                "quantity": f"{co.quantity:g}",
                "item_id": sku[:200],
                "order_date": od,
            },
        )
    except Exception as ex:
        return {"ok": False, "error": str(ex)}
    if r.get("ok") is True:
        with _connect() as conn:
            conn.execute(
                """
                UPDATE customer_order_billings SET
                    payment_reminder_wa_sent_at = datetime('now'),
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (int(billing_id),),
            )
            conn.commit()
    return r


def list_customer_order_billings() -> List[CustomerOrderBilling]:
    init_db()
    if not _table_exists("customer_order_billings"):
        return []
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM customer_order_billings ORDER BY created_at DESC, id DESC"
        ).fetchall()
    return [CustomerOrderBilling(**dict(x)) for x in rows]


def _rate_band_label(unit_price: float) -> str:
    p = float(unit_price)
    if p <= 0:
        return "₹ 0"
    if p < 100:
        return "₹ 1–99"
    if p < 500:
        return "₹ 100–499"
    if p < 2000:
        return "₹ 500–1,999"
    if p < 10000:
        return "₹ 2k–9.9k"
    return "₹ 10k+"


def list_portal_order_lines_detail() -> List[dict]:
    """Portal customer_orders joined to product category — for dashboard grouping."""
    init_db()
    if not _table_exists("customer_orders"):
        return []
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT co.id AS order_id, co.customer_id, c.name AS customer_name,
                   co.product_id, vp.our_product_id AS sku, vp.name AS product_name,
                   COALESCE(NULLIF(TRIM(vp.category), ''), '(uncategorised)') AS category,
                   co.quantity, co.unit_price, co.status,
                   (co.quantity * co.unit_price) AS line_value,
                   co.created_at
            FROM customer_orders co
            JOIN customers c ON c.id = co.customer_id
            JOIN vendor_products vp ON vp.id = co.product_id
            ORDER BY co.created_at DESC
            """
        ).fetchall()
    out: List[dict] = []
    for r in rows:
        d = dict(r)
        q = float(d["quantity"])
        u = float(d["unit_price"])
        d["quantity"] = q
        d["unit_price"] = u
        d["line_value"] = float(d["line_value"])
        d["rate_band"] = _rate_band_label(u)
        out.append(d)
    return out


def insert_customer_order_billing(
    customer_order_id: int,
    *,
    quantity: Optional[float] = None,
    unit_cost: Optional[float] = None,
    billing_pct: Optional[int] = None,
    notes: Optional[str] = None,
    vendor_invoice_raw: Optional[str] = None,
    vendor_invoice_gst: Optional[str] = None,
) -> int:
    init_db()
    co = get_customer_order(customer_order_id)
    if not co:
        raise ValueError("Customer order not found")
    if (co.status or "").strip().lower() not in ("shipped", "delivered"):
        raise ValueError("Set order status to **shipped** or **delivered** before creating a bill")
    if get_customer_order_billing_by_order_id(customer_order_id) is not None:
        raise ValueError("Billing already exists for this order")
    cust = get_customer(co.customer_id)
    if not cust:
        raise ValueError("Customer not found")
    pr = get_vendor_product(co.product_id)
    if not pr:
        raise ValueError("Product not found")
    iss = _default_issuer_snapshot()
    q = float(co.quantity) if quantity is None else float(quantity)
    ucost = float(co.unit_price) if unit_cost is None else float(unit_cost)
    bpc = co.billing_pct if billing_pct is None else billing_pct
    n_raw = (
        (str(notes).strip() or None)
        if notes is not None
        else None
    )
    v_raw = None if vendor_invoice_raw is None else (str(vendor_invoice_raw).strip() or None)
    v_gst = None if vendor_invoice_gst is None else (str(vendor_invoice_gst).strip() or None)
    raw_line, gst_taxable, gst_amt, gst_grand = compute_po_billing_amounts(
        q,
        ucost,
        bpc,
        None,
    )
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO customer_order_billings (
                customer_order_id, customer_id, product_id,
                quantity, unit_cost, billing_pct, gst_rate_pct,
                raw_line_total, gst_taxable_total, gst_amount, gst_grand_total,
                vendor_invoice_raw, vendor_invoice_gst, notes,
                snap_customer_name, snap_customer_company, snap_customer_phone, snap_customer_address,
                snap_issuer_legal_name, snap_issuer_address, snap_issuer_city_pin,
                snap_issuer_gstin, snap_issuer_phone, snap_issuer_email,
                snap_item_sku, snap_item_name,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                customer_order_id,
                co.customer_id,
                co.product_id,
                q,
                ucost,
                bpc,
                None,
                raw_line,
                0.0,
                0.0,
                0.0,
                v_raw,
                v_gst,
                n_raw,
                cust.name,
                cust.company_name,
                cust.phone,
                cust.address,
                iss.get("issuer_legal_name"),
                iss.get("issuer_address"),
                iss.get("issuer_city_pin"),
                iss.get("issuer_gstin"),
                iss.get("issuer_phone"),
                iss.get("issuer_email"),
                pr.our_product_id,
                pr.name,
                None,
            ),
        )
        cob_id = int(cur.lastrowid)
        conn.commit()
    cogs = q * float(pr.cost_price or 0.0)
    jid = _post_gl_sale_cogs(cob_id, raw_line, cogs)
    with _connect() as c2:
        c2.execute(
            "UPDATE customer_order_billings SET gl_journal_id = ? WHERE id = ?",
            (jid, cob_id),
        )
        c2.commit()
    return cob_id


def update_customer_order_billing_record(
    bid: int,
    *,
    snap_customer_name: str,
    snap_customer_company: Optional[str],
    snap_customer_phone: Optional[str],
    snap_customer_address: Optional[str],
    snap_issuer_legal_name: Optional[str],
    snap_issuer_address: Optional[str],
    snap_issuer_city_pin: Optional[str],
    snap_issuer_gstin: Optional[str],
    snap_issuer_phone: Optional[str],
    snap_issuer_email: Optional[str],
    snap_item_sku: str,
    snap_item_name: str,
    quantity: float,
    unit_cost: float,
    billing_pct: Optional[int],
    gst_rate_pct: Optional[float],
    vendor_invoice_raw: Optional[str],
    vendor_invoice_gst: Optional[str],
    notes: str,
) -> None:
    init_db()
    b = get_customer_order_billing(bid)
    if not b:
        raise ValueError("Billing row not found")
    raw_line, gst_taxable, gst_amt, gst_grand = compute_po_billing_amounts(
        quantity,
        unit_cost,
        billing_pct,
        None,
    )
    ra = None if vendor_invoice_raw is None else (str(vendor_invoice_raw).strip() or None)
    ga = None if vendor_invoice_gst is None else (str(vendor_invoice_gst).strip() or None)
    with _connect() as conn:
        conn.execute(
            """
            UPDATE customer_order_billings SET
                quantity = ?, unit_cost = ?, billing_pct = ?, gst_rate_pct = ?,
                raw_line_total = ?, gst_taxable_total = ?, gst_amount = ?, gst_grand_total = ?,
                snap_customer_name = ?, snap_customer_company = ?, snap_customer_phone = ?,
                snap_customer_address = ?,
                snap_issuer_legal_name = ?, snap_issuer_address = ?, snap_issuer_city_pin = ?,
                snap_issuer_gstin = ?, snap_issuer_phone = ?, snap_issuer_email = ?,
                snap_item_sku = ?, snap_item_name = ?,
                vendor_invoice_raw = ?, vendor_invoice_gst = ?, notes = ?,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (
                float(quantity),
                float(unit_cost),
                billing_pct,
                None,
                raw_line,
                0.0,
                0.0,
                0.0,
                snap_customer_name.strip(),
                (snap_customer_company or "").strip() or None,
                (snap_customer_phone or "").strip() or None,
                (snap_customer_address or "").strip() or None,
                (snap_issuer_legal_name or "").strip() or None,
                (snap_issuer_address or "").strip() or None,
                (snap_issuer_city_pin or "").strip() or None,
                (snap_issuer_gstin or "").strip() or None,
                (snap_issuer_phone or "").strip() or None,
                (snap_issuer_email or "").strip() or None,
                (snap_item_sku or "").strip(),
                (snap_item_name or "").strip(),
                ra,
                ga,
                (notes or None) or None,
                bid,
            ),
        )
        conn.commit()


def delete_customer_order_billing(bid: int) -> None:
    init_db()
    b = get_customer_order_billing(bid)
    if b and getattr(b, "gl_journal_id", None):
        from gl import post_reversal

        post_reversal(
            int(b.gl_journal_id),
            _today_iso(),
            f"Reverse COB delete #{bid}",
            "cob_del",
            bid,
        )
    with _connect() as conn:
        conn.execute("DELETE FROM customer_order_billings WHERE id = ?", (bid,))
        conn.commit()


def line_total(quantity: float, unit_cost: float, billing_pct: Optional[int]) -> float:
    """Single line amount: qty × unit × (billing% / 100). Vendor **billing** column drives partial billing."""
    bp = float(billing_pct if billing_pct is not None else 100)
    bp = max(0.0, min(100.0, bp))
    return float(quantity) * float(unit_cost) * (bp / 100.0)


def compute_po_billing_amounts(
    quantity: float,
    unit_cost: float,
    billing_pct: Optional[int],
    gst_rate_pct: Optional[float],
) -> tuple[float, float, float, float]:
    """Returns (line_total, 0,0,0) — GST fields unused; kept for call compatibility."""
    r = line_total(quantity, unit_cost, billing_pct)
    return (r, 0.0, 0.0, 0.0)


def _today_iso() -> str:
    return date.today().isoformat()


def _post_gl_purchase_bill(pob_id: int, amount: float) -> int:
    from gl import AC_AP, AC_INVENTORY, post_journal

    return int(
        post_journal(
            _today_iso(),
            f"Vendor bill B#{pob_id} — inventory and AP",
            "po_billing",
            pob_id,
            [
                (AC_INVENTORY, float(amount), 0.0),
                (AC_AP, 0.0, float(amount)),
            ],
        )
    )


def _post_gl_sale_cogs(cob_id: int, sales: float, cogs: float) -> int:
    from gl import AC_AR, AC_COGS, AC_INVENTORY, AC_SALES, post_journal

    s = float(sales)
    cg = max(0.0, float(cogs))
    if cg < 0.0001:
        return int(
            post_journal(
                _today_iso(),
                f"Customer sale COB#{cob_id}",
                "cob",
                cob_id,
                [
                    (AC_AR, s, 0.0),
                    (AC_SALES, 0.0, s),
                ],
            )
        )
    return int(
        post_journal(
            _today_iso(),
            f"Customer sale + COGS COB#{cob_id}",
            "cob",
            cob_id,
            [
                (AC_AR, s, 0.0),
                (AC_SALES, 0.0, s),
                (AC_COGS, cg, 0.0),
                (AC_INVENTORY, 0.0, cg),
            ],
        )
    )


def _post_gl_ar_receipt(pay_id: int, amount: float) -> int:
    from gl import AC_AR, AC_CASH, post_journal

    a = float(amount)
    return int(
        post_journal(
            _today_iso(),
            f"Customer payment AR p#{pay_id}",
            "ar_payment",
            pay_id,
            [(AC_CASH, a, 0.0), (AC_AR, 0.0, a)],
        )
    )


def _post_gl_ap_payment(pay_id: int, amount: float) -> int:
    from gl import AC_AP, AC_CASH, post_journal

    a = float(amount)
    return int(
        post_journal(
            _today_iso(),
            f"Vendor payment AP p#{pay_id}",
            "ap_payment",
            pay_id,
            [(AC_AP, a, 0.0), (AC_CASH, 0.0, a)],
        )
    )


def list_po_billings() -> List[PoBilling]:
    init_db()
    if not _table_exists("po_billings"):
        return []
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM po_billings ORDER BY created_at DESC, id DESC"
        ).fetchall()
    return [PoBilling(**dict(r)) for r in rows]


def get_po_billing(bid: int) -> Optional[PoBilling]:
    init_db()
    with _connect() as conn:
        r = conn.execute("SELECT * FROM po_billings WHERE id = ?", (bid,)).fetchone()
    return PoBilling(**dict(r)) if r else None


def get_po_billing_by_po_id(po_id: int) -> Optional[PoBilling]:
    init_db()
    with _connect() as conn:
        r = conn.execute("SELECT * FROM po_billings WHERE po_id = ?", (po_id,)).fetchone()
    return PoBilling(**dict(r)) if r else None


def upload_po_billing_pdf_to_bucket(po_id: int) -> str:
    """Build vendor bill PDF and store as vendor_bills/{po_id}.pdf."""
    if _storage_s3 is None or not _storage_s3.s3_enabled():
        raise RuntimeError("S3 not configured (set S3_ENDPOINT_URL, S3_BUCKET, access keys).")
    from bill_pdf import build_billing_pdfs_for_record

    b = get_po_billing_by_po_id(int(po_id))
    if not b:
        raise ValueError("No billing row for this PO.")
    raw_pdf, _ = build_billing_pdfs_for_record(b)
    return _storage_s3.put_vendor_bill_pdf(int(po_id), raw_pdf)


def upload_customer_order_billing_pdf_to_bucket(customer_order_id: int) -> str:
    """Build customer bill PDF and store as customer_bills/{customer_order_id}.pdf."""
    if _storage_s3 is None or not _storage_s3.s3_enabled():
        raise RuntimeError("S3 not configured.")
    from bill_pdf import build_billing_pdfs_for_co_record

    b = get_customer_order_billing_by_order_id(int(customer_order_id))
    if not b:
        raise ValueError("No billing row for this order.")
    raw_pdf, _ = build_billing_pdfs_for_co_record(b)
    return _storage_s3.put_customer_bill_pdf(int(customer_order_id), raw_pdf)


def list_po_ids_eligible_new_billing() -> List[int]:
    init_db()
    if not _table_exists("po_billings"):
        return []
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT po.id
            FROM purchase_orders po
            WHERE EXISTS (SELECT 1 FROM stock_receipts sr WHERE sr.po_id = po.id)
              AND NOT EXISTS (SELECT 1 FROM po_billings b WHERE b.po_id = po.id)
            ORDER BY po.created_at DESC
            """
        ).fetchall()
    return [int(row["id"]) for row in rows]


def insert_po_billing_for_po(
    po_id: int,
    *,
    quantity: Optional[float] = None,
    unit_cost: Optional[float] = None,
    billing_pct: Optional[int] = None,
    notes: Optional[str] = None,
    vendor_invoice_raw: Optional[str] = None,
    vendor_invoice_gst: Optional[str] = None,
) -> int:
    init_db()
    po = get_purchase_order(po_id)
    if not po:
        raise ValueError("Purchase order not found")
    if sum_received_for_po(po_id) <= 0:
        raise ValueError("Receive stock on this PO first (at least one receipt)")
    if get_po_billing_by_po_id(po_id) is not None:
        raise ValueError("Billing already recorded for this PO")
    vn = get_vendor(po.vendor_id)
    if not vn:
        raise ValueError("Vendor not found")
    pr = get_vendor_product(po.product_id)
    q = float(po.quantity) if quantity is None else float(quantity)
    ucost = float(po.unit_cost) if unit_cost is None else float(unit_cost)
    bline = po.billing if billing_pct is None else billing_pct
    n_raw = (
        (str(notes).strip() or None)
        if notes is not None
        else None
    )
    v_raw = None if vendor_invoice_raw is None else (str(vendor_invoice_raw).strip() or None)
    v_gst = None if vendor_invoice_gst is None else (str(vendor_invoice_gst).strip() or None)
    raw_line, gst_taxable, gst_amt, gst_grand = compute_po_billing_amounts(
        q,
        ucost,
        bline,
        None,
    )
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO po_billings (
                po_id, vendor_id, quantity, unit_cost, billing_pct, gst_rate_pct,
                raw_line_total, gst_taxable_total, gst_amount, gst_grand_total,
                vendor_invoice_raw, vendor_invoice_gst, notes,
                snap_vendor_person, snap_vendor_company, snap_vendor_phone,
                snap_issuer_legal_name, snap_issuer_address, snap_issuer_city_pin,
                snap_issuer_gstin, snap_issuer_phone, snap_issuer_email,
                snap_item_sku, snap_item_name,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                po_id,
                po.vendor_id,
                q,
                ucost,
                bline,
                None,
                raw_line,
                0.0,
                0.0,
                0.0,
                v_raw,
                v_gst,
                n_raw,
                vn.person_name,
                vn.company_name,
                vn.primary_phone,
                vn.issuer_legal_name,
                vn.issuer_address,
                vn.issuer_city_pin,
                vn.issuer_gstin,
                vn.issuer_phone,
                vn.issuer_email,
                pr.our_product_id if pr else "",
                pr.name if pr else "",
                None,
            ),
        )
        bid = int(cur.lastrowid)
        conn.commit()
        jid = _post_gl_purchase_bill(bid, raw_line)
        with _connect() as c2:
            c2.execute(
                "UPDATE po_billings SET gl_journal_id = ? WHERE id = ?",
                (jid, bid),
            )
            c2.commit()
        return bid


def update_po_billing_record(
    bid: int,
    *,
    snap_vendor_person: str,
    snap_vendor_company: Optional[str],
    snap_vendor_phone: Optional[str],
    snap_issuer_legal_name: Optional[str],
    snap_issuer_address: Optional[str],
    snap_issuer_city_pin: Optional[str],
    snap_issuer_gstin: Optional[str],
    snap_issuer_phone: Optional[str],
    snap_issuer_email: Optional[str],
    snap_item_sku: str,
    snap_item_name: str,
    quantity: float,
    unit_cost: float,
    billing_pct: Optional[int],
    gst_rate_pct: Optional[float],
    vendor_invoice_raw: Optional[str],
    vendor_invoice_gst: Optional[str],
    notes: str,
) -> None:
    init_db()
    raw_line, gst_taxable, gst_amt, gst_grand = compute_po_billing_amounts(
        quantity,
        unit_cost,
        billing_pct,
        None,
    )
    ra = None if vendor_invoice_raw is None else (str(vendor_invoice_raw).strip() or None)
    ga = None if vendor_invoice_gst is None else (str(vendor_invoice_gst).strip() or None)
    with _connect() as conn:
        conn.execute(
            """
            UPDATE po_billings SET
                quantity = ?, unit_cost = ?, billing_pct = ?, gst_rate_pct = ?,
                raw_line_total = ?, gst_taxable_total = ?, gst_amount = ?, gst_grand_total = ?,
                snap_vendor_person = ?, snap_vendor_company = ?, snap_vendor_phone = ?,
                snap_issuer_legal_name = ?, snap_issuer_address = ?, snap_issuer_city_pin = ?,
                snap_issuer_gstin = ?, snap_issuer_phone = ?, snap_issuer_email = ?,
                snap_item_sku = ?, snap_item_name = ?,
                vendor_invoice_raw = ?, vendor_invoice_gst = ?, notes = ?,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (
                float(quantity),
                float(unit_cost),
                billing_pct,
                None,
                raw_line,
                0.0,
                0.0,
                0.0,
                snap_vendor_person.strip(),
                (snap_vendor_company or "").strip() or None,
                (snap_vendor_phone or "").strip() or None,
                (snap_issuer_legal_name or "").strip() or None,
                (snap_issuer_address or "").strip() or None,
                (snap_issuer_city_pin or "").strip() or None,
                (snap_issuer_gstin or "").strip() or None,
                (snap_issuer_phone or "").strip() or None,
                (snap_issuer_email or "").strip() or None,
                (snap_item_sku or "").strip(),
                (snap_item_name or "").strip(),
                ra,
                ga,
                (notes or None) or None,
                bid,
            ),
        )
        conn.commit()


def refresh_po_billing_from_po(bid: int) -> None:
    init_db()
    b = get_po_billing(bid)
    if not b:
        raise ValueError("Billing row not found")
    po = get_purchase_order(b.po_id)
    if not po:
        raise ValueError("Purchase order missing")
    raw_line, gst_taxable, gst_amt, gst_grand = compute_po_billing_amounts(
        po.quantity,
        po.unit_cost,
        po.billing,
        None,
    )
    with _connect() as conn:
        conn.execute(
            """
            UPDATE po_billings SET
                vendor_id = ?, quantity = ?, unit_cost = ?, billing_pct = ?, gst_rate_pct = ?,
                raw_line_total = ?, gst_taxable_total = ?, gst_amount = ?, gst_grand_total = ?,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (
                po.vendor_id,
                float(po.quantity),
                float(po.unit_cost),
                po.billing,
                None,
                raw_line,
                0.0,
                0.0,
                0.0,
                bid,
            ),
        )
        conn.commit()


def delete_po_billing(bid: int) -> None:
    init_db()
    b = get_po_billing(bid)
    if b and getattr(b, "gl_journal_id", None):
        from gl import post_reversal

        post_reversal(
            int(b.gl_journal_id),
            _today_iso(),
            f"Reverse POB#{bid} delete",
            "po_billing_del",
            bid,
        )
    with _connect() as conn:
        conn.execute("DELETE FROM po_billings WHERE id = ?", (bid,))
        conn.commit()


def _sum_ar_paid_for_cob(cob_id: int, conn) -> float:
    return float(
        conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS s FROM ar_payments WHERE co_billing_id = ?",
            (cob_id,),
        ).fetchone()["s"]
    )


def _sum_ar_paid_for_invoice(invoice_id: int, conn) -> float:
    return float(
        conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS s FROM ar_payments WHERE customer_invoice_id = ?",
            (invoice_id,),
        ).fetchone()["s"]
    )


def _sum_ap_paid_for_pob(pob_id: int, conn) -> float:
    return float(
        conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS s FROM ap_payments WHERE po_billing_id = ?",
            (pob_id,),
        ).fetchone()["s"]
    )


def _sum_ap_paid_for_vendor_bill_doc(vendor_bill_doc_id: int, conn) -> float:
    return float(
        conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS s FROM ap_payments WHERE vendor_bill_doc_id = ?",
            (vendor_bill_doc_id,),
        ).fetchone()["s"]
    )


def get_ar_open_balance(cob_id: Optional[int] = None, *, customer_invoice_id: Optional[int] = None) -> float:
    init_db()
    with _connect() as conn:
        if customer_invoice_id is not None:
            row = conn.execute(
                "SELECT grand_total FROM customer_invoice_docs WHERE id = ?",
                (int(customer_invoice_id),),
            ).fetchone()
            if not row:
                return 0.0
            return float(row["grand_total"]) - _sum_ar_paid_for_invoice(int(customer_invoice_id), conn)
        if cob_id is None:
            return 0.0
        b = get_customer_order_billing(int(cob_id))
        if not b:
            return 0.0
        p = _sum_ar_paid_for_cob(int(cob_id), conn)
        return float(b.raw_line_total) - p


def get_ap_open_balance(pob_id: Optional[int] = None, *, vendor_bill_doc_id: Optional[int] = None) -> float:
    init_db()
    with _connect() as conn:
        if vendor_bill_doc_id is not None:
            row = conn.execute(
                "SELECT grand_total FROM vendor_bill_docs WHERE id = ?",
                (int(vendor_bill_doc_id),),
            ).fetchone()
            if not row:
                return 0.0
            return float(row["grand_total"]) - _sum_ap_paid_for_vendor_bill_doc(int(vendor_bill_doc_id), conn)
        if pob_id is None:
            return 0.0
        b = get_po_billing(int(pob_id))
        if not b:
            return 0.0
        p = _sum_ap_paid_for_pob(int(pob_id), conn)
        return float(b.raw_line_total) - p


def insert_ar_payment(
    co_billing_id: Optional[int], amount: float, method: Optional[str], note: Optional[str], *, customer_invoice_id: Optional[int] = None
) -> int:
    init_db()
    a = float(amount)
    if a <= 0:
        raise ValueError("Amount must be positive")
    with _connect() as conn:
        if customer_invoice_id is not None:
            row = conn.execute("SELECT grand_total FROM customer_invoice_docs WHERE id = ?", (int(customer_invoice_id),)).fetchone()
            if not row:
                raise ValueError("Customer invoice not found")
            p = _sum_ar_paid_for_invoice(int(customer_invoice_id), conn)
            if p + a > float(row["grand_total"]) + 1e-4:
                raise ValueError("Payment exceeds open balance.")
        else:
            b = get_customer_order_billing(int(co_billing_id or 0))
            if not b:
                raise ValueError("Customer billing not found")
            p = _sum_ar_paid_for_cob(int(co_billing_id), conn)
            if p + a > float(b.raw_line_total) + 1e-4:
                raise ValueError("Payment exceeds open balance (raw bill total).")
        m2 = (method or "").strip() or None
        n2 = (note or "").strip() or None
        cur = conn.execute(
            """
            INSERT INTO ar_payments (co_billing_id, customer_invoice_id, amount, method, note)
            VALUES (?, ?, ?, ?, ?)
            """,
            (int(co_billing_id) if co_billing_id is not None else None, int(customer_invoice_id) if customer_invoice_id is not None else None, a, m2, n2),
        )
        pid = int(cur.lastrowid)
        conn.commit()
    jid = _post_gl_ar_receipt(pid, a)
    with _connect() as c2:
        c2.execute("UPDATE ar_payments SET gl_journal_id = ? WHERE id = ?", (jid, pid))
        c2.commit()
    return pid


def insert_ap_payment(
    po_billing_id: Optional[int], amount: float, method: Optional[str], note: Optional[str], *, vendor_bill_doc_id: Optional[int] = None
) -> int:
    init_db()
    a = float(amount)
    if a <= 0:
        raise ValueError("Amount must be positive")
    with _connect() as conn:
        if vendor_bill_doc_id is not None:
            row = conn.execute("SELECT grand_total FROM vendor_bill_docs WHERE id = ?", (int(vendor_bill_doc_id),)).fetchone()
            if not row:
                raise ValueError("Vendor bill not found")
            p = _sum_ap_paid_for_vendor_bill_doc(int(vendor_bill_doc_id), conn)
            if p + a > float(row["grand_total"]) + 1e-4:
                raise ValueError("Payment exceeds open balance.")
        else:
            b = get_po_billing(int(po_billing_id or 0))
            if not b:
                raise ValueError("Purchase billing not found")
            p = _sum_ap_paid_for_pob(int(po_billing_id), conn)
            if p + a > float(b.raw_line_total) + 1e-4:
                raise ValueError("Payment exceeds open balance (raw bill total).")
        m2 = (method or "").strip() or None
        n2 = (note or "").strip() or None
        cur = conn.execute(
            """
            INSERT INTO ap_payments (po_billing_id, vendor_bill_doc_id, amount, method, note)
            VALUES (?, ?, ?, ?, ?)
            """,
            (int(po_billing_id) if po_billing_id is not None else None, int(vendor_bill_doc_id) if vendor_bill_doc_id is not None else None, a, m2, n2),
        )
        pid = int(cur.lastrowid)
        conn.commit()
    jid = _post_gl_ap_payment(pid, a)
    with _connect() as c2:
        c2.execute("UPDATE ap_payments SET gl_journal_id = ? WHERE id = ?", (jid, pid))
        c2.commit()
    return pid


def ar_ledger_rows() -> List[dict]:
    init_db()
    with _connect() as conn:
        legacy_rows = conn.execute(
            """
            SELECT
              c.id AS cob_id,
              c.customer_order_id,
              c.snap_customer_name,
              c.raw_line_total,
              (SELECT COALESCE(SUM(p.amount), 0) FROM ar_payments p
               WHERE p.co_billing_id = c.id) AS paid
            FROM customer_order_billings c
            ORDER BY c.id DESC
            """
        ).fetchall()
        invoice_rows = conn.execute(
            """
            SELECT
              i.id AS customer_invoice_id,
              i.invoice_no,
              i.sales_order_id,
              i.grand_total,
              c.name AS customer_name,
              (SELECT COALESCE(SUM(p.amount), 0) FROM ar_payments p
               WHERE p.customer_invoice_id = i.id) AS paid
            FROM customer_invoice_docs i
            JOIN customers c ON c.id = i.customer_id
            ORDER BY i.id DESC
            """
        ).fetchall()
    out: List[dict] = []
    for r in legacy_rows:
        inv = float(r["raw_line_total"])
        paid = float(r["paid"])
        out.append(
            {
                "doc_type": "Legacy sales bill",
                "cob_id": int(r["cob_id"]),
                "customer_order_id": int(r["customer_order_id"]),
                "customer": (r["snap_customer_name"] or "—")[:64],
                "raw_bill_₹": inv,
                "paid_₹": paid,
                "balance_₹": inv - paid,
            }
        )
    for r in invoice_rows:
        inv = float(r["grand_total"])
        paid = float(r["paid"])
        out.append(
            {
                "doc_type": "Customer invoice",
                "customer_invoice_id": int(r["customer_invoice_id"]),
                "invoice_no": r["invoice_no"],
                "customer_order_id": int(r["sales_order_id"]),
                "customer": (r["customer_name"] or "—")[:64],
                "raw_bill_₹": inv,
                "paid_₹": paid,
                "balance_₹": inv - paid,
            }
        )
    return out


def ap_ledger_rows() -> List[dict]:
    init_db()
    with _connect() as conn:
        legacy_rows = conn.execute(
            """
            SELECT
              b.id AS pob_id,
              b.po_id,
              b.raw_line_total,
              (SELECT COALESCE(SUM(p.amount), 0) FROM ap_payments p
               WHERE p.po_billing_id = b.id) AS paid,
              b.vendor_id
            FROM po_billings b
            ORDER BY b.id DESC
            """
        ).fetchall()
        bill_rows = conn.execute(
            """
            SELECT
              b.id AS vendor_bill_doc_id,
              b.bill_no,
              b.po_doc_id,
              b.grand_total,
              b.vendor_id,
              (SELECT COALESCE(SUM(p.amount), 0) FROM ap_payments p
               WHERE p.vendor_bill_doc_id = b.id) AS paid
            FROM vendor_bill_docs b
            ORDER BY b.id DESC
            """
        ).fetchall()
    vmap = {v.id: v for v in list_vendors()}
    out: List[dict] = []
    for r in legacy_rows:
        inv = float(r["raw_line_total"])
        paid = float(r["paid"])
        v = vmap.get(int(r["vendor_id"]))
        vlabel = (v.person_name or "—") if v else "—"
        out.append(
            {
                "doc_type": "Legacy purchase bill",
                "pob_id": int(r["pob_id"]),
                "po_id": int(r["po_id"]),
                "vendor": vlabel,
                "raw_bill_₹": inv,
                "paid_₹": paid,
                "balance_₹": inv - paid,
            }
        )
    for r in bill_rows:
        inv = float(r["grand_total"])
        paid = float(r["paid"])
        v = vmap.get(int(r["vendor_id"]))
        vlabel = (v.person_name or "—") if v else "—"
        out.append(
            {
                "doc_type": "Vendor bill",
                "vendor_bill_doc_id": int(r["vendor_bill_doc_id"]),
                "bill_no": r["bill_no"],
                "po_id": int(r["po_doc_id"]),
                "vendor": vlabel,
                "raw_bill_₹": inv,
                "paid_₹": paid,
                "balance_₹": inv - paid,
            }
        )
    return out


def list_ar_payments_log() -> List[dict]:
    init_db()
    with _connect() as conn:
        legacy_rows = conn.execute(
            """
            SELECT
              p.id, p.co_billing_id, p.amount, p.paid_at, p.method, p.note,
              c.snap_customer_name, c.customer_order_id, c.raw_line_total
            FROM ar_payments p
            JOIN customer_order_billings c ON c.id = p.co_billing_id
            ORDER BY p.paid_at DESC, p.id DESC
            """
        ).fetchall()
        invoice_rows = conn.execute(
            """
            SELECT
              p.id, p.customer_invoice_id, p.amount, p.paid_at, p.method, p.note,
              i.invoice_no, i.sales_order_id, c.name AS customer_name
            FROM ar_payments p
            JOIN customer_invoice_docs i ON i.id = p.customer_invoice_id
            JOIN customers c ON c.id = i.customer_id
            WHERE p.customer_invoice_id IS NOT NULL
            ORDER BY p.paid_at DESC, p.id DESC
            """
        ).fetchall()
    out = []
    for x in legacy_rows:
        d = dict(x)
        d["doc_type"] = "Legacy sales bill"
        out.append(d)
    for x in invoice_rows:
        d = dict(x)
        d["doc_type"] = "Customer invoice"
        d["snap_customer_name"] = d.pop("customer_name")
        d["customer_order_id"] = d.pop("sales_order_id")
        out.append(d)
    out.sort(key=lambda x: (x.get("paid_at") or "", int(x.get("id") or 0)), reverse=True)
    return out


def list_ap_payments_log() -> List[dict]:
    init_db()
    with _connect() as conn:
        legacy_rows = conn.execute(
            """
            SELECT
              p.id, p.po_billing_id, p.amount, p.paid_at, p.method, p.note,
              b.po_id, b.raw_line_total, b.vendor_id
            FROM ap_payments p
            JOIN po_billings b ON b.id = p.po_billing_id
            ORDER BY p.paid_at DESC, p.id DESC
            """
        ).fetchall()
        doc_rows = conn.execute(
            """
            SELECT
              p.id, p.vendor_bill_doc_id, p.amount, p.paid_at, p.method, p.note,
              b.bill_no, b.po_doc_id, b.vendor_id
            FROM ap_payments p
            JOIN vendor_bill_docs b ON b.id = p.vendor_bill_doc_id
            WHERE p.vendor_bill_doc_id IS NOT NULL
            ORDER BY p.paid_at DESC, p.id DESC
            """
        ).fetchall()
    vmap = {v.id: v for v in list_vendors()}
    out: List[dict] = []
    for r in legacy_rows:
        m = dict(r)
        v = vmap.get(int(m["vendor_id"]) if m.get("vendor_id") is not None else 0)
        m["vendor_name"] = (v.person_name or "—") if v else "—"
        m["doc_type"] = "Legacy purchase bill"
        out.append(m)
    for r in doc_rows:
        m = dict(r)
        v = vmap.get(int(m["vendor_id"]) if m.get("vendor_id") is not None else 0)
        m["vendor_name"] = (v.person_name or "—") if v else "—"
        m["po_id"] = m.pop("po_doc_id")
        m["po_billing_id"] = None
        m["doc_type"] = "Vendor bill"
        out.append(m)
    out.sort(key=lambda x: (x.get("paid_at") or "", int(x.get("id") or 0)), reverse=True)
    return out


def delete_ar_payment(pid: int) -> None:
    init_db()
    with _connect() as conn:
        r = conn.execute("SELECT id, gl_journal_id FROM ar_payments WHERE id = ?", (pid,)).fetchone()
        if not r:
            raise ValueError("AR payment not found")
        gj = r["gl_journal_id"]
    if gj:
        from gl import post_reversal

        post_reversal(
            int(gj), _today_iso(), f"Reverse AR pay #{pid}", "ar_del", pid
        )
    with _connect() as conn:
        conn.execute("DELETE FROM ar_payments WHERE id = ?", (pid,))
        conn.commit()


def delete_ap_payment(pid: int) -> None:
    init_db()
    with _connect() as conn:
        r = conn.execute("SELECT id, gl_journal_id FROM ap_payments WHERE id = ?", (pid,)).fetchone()
        if not r:
            raise ValueError("AP payment not found")
        gj = r["gl_journal_id"]
    if gj:
        from gl import post_reversal

        post_reversal(
            int(gj), _today_iso(), f"Reverse AP pay #{pid}", "ap_del", pid
        )
    with _connect() as conn:
        conn.execute("DELETE FROM ap_payments WHERE id = ?", (pid,))
        conn.commit()
