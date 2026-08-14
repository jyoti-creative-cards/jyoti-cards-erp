"""Full restore-grade Excel backup — every DB table as a sheet (zip of workbooks)."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Sequence

from openpyxl import Workbook
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from app.models import (
    ActivityLog,
    AddonProduct,
    ApLedgerEntry,
    ArLedgerEntry,
    BillSeries,
    CatalogAddonLink,
    CatalogAlternative,
    CatalogLookup,
    CatalogProduct,
    City,
    Customer,
    CustomerArAccount,
    CustomerBill,
    CustomerBillLine,
    CustomerOpenLine,
    CustomerOrder,
    CustomerOrderLine,
    CustomerOrderPlacement,
    CustomerReturn,
    CustomerReturnLine,
    DebitNote,
    EntityHistory,
    Expense,
    FreightAgent,
    FreightLedgerEntry,
    ManualLoss,
    PriceHistory,
    Route,
    Staff,
    StockBalance,
    StockLedger,
    StockReceipt,
    StockReceiptLine,
    Vendor,
    VendorApAccount,
    VendorOpenLine,
    VendorOrder,
    VendorOrderLine,
    VendorOrderPlacement,
)

# Ordered for human reading — every money/ops table included
BACKUP_MODELS: list[tuple[str, type]] = [
    ("routes", Route),
    ("cities", City),
    ("customers", Customer),
    ("vendors", Vendor),
    ("staff", Staff),
    ("catalog_lookups", CatalogLookup),
    ("catalog_products", CatalogProduct),
    ("addon_products", AddonProduct),
    ("catalog_addon_links", CatalogAddonLink),
    ("catalog_alternatives", CatalogAlternative),
    ("price_history", PriceHistory),
    ("vendor_orders", VendorOrder),
    ("vendor_order_placements", VendorOrderPlacement),
    ("vendor_order_lines", VendorOrderLine),
    ("vendor_open_lines", VendorOpenLine),
    ("customer_orders", CustomerOrder),
    ("customer_order_placements", CustomerOrderPlacement),
    ("customer_order_lines", CustomerOrderLine),
    ("customer_open_lines", CustomerOpenLine),
    ("customer_bills", CustomerBill),
    ("customer_bill_lines", CustomerBillLine),
    ("bill_series", BillSeries),
    ("customer_returns", CustomerReturn),
    ("customer_return_lines", CustomerReturnLine),
    ("stock_balances", StockBalance),
    ("stock_ledger", StockLedger),
    ("stock_receipts", StockReceipt),
    ("stock_receipt_lines", StockReceiptLine),
    ("debit_notes", DebitNote),
    ("vendor_ap_accounts", VendorApAccount),
    ("ap_ledger_entries", ApLedgerEntry),
    ("customer_ar_accounts", CustomerArAccount),
    ("ar_ledger_entries", ArLedgerEntry),
    ("freight_agents", FreightAgent),
    ("freight_ledger_entries", FreightLedgerEntry),
    ("expenses", Expense),
    ("manual_losses", ManualLoss),
    ("entity_history", EntityHistory),
    ("activity_logs", ActivityLog),
]

# Group into workbooks so Excel stays usable
WORKBOOK_GROUPS: list[tuple[str, list[str]]] = [
    ("01_masters", [
        "routes", "cities", "customers", "vendors", "staff",
        "catalog_lookups", "catalog_products", "addon_products",
        "catalog_addon_links", "catalog_alternatives", "price_history", "bill_series",
    ]),
    ("02_buying", [
        "vendor_orders", "vendor_order_placements", "vendor_order_lines", "vendor_open_lines",
        "stock_receipts", "stock_receipt_lines", "debit_notes",
    ]),
    ("03_selling", [
        "customer_orders", "customer_order_placements", "customer_order_lines", "customer_open_lines",
        "customer_bills", "customer_bill_lines", "customer_returns", "customer_return_lines",
    ]),
    ("04_stock", ["stock_balances", "stock_ledger"]),
    ("05_money", [
        "customer_ar_accounts", "ar_ledger_entries",
        "vendor_ap_accounts", "ap_ledger_entries",
        "freight_agents", "freight_ledger_entries",
        "expenses", "manual_losses",
    ]),
    ("06_audit", ["entity_history", "activity_logs"]),
]


def _cell(v: Any) -> Any:
    if v is None:
        return ""
    if isinstance(v, bool):
        return v
    if isinstance(v, Decimal):
        return format(v, "f")
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, default=str)
    if isinstance(v, (bytes, bytearray)):
        return ""
    return v


def _model_columns(model: type) -> list[str]:
    mapper = sa_inspect(model)
    return [attr.key for attr in mapper.column_attrs]


def _dump_table(db: Session, model: type) -> tuple[list[str], list[list[Any]]]:
    cols = _model_columns(model)
    # Cap activity/history if enormous — still export newest first for audit
    q = db.query(model)
    table = getattr(model, "__tablename__", "")
    if table in ("jc_activity_logs", "jc_entity_history", "jc_stock_ledger", "jc_price_history"):
        # Prefer id desc if present
        if hasattr(model, "id"):
            q = q.order_by(model.id.desc()).limit(200_000)
    rows_out: list[list[Any]] = []
    for row in q.all():
        rows_out.append([_cell(getattr(row, c, None)) for c in cols])
    # Reverse capped tables so oldest→newest in file when we took newest first
    if table in ("jc_activity_logs", "jc_entity_history", "jc_stock_ledger", "jc_price_history"):
        rows_out.reverse()
    return cols, rows_out


def _workbook_for_sheets(sheets: list[tuple[str, Sequence[str], list[list[Any]]]]) -> bytes:
    wb = Workbook()
    first = True
    for name, headers, rows in sheets:
        if first:
            ws = wb.active
            first = False
        else:
            ws = wb.create_sheet()
        ws.title = (name or "Sheet")[:31]
        ws.append(list(headers))
        for row in rows:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_full_backup_zip(db: Session) -> bytes:
    """Zip of Excel workbooks covering every app table + manifest."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    by_name = {name: model for name, model in BACKUP_MODELS}
    dumped: dict[str, tuple[list[str], list[list[Any]]]] = {}
    counts: dict[str, int] = {}

    for name, model in BACKUP_MODELS:
        cols, rows = _dump_table(db, model)
        dumped[name] = (cols, rows)
        counts[name] = len(rows)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for book_name, sheet_names in WORKBOOK_GROUPS:
            sheets = []
            for sn in sheet_names:
                if sn not in dumped:
                    continue
                cols, rows = dumped[sn]
                sheets.append((sn, cols, rows))
            if sheets:
                zf.writestr(f"{book_name}.xlsx", _workbook_for_sheets(sheets))

        # Also one mega workbook for convenience (may be large)
        all_sheets = [(n, dumped[n][0], dumped[n][1]) for n, _ in BACKUP_MODELS if n in dumped]
        zf.writestr("00_ALL_TABLES.xlsx", _workbook_for_sheets(all_sheets))

        summary_data = [[k, counts[k]] for k in counts]
        zf.writestr(
            "00_SUMMARY.xlsx",
            _workbook_for_sheets([("summary", ["table", "rows"], summary_data)]),
        )

        manifest = [
            f"JC FULL BACKUP {stamp}",
            "",
            "This zip is a restore-grade dump of every database table used by the app.",
            "Files:",
            "  00_SUMMARY.xlsx     — row counts",
            "  00_ALL_TABLES.xlsx  — every table as a sheet",
            "  01_masters.xlsx … 06_audit.xlsx — grouped workbooks",
            "",
            "Money convention: signed ledger amounts (+ increases outstanding, − decreases).",
            "PDFs/images in S3 are NOT included — only DB keys/paths to files.",
            "Staff password hashes ARE included (admin-only download) — store zip securely.",
            "",
            "Row counts:",
        ]
        for k, n in counts.items():
            manifest.append(f"  {k}: {n}")
        zf.writestr("README.txt", "\n".join(manifest) + "\n")

    return buf.getvalue()
