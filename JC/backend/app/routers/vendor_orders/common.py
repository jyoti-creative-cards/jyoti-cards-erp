from __future__ import annotations
"""Split from app/routers/vendor_orders.py."""

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import AuthContext, require_permission
from app.models.catalog_alternative import CatalogAlternative
from app.models.catalog_product import CatalogProduct
from app.models.city import City
from app.models.vendor import Vendor
from app.models.vendor_order import VendorOrder, VendorOrderLine, VendorOrderPlacement
from app.models.vendor_open_line import VendorOpenLine
from app.models.stock import StockReceipt, StockReceiptLine
from app.schemas.vendor_order import (
    AggregatedLine,
    CatalogProductForOrder,
    OrderSummaryDrillDown,
    OrderSummaryEvent,
    OrderSummaryLine,
    PlacementCreate,
    PlacementLineDetail,
    PlacementSummary,
    VendorOrderDetail,
    VendorOrderLineUpdate,
    VendorOrderSummary,
    VendorOrderSummaryDetail,
    OpenLineOut,
    OpenVendorDetail,
    ClosedLineOut,
    OpenLineUpdate,
    CloseableVendorItemOut,
    CloseBatchIn,
    ReasonIn,
)
from app.services.activity import log_from_auth
from app.services.ap_ledger import receipt_bill_amount, receipt_debit_note_total
from app.services.biz_date import ist_day_bounds_utc, today_ist
from app.services.cost_visibility import hide_cost
from app.services.open_lines import add_to_open, cancel_open_qty, close_open_line, cancel_open_line, open_lines_for_vendor, reduce_from_open
from app.services.order_summary import pending_qty_by_product, placed_qty_by_product, received_qty_by_product
from app.services.stock_receipt import get_or_create_open_order
from app.services.doc_gen import generate_vendor_placement_document
from app.services.document_present import present
from app.services.storage import presigned_url, presigned_urls, storage_configured

def _placement_color_map(placements: list[VendorOrderPlacement]) -> dict[int, int]:
    ordered = sorted(placements, key=lambda p: (p.placed_at, p.id))
    return {p.id: idx for idx, p in enumerate(ordered)}

def _vendor_context(db: Session, vendor_id: int, *, require_active: bool = True) -> tuple[Vendor, Optional[str], str]:
    vendor = db.get(Vendor, vendor_id)
    if not vendor:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor not found")
    if require_active and vendor.deleted_at:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor not found")
    city_name = None
    if vendor.city_id:
        city = db.get(City, vendor.city_id)
        city_name = city.name if city else None
    label = _vendor_label(vendor, city_name)
    if vendor.deleted_at:
        label = f"{label} (deleted)"
    return vendor, city_name, label

def _vendor_contexts(db: Session, vendor_ids: set[int]) -> dict[int, tuple[Vendor, Optional[str], str]]:
    """Batched _vendor_context (require_active=False) — one query for N vendors instead of N."""
    if not vendor_ids:
        return {}
    vendors = {v.id: v for v in db.query(Vendor).filter(Vendor.id.in_(vendor_ids)).all()}
    city_ids = {v.city_id for v in vendors.values() if v.city_id}
    cities = {c.id: c.name for c in db.query(City).filter(City.id.in_(city_ids)).all()} if city_ids else {}
    out: dict[int, tuple[Vendor, Optional[str], str]] = {}
    for vid, vendor in vendors.items():
        city_name = cities.get(vendor.city_id) if vendor.city_id else None
        label = _vendor_label(vendor, city_name)
        if vendor.deleted_at:
            label = f"{label} (deleted)"
        out[vid] = (vendor, city_name, label)
    return out

def _vendor_label(vendor: Vendor, city_name: Optional[str]) -> str:
    city = city_name or ""
    return f"{vendor.business_name} — {city}" if city else vendor.business_name

