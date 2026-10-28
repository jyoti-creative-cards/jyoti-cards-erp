from __future__ import annotations
"""Split from app/services/ledger.py."""

from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models.catalog_product import CatalogProduct
from app.models.stock import StockReceipt, StockReceiptLine
from app.models.debit_note import DebitNote
from app.models.accounts_payable import ApLedgerEntry
from app.models.vendor_order import VendorOrder, VendorOrderLine, VendorOrderPlacement
from app.deps import AuthContext
from app.models.vendor import Vendor
from app.models.customer import Customer
from app.services.ap_ledger import debit_note_payable_effect
from app.services.cost_visibility import hide_cost
from app.schemas.ledger import EntityLedgerEntry, LedgerLineDetail
from app.services.storage import presigned_url

_IST = ZoneInfo("Asia/Kolkata")

def _product_maps(db: Session, product_ids: set[int]) -> tuple[dict[int, str], dict[int, Optional[str]]]:
    ids = {int(pid) for pid in product_ids if pid}
    if not ids:
        return {}, {}
    rows = (
        db.query(CatalogProduct.id, CatalogProduct.our_product_id, CatalogProduct.vendor_product_id)
        .filter(CatalogProduct.id.in_(ids))
        .all()
    )
    return {p.id: p.our_product_id for p in rows}, {p.id: p.vendor_product_id for p in rows}

def _doc_status(row) -> str:
    if row is None:
        return "open"
    if getattr(row, "deleted_at", None):
        return "voided"
    if getattr(row, "cancelled_at", None) or getattr(row, "status", None) == "cancelled":
        return "cancelled"
    return "open"

def _sortable_ts(ts: datetime) -> datetime:
    """Sort key. Postgres timestamps are timezone-aware; bill dates become naive UTC."""
    if ts.tzinfo is None:
        return ts
    return ts.astimezone(timezone.utc).replace(tzinfo=None)

def _fmt_amount(val: Optional[Decimal]) -> Optional[str]:
    if val is None:
        return None
    return format(val, "f")

def _actor_fields(actor_name: str, actor_type: str, show_actor: bool) -> dict:
    if not show_actor:
        return {"actor_name": None, "actor_type": None}
    return {"actor_name": actor_name, "actor_type": actor_type}

def _line_name(live: Optional[str], stored: Optional[str]) -> str:
    return live or stored or "—"

def _occurred_at_from_display(display_date, fallback: datetime) -> datetime:
    """Ledger sort key from present() display_date; plain dates → IST noon as naive UTC."""
    if display_date is None:
        return fallback
    if isinstance(display_date, datetime):
        ts = display_date if display_date.tzinfo else display_date.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc).replace(tzinfo=None)
    if isinstance(display_date, date):
        local = datetime(display_date.year, display_date.month, display_date.day, 12, 0, 0, tzinfo=_IST)
        return local.astimezone(timezone.utc).replace(tzinfo=None)
    return fallback

