"""Item movement for year group 2026-27. DCU stays out unless asked for."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.catalog_product import CatalogProduct
from app.models.stock import StockLedger
from app.models.vendor import Vendor
from app.services.biz_date import ist_range_bounds_utc, to_ist
from app.services.reports.stock_group_summary import (
    _INWARD_TYPES,
    _Row,
    _add_inwards,
    _add_sales,
    _closing_qty,
    _d,
    _q2,
    period_label,
)

DEFAULT_YEAR = "2026-27"


def _is_dcu(product: CatalogProduct) -> bool:
    for value in (product.category, product.second_category, product.category_3):
        if (value or "").strip().upper() == "DCU":
            return True
    return False


def _last_inward(db: Session, product_ids: list[int], to_date: Optional[date]) -> dict[int, date]:
    if not product_ids:
        return {}
    q = (
        db.query(StockLedger.catalog_product_id, func.max(StockLedger.created_at))
        .filter(
            StockLedger.catalog_product_id.in_(product_ids),
            StockLedger.entry_type.in_(_INWARD_TYPES),
            StockLedger.quantity_delta > 0,
        )
    )
    if to_date is not None:
        _start, end = ist_range_bounds_utc(to_date, to_date)
        q = q.filter(StockLedger.created_at <= end)
    out = {}
    for pid, stamp in q.group_by(StockLedger.catalog_product_id).all():
        if stamp is not None:
            out[int(pid)] = to_ist(stamp).date()
    return out


def vendor_order_report(
    db: Session,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    *,
    year_group: str = DEFAULT_YEAR,
    include_dcu: bool = False,
) -> dict:
    year = (year_group or DEFAULT_YEAR).strip() or DEFAULT_YEAR
    products = (
        db.query(CatalogProduct)
        .filter(
            CatalogProduct.deleted_at.is_(None),
            CatalogProduct.is_active.is_(True),
            CatalogProduct.year_group == year,
        )
        .all()
    )
    if not include_dcu:
        products = [p for p in products if not _is_dcu(p)]
    ids = [p.id for p in products]
    store: dict[int, _Row] = {}
    _add_sales(db, store, from_date, to_date)
    _add_inwards(db, store, from_date, to_date)
    closing = _closing_qty(db, ids, to_date)
    last_in = _last_inward(db, ids, to_date)
    vendor_ids = {p.vendor_id for p in products if p.vendor_id}
    vendors = {
        v.id: v.business_name
        for v in db.query(Vendor).filter(Vendor.id.in_(vendor_ids)).all()
    } if vendor_ids else {}
    items = []
    for product in products:
        moved = store.get(product.id) or _Row()
        inward = _q2(moved.in_qty)
        outward = _q2(moved.out_qty)
        close_qty = _q2(_d(closing.get(product.id, 0)))
        rate = _q2(_d(product.buying_price)) if product.buying_price is not None else Decimal("0")
        ratio = None
        if inward > 0:
            ratio = _q2(close_qty / inward * Decimal("100"))
        items.append({
            "id": product.id,
            "item_no": product.our_product_id,
            "company_no": product.vendor_product_id or "",
            "company_name": vendors.get(product.vendor_id, ""),
            "category": product.category or "",
            "invoices": len(moved.bills),
            "inward_qty": f"{inward:.2f}",
            "outward_qty": f"{outward:.2f}",
            "closing_qty": f"{close_qty:.2f}",
            "purchase_rate": f"{rate:.2f}",
            "closing_value": f"{_q2(close_qty * rate):.2f}",
            "last_inward_date": last_in.get(product.id).isoformat() if product.id in last_in else None,
            "stock_ratio": f"{ratio:.2f}" if ratio is not None else None,
        })
    items.sort(key=lambda row: (row["company_name"].lower(), row["item_no"].lower()))
    return {
        "year_group": year,
        "include_dcu": include_dcu,
        "period": period_label(from_date, to_date),
        "from_date": from_date.isoformat() if from_date else None,
        "to_date": to_date.isoformat() if to_date else None,
        "items": items,
    }
