"""Daily stock summary in the shape of the Tally stock group summary.

One row per item that moved between the dates. A confirmed order that is
later billed is counted on the bill only, so the same pieces are not added
twice. Closing is stock on hand at the end date, valued at the purchase rate.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.models.catalog_product import CatalogProduct
from app.models.customer_bill import CustomerBill, CustomerBillLine
from app.models.customer_order import CustomerOrderLine, CustomerOrderPlacement
from app.models.customer_return import CustomerReturn, CustomerReturnLine
from app.models.stock import StockLedger, StockReceiptLine
from app.models.vendor import Vendor
from app.services.biz_date import ist_range_bounds_utc, to_ist

# Stock added by us. Sales returns and order cancels are not inwards.
_INWARD_TYPES = (
    "received",
    "journal",
    "manual_adjustment",
    "opening",
    "receipt_adjustment",
    "void_receipt",
    "restore_receipt",
    "journal_void",
)


def _d(value) -> Decimal:
    return Decimal(str(value or 0))


def _q2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def _num(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return f"{_q2(value):.2f}"


def _rate(value: Decimal, qty: Decimal) -> Decimal | None:
    if qty == 0:
        return None
    return _q2(abs(value / qty))


def period_label(from_date: Optional[date], to_date: Optional[date]) -> str:
    if from_date and to_date and from_date == to_date:
        return f"For {_day(from_date)}"
    if from_date and to_date:
        return f"For {_day(from_date)} to {_day(to_date)}"
    if from_date:
        return f"From {_day(from_date)}"
    if to_date:
        return f"Up to {_day(to_date)}"
    return "All dates"


def _day(value: date) -> str:
    return value.strftime("%d-%b-%y")


def _stamp_in_range(column, from_date: Optional[date], to_date: Optional[date]):
    if from_date is None and to_date is None:
        return True
    start, end = ist_range_bounds_utc(from_date, to_date)
    clause = True
    if start is not None:
        clause = and_(clause, column >= start)
    if end is not None:
        clause = and_(clause, column <= end)
    return clause


def _dated_or_created(date_col, created_col, from_date: Optional[date], to_date: Optional[date]):
    """A real document date wins. Rows with no document date use created_at in IST."""
    if from_date is None and to_date is None:
        return True
    start, end = ist_range_bounds_utc(from_date, to_date)
    value_parts = []
    if from_date is not None:
        value_parts.append(date_col >= from_date)
    if to_date is not None:
        value_parts.append(date_col <= to_date)
    created_parts = [date_col.is_(None)]
    if start is not None:
        created_parts.append(created_col >= start)
    if end is not None:
        created_parts.append(created_col <= end)
    return or_(and_(*value_parts), and_(*created_parts))


class _Row:
    def __init__(self) -> None:
        self.bills: set[int] = set()
        self.orders: set[int] = set()
        self.in_qty = Decimal("0")
        self.in_value = Decimal("0")
        self.out_qty = Decimal("0")
        self.out_value = Decimal("0")


def _bucket(store: dict[int, _Row], product_id: int) -> _Row:
    row = store.get(product_id)
    if row is None:
        row = _Row()
        store[product_id] = row
    return row


def _particular(product: CatalogProduct) -> str:
    name = (product.our_product_id or "").strip() or f"#{product.id}"
    vendor_no = (product.vendor_product_id or "").strip()
    if vendor_no and vendor_no.lower() not in name.lower():
        return f"{name} ({vendor_no})"
    return name


def stock_group_summary(
    db: Session,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
) -> dict:
    store: dict[int, _Row] = {}
    _add_sales(db, store, from_date, to_date)
    _add_unbilled_orders(db, store, from_date, to_date)
    _add_returns(db, store, from_date, to_date)
    _add_inwards(db, store, from_date, to_date)

    active = [
        pid for pid, row in store.items()
        if row.bills or row.orders or row.in_qty != 0 or row.out_qty != 0
    ]
    closing = _closing_qty(db, active, to_date)
    products = {
        p.id: p
        for p in db.query(CatalogProduct).filter(CatalogProduct.id.in_(active)).all()
    } if active else {}
    vendor_ids = {p.vendor_id for p in products.values() if p.vendor_id}
    vendors = {
        v.id: v.business_name
        for v in db.query(Vendor).filter(Vendor.id.in_(vendor_ids)).all()
    } if vendor_ids else {}

    items = []
    totals = {
        "sales_count": 0,
        "in_qty": Decimal("0"),
        "in_value": Decimal("0"),
        "out_qty": Decimal("0"),
        "out_value": Decimal("0"),
        "close_qty": Decimal("0"),
        "close_value": Decimal("0"),
    }
    for pid in active:
        row = store[pid]
        product = products.get(pid)
        buy = _d(product.buying_price) if product and product.buying_price is not None else Decimal("0")
        close_qty = _d(closing.get(pid, 0))
        close_value = _q2(close_qty * buy)
        in_qty = _q2(row.in_qty)
        in_value = _q2(row.in_value)
        out_qty = _q2(row.out_qty)
        out_value = _q2(row.out_value)
        sales = len(row.bills) + len(row.orders)
        items.append({
            "id": pid,
            "particular": _particular(product) if product else f"#{pid}",
            "vendor_name": vendors.get(product.vendor_id, "") if product else "",
            "sales_count": sales,
            "in_qty": _num(in_qty) if in_qty != 0 else None,
            "in_rate": _num(_rate(in_value, in_qty)),
            "in_value": _num(in_value) if in_qty != 0 else None,
            "out_qty": _num(out_qty) if out_qty != 0 else None,
            "out_rate": _num(_rate(out_value, out_qty)),
            "out_value": _num(out_value) if out_qty != 0 else None,
            "close_qty": _num(close_qty) if close_qty != 0 else None,
            "close_rate": _num(buy) if close_qty != 0 else None,
            "close_value": _num(close_value) if close_qty != 0 else None,
        })
        totals["sales_count"] += sales
        totals["in_qty"] += in_qty
        totals["in_value"] += in_value
        totals["out_qty"] += out_qty
        totals["out_value"] += out_value
        totals["close_qty"] += close_qty
        totals["close_value"] += close_value

    items.sort(key=lambda item: (-_d(item["close_value"]), item["particular"]))
    printed = to_ist(datetime.now(timezone.utc)).strftime("%d-%b-%y at %H:%M")
    return {
        "from_date": from_date.isoformat() if from_date else None,
        "to_date": to_date.isoformat() if to_date else None,
        "period": period_label(from_date, to_date),
        "printed_on": printed,
        "items": items,
        "totals": {key: (value if key == "sales_count" else _num(_q2(value))) for key, value in totals.items()},
    }


def _add_sales(db: Session, store: dict[int, _Row], from_date: Optional[date], to_date: Optional[date]) -> None:
    rows = (
        db.query(
            CustomerBillLine.catalog_product_id,
            CustomerBill.id,
            CustomerBillLine.quantity_shipped,
            CustomerBillLine.line_total,
        )
        .join(CustomerBill, CustomerBill.id == CustomerBillLine.bill_id)
        .filter(
            CustomerBill.deleted_at.is_(None),
            CustomerBill.cancelled_at.is_(None),
            CustomerBillLine.status != "cancelled",
            CustomerBillLine.quantity_shipped > 0,
            _dated_or_created(CustomerBill.bill_date, CustomerBill.created_at, from_date, to_date),
        )
        .all()
    )
    for pid, bill_id, qty, value in rows:
        row = _bucket(store, int(pid))
        row.bills.add(int(bill_id))
        row.out_qty += _d(qty)
        row.out_value += _d(value)


def _add_unbilled_orders(db: Session, store: dict[int, _Row], from_date: Optional[date], to_date: Optional[date]) -> None:
    """Confirmed orders still waiting for a bill. Billed quantity stays on the bill."""
    rows = (
        db.query(CustomerOrderLine, CustomerOrderPlacement)
        .join(CustomerOrderPlacement, CustomerOrderPlacement.id == CustomerOrderLine.placement_id)
        .filter(
            CustomerOrderPlacement.deleted_at.is_(None),
            CustomerOrderPlacement.status == "open",
            CustomerOrderLine.status == "active",
            _stamp_in_range(CustomerOrderPlacement.placed_at, from_date, to_date),
        )
        .all()
    )
    for line, placement in rows:
        unbilled = int(line.quantity or 0) - int(line.quantity_billed or 0)
        if unbilled <= 0:
            continue
        row = _bucket(store, int(line.catalog_product_id))
        row.orders.add(int(placement.id))
        row.out_qty += Decimal(unbilled)
        row.out_value += Decimal(unbilled) * _d(line.unit_price)


def _add_returns(db: Session, store: dict[int, _Row], from_date: Optional[date], to_date: Optional[date]) -> None:
    rows = (
        db.query(CustomerReturnLine, CustomerReturn)
        .join(CustomerReturn, CustomerReturn.id == CustomerReturnLine.return_id)
        .filter(
            CustomerReturn.deleted_at.is_(None),
            CustomerReturnLine.quantity_returned > 0,
            _stamp_in_range(CustomerReturn.created_at, from_date, to_date),
        )
        .all()
    )
    for line, _ret in rows:
        row = _bucket(store, int(line.catalog_product_id))
        qty = _d(line.quantity_returned)
        row.out_qty -= qty
        row.out_value -= _d(line.line_calculated)


def _add_inwards(db: Session, store: dict[int, _Row], from_date: Optional[date], to_date: Optional[date]) -> None:
    rows = (
        db.query(StockLedger)
        .filter(
            StockLedger.entry_type.in_(_INWARD_TYPES),
            _stamp_in_range(StockLedger.created_at, from_date, to_date),
        )
        .all()
    )
    receipt_ids = {
        int(row.reference_id)
        for row in rows
        if row.reference_type == "stock_receipt" and row.reference_id
    }
    receipt_rate: dict[tuple[int, int], Decimal] = {}
    if receipt_ids:
        for line in db.query(StockReceiptLine).filter(StockReceiptLine.receipt_id.in_(receipt_ids)).all():
            receipt_rate[(int(line.receipt_id), int(line.catalog_product_id))] = _d(line.buying_price)
    product_ids = {int(row.catalog_product_id) for row in rows}
    buying = {
        int(pid): _d(price)
        for pid, price in db.query(CatalogProduct.id, CatalogProduct.buying_price)
        .filter(CatalogProduct.id.in_(product_ids))
        .all()
    } if product_ids else {}
    for row in rows:
        pid = int(row.catalog_product_id)
        delta = _d(row.quantity_delta)
        if delta == 0:
            continue
        explicit = None
        if row.reference_type == "stock_receipt" and row.reference_id:
            explicit = receipt_rate.get((int(row.reference_id), pid))
        rate = explicit if explicit is not None else buying.get(pid, Decimal("0"))
        bucket = _bucket(store, pid)
        bucket.in_qty += delta
        bucket.in_value += delta * rate


def _closing_qty(db: Session, product_ids: list[int], to_date: Optional[date]) -> dict[int, Decimal]:
    if not product_ids:
        return {}
    q = db.query(
        StockLedger.catalog_product_id,
        func.coalesce(func.sum(StockLedger.quantity_delta), 0),
    ).filter(StockLedger.catalog_product_id.in_(product_ids))
    if to_date is not None:
        _start, end = ist_range_bounds_utc(to_date, to_date)
        q = q.filter(StockLedger.created_at <= end)
    return {int(pid): _d(total) for pid, total in q.group_by(StockLedger.catalog_product_id).all()}


def split_summary_pages(items: list[dict], page_rows: int = 22) -> list[list[dict]]:
    size = max(int(page_rows or 28), 1)
    if not items:
        return [[]]
    return [items[i:i + size] for i in range(0, len(items), size)]
