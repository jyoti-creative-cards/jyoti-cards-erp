"""Phone books: sales, purchase, cash, and one item's history."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.accounts_payable import ApLedgerEntry
from app.models.accounts_receivable import ArLedgerEntry
from app.models.catalog_product import CatalogProduct
from app.models.customer import Customer
from app.models.customer_bill import CustomerBill, CustomerBillLine
from app.models.expense import Expense
from app.models.stock import StockBalance, StockReceipt, StockReceiptLine
from app.models.vendor import Vendor
from app.services.biz_date import ist_range_bounds_utc

_Q = Decimal("0.01")


def _d(value) -> Decimal:
    return Decimal(str(value or 0))


def _money(value: Decimal) -> str:
    return format(value.quantize(_Q), "f")


def _day(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat") and not isinstance(value, datetime):
        return value.isoformat()[:10]
    return str(value)[:10]


def _stamp_through(column, to_date: Optional[date]):
    if to_date is None:
        return True
    _start, end = ist_range_bounds_utc(to_date, to_date)
    return column <= end


def _dated(date_col, created_col, from_date: Optional[date], to_date: Optional[date]):
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


def _in_dates(column, from_date: Optional[date], to_date: Optional[date]):
    clause = True
    if from_date is not None:
        clause = and_(clause, column >= from_date)
    if to_date is not None:
        clause = and_(clause, column <= to_date)
    return clause


def _rate_ok(rate: Decimal, rate_min: Optional[Decimal], rate_max: Optional[Decimal]) -> bool:
    if rate_min is not None and rate < rate_min:
        return False
    if rate_max is not None and rate > rate_max:
        return False
    return True


def home(db: Session, from_date: Optional[date], to_date: Optional[date]) -> dict:
    sales = _sales_total(db, from_date, to_date)
    purchase = _purchase_total(db, from_date, to_date)
    receipt = _cash_total(db, ArLedgerEntry, "customer_id", from_date, to_date)
    payment = _cash_total(db, ApLedgerEntry, "vendor_id", from_date, to_date)
    expense_rows = _expense_heads(db, from_date, to_date)
    expense_total = sum((Decimal(row["amount"]) for row in expense_rows), Decimal("0"))
    cash = receipt - payment - expense_total
    return {
        "from_date": from_date.isoformat() if from_date else None,
        "to_date": to_date.isoformat() if to_date else None,
        "sales": _money(sales),
        "purchase": _money(purchase),
        "receipt": _money(receipt),
        "payment": _money(payment),
        "payable": _money(_outstanding(db, ApLedgerEntry, to_date)),
        "receivable": _money(_outstanding(db, ArLedgerEntry, to_date)),
        "cash": _money(cash),
        "expenses": _money(expense_total),
        "expense_heads": expense_rows,
    }


def _sales_total(db: Session, from_date, to_date) -> Decimal:
    bills = _live_bills(db, from_date, to_date)
    return sum((_d(b.grand_total) for b in bills), Decimal("0"))


def _live_bills(db: Session, from_date, to_date) -> list[CustomerBill]:
    return (
        db.query(CustomerBill)
        .filter(
            CustomerBill.deleted_at.is_(None),
            CustomerBill.cancelled_at.is_(None),
            _dated(CustomerBill.bill_date, CustomerBill.created_at, from_date, to_date),
        )
        .all()
    )


def _purchase_total(db: Session, from_date, to_date) -> Decimal:
    total = Decimal("0")
    for _line, _receipt, value in _purchase_lines(db, from_date, to_date, None, None):
        total += value
    return total


def _cash_total(db, model, _party_field, from_date, to_date) -> Decimal:
    rows = (
        db.query(model)
        .filter(
            model.deleted_at.is_(None),
            model.entry_type == "payment",
            _dated(model.value_date, model.created_at, from_date, to_date),
        )
        .all()
    )
    return sum((abs(_d(row.amount)) for row in rows), Decimal("0"))


def _outstanding(db, model, to_date) -> Decimal:
    q = db.query(model).filter(model.deleted_at.is_(None))
    if to_date is not None:
        q = q.filter(_dated(model.value_date, model.created_at, None, to_date))
    total = sum((_d(row.amount) for row in q.all()), Decimal("0"))
    return total if total > 0 else Decimal("0")


def _expense_heads(db: Session, from_date, to_date) -> list[dict]:
    rows = (
        db.query(Expense)
        .filter(Expense.is_cash.is_(True), _in_dates(Expense.expense_date, from_date, to_date))
        .all()
    )
    buckets: dict[str, Decimal] = {}
    for row in rows:
        name = (row.category or "misc").strip() or "misc"
        buckets[name] = buckets.get(name, Decimal("0")) + _d(row.amount)
    out = [{"name": name, "amount": _money(amount)} for name, amount in buckets.items()]
    out.sort(key=lambda row: Decimal(row["amount"]), reverse=True)
    return out


def drill(
    db: Session,
    metric: str,
    group: str,
    from_date: Optional[date],
    to_date: Optional[date],
    rate_min: Optional[Decimal],
    rate_max: Optional[Decimal],
) -> dict:
    metric = (metric or "sales").strip()
    group = (group or "party").strip()
    if metric == "sales":
        rows = _sales_groups(db, group, from_date, to_date, rate_min, rate_max)
    elif metric == "purchase":
        rows = _purchase_groups(db, group, from_date, to_date, rate_min, rate_max)
    elif metric == "receipt":
        rows = _payment_rows(db, ArLedgerEntry, Customer, "customer_id", from_date, to_date)
    elif metric == "payment":
        rows = _payment_rows(db, ApLedgerEntry, Vendor, "vendor_id", from_date, to_date)
    elif metric == "expenses":
        rows = [
            {"label": row["name"], "sub": "Head", "amount": row["amount"], "qty": None, "kind": "", "id": 0}
            for row in _expense_heads(db, from_date, to_date)
        ]
    elif metric == "payable":
        rows = _outstanding_parties(db, ApLedgerEntry, Vendor, "vendor_id", to_date)
    elif metric == "receivable":
        rows = _outstanding_parties(db, ArLedgerEntry, Customer, "customer_id", to_date)
    elif metric == "cash":
        home_row = home(db, from_date, to_date)
        rows = [
            {"label": "Receipt", "sub": "Money in", "amount": home_row["receipt"], "qty": None, "kind": "", "id": 0},
            {"label": "Payment", "sub": "Money out", "amount": home_row["payment"], "qty": None, "kind": "", "id": 0},
            {"label": "Expenses", "sub": "Cash expenses", "amount": home_row["expenses"], "qty": None, "kind": "", "id": 0},
        ]
    else:
        rows = []
    total = sum((Decimal(row["amount"]) for row in rows), Decimal("0"))
    return {
        "metric": metric,
        "group": group,
        "total": _money(total),
        "rows": rows,
    }


def _sales_groups(db, group, from_date, to_date, rate_min, rate_max) -> list[dict]:
    bills = {b.id: b for b in _live_bills(db, from_date, to_date)}
    if not bills:
        return []
    lines = db.query(CustomerBillLine).filter(CustomerBillLine.bill_id.in_(list(bills))).all()
    products = _products(db, {ln.catalog_product_id for ln in lines})
    customers = _names(db, Customer, {b.customer_id for b in bills.values()})
    buckets: dict[str, dict] = {}
    for ln in lines:
        bill = bills.get(ln.bill_id)
        if not bill or ln.status == "cancelled":
            continue
        qty = _d(ln.quantity_shipped)
        value = _d(ln.line_total)
        rate = (value / qty) if qty else _d(ln.unit_price)
        if not _rate_ok(rate, rate_min, rate_max):
            continue
        product = products.get(ln.catalog_product_id)
        if group == "item":
            key = str(ln.catalog_product_id)
            label = (product.our_product_id if product else None) or ln.our_product_id
            kind, row_id = "item", int(ln.catalog_product_id)
            sub = (product.category if product else "") or ""
        elif group == "category":
            label = ((product.category if product else "") or "No album").strip() or "No album"
            key, kind, row_id, sub = label, "", 0, "Album"
        else:
            label = customers.get(bill.customer_id) or f"Customer #{bill.customer_id}"
            key, kind, row_id, sub = str(bill.customer_id), "", int(bill.customer_id), "Party"
        bucket = buckets.setdefault(key, {"label": label, "sub": sub, "amount": Decimal("0"), "qty": Decimal("0"), "kind": kind, "id": row_id})
        bucket["amount"] += value
        bucket["qty"] += qty
    return _sorted_rows(buckets)


def _purchase_lines(db, from_date, to_date, rate_min, rate_max):
    start, end = ist_range_bounds_utc(from_date, to_date)
    q = (
        db.query(StockReceiptLine, StockReceipt)
        .join(StockReceipt, StockReceipt.id == StockReceiptLine.receipt_id)
        .filter(StockReceipt.deleted_at.is_(None))
    )
    if start is not None:
        q = q.filter(StockReceipt.received_at >= start)
    if end is not None:
        q = q.filter(StockReceipt.received_at <= end)
    out = []
    for line, receipt in q.all():
        qty = _d(line.quantity_received or line.quantity_billed)
        if qty == 0:
            continue
        rate = _d(line.buying_price)
        if not _rate_ok(rate, rate_min, rate_max):
            continue
        value = _d(line.billed_amount) if _d(line.billed_amount) else rate * qty
        out.append((line, receipt, value))
    return out


def _purchase_groups(db, group, from_date, to_date, rate_min, rate_max) -> list[dict]:
    lines = _purchase_lines(db, from_date, to_date, rate_min, rate_max)
    products = _products(db, {ln.catalog_product_id for ln, _r, _v in lines})
    vendors = _names(db, Vendor, {r.vendor_id for _ln, r, _v in lines})
    buckets: dict[str, dict] = {}
    for line, receipt, value in lines:
        qty = _d(line.quantity_received or line.quantity_billed)
        product = products.get(line.catalog_product_id)
        if group == "item":
            key = str(line.catalog_product_id)
            label = (product.our_product_id if product else None) or line.our_product_id
            kind, row_id, sub = "item", int(line.catalog_product_id), (product.category if product else "") or ""
        elif group == "category":
            label = ((product.category if product else "") or "No album").strip() or "No album"
            key, kind, row_id, sub = label, "", 0, "Album"
        else:
            label = vendors.get(receipt.vendor_id) or f"Vendor #{receipt.vendor_id}"
            key, kind, row_id, sub = str(receipt.vendor_id), "", int(receipt.vendor_id), "Party"
        bucket = buckets.setdefault(key, {"label": label, "sub": sub, "amount": Decimal("0"), "qty": Decimal("0"), "kind": kind, "id": row_id})
        bucket["amount"] += value
        bucket["qty"] += qty
    return _sorted_rows(buckets)


def _payment_rows(db, model, party_model, party_field, from_date, to_date) -> list[dict]:
    rows = (
        db.query(model)
        .filter(
            model.deleted_at.is_(None),
            model.entry_type == "payment",
            _dated(model.value_date, model.created_at, from_date, to_date),
        )
        .all()
    )
    names = _names(db, party_model, {getattr(row, party_field) for row in rows})
    buckets: dict[str, dict] = {}
    for row in rows:
        day = row.value_date.isoformat() if row.value_date else _day(row.created_at)
        party = names.get(getattr(row, party_field)) or "Party"
        key = f"{day}|{row.id}"
        buckets[key] = {
            "label": day,
            "sub": party,
            "amount": abs(_d(row.amount)),
            "qty": Decimal("0"),
            "kind": "",
            "id": row.id,
        }
    return _sorted_rows(buckets)


def _outstanding_parties(db, model, party_model, party_field, to_date) -> list[dict]:
    q = db.query(model).filter(model.deleted_at.is_(None))
    if to_date is not None:
        q = q.filter(_dated(model.value_date, model.created_at, None, to_date))
    totals: dict[int, Decimal] = {}
    for row in q.all():
        pid = int(getattr(row, party_field))
        totals[pid] = totals.get(pid, Decimal("0")) + _d(row.amount)
    names = _names(db, party_model, set(totals))
    buckets = {}
    for pid, amount in totals.items():
        if amount <= 0:
            continue
        buckets[str(pid)] = {
            "label": names.get(pid) or f"#{pid}",
            "sub": "Outstanding",
            "amount": amount,
            "qty": Decimal("0"),
            "kind": "",
            "id": pid,
        }
    return _sorted_rows(buckets)


def _sorted_rows(buckets: dict) -> list[dict]:
    rows = []
    for bucket in buckets.values():
        rows.append({
            "label": bucket["label"],
            "sub": bucket["sub"],
            "amount": _money(bucket["amount"]),
            "qty": _money(bucket["qty"]) if bucket["qty"] else None,
            "kind": bucket["kind"],
            "id": bucket["id"],
        })
    rows.sort(key=lambda row: Decimal(row["amount"]), reverse=True)
    return rows


def _products(db, ids) -> dict[int, CatalogProduct]:
    ids = {int(i) for i in ids if i}
    if not ids:
        return {}
    return {p.id: p for p in db.query(CatalogProduct).filter(CatalogProduct.id.in_(ids)).all()}


def _names(db, model, ids) -> dict[int, str]:
    ids = {int(i) for i in ids if i}
    if not ids:
        return {}
    return {row.id: row.business_name for row in db.query(model).filter(model.id.in_(ids)).all()}


def search_items(db: Session, query: str) -> list[dict]:
    text = (query or "").strip()
    if not text:
        return []
    products = (
        db.query(CatalogProduct)
        .filter(
            CatalogProduct.deleted_at.is_(None),
            CatalogProduct.our_product_id.ilike(f"%{text}%"),
        )
        .order_by(CatalogProduct.our_product_id.asc())
        .limit(30)
        .all()
    )
    stock = {
        b.catalog_product_id: int(b.quantity_on_hand or 0)
        for b in db.query(StockBalance).filter(StockBalance.catalog_product_id.in_([p.id for p in products] or [0])).all()
    } if products else {}
    return [
        {
            "id": p.id,
            "name": p.our_product_id,
            "vendor_item": p.vendor_product_id or "",
            "category": p.category or "",
            "year_group": p.year_group or "",
            "stock": stock.get(p.id, 0),
        }
        for p in products
    ]


def item_summary(db: Session, product_id: int, from_date, to_date) -> dict:
    product = db.get(CatalogProduct, product_id)
    if not product or product.deleted_at:
        return {}
    stock = db.query(StockBalance).filter(StockBalance.catalog_product_id == product_id).first()
    sales = _item_sales(db, product_id, from_date, to_date)
    purchase = _item_purchases(db, product_id, from_date, to_date)
    return {
        "id": product.id,
        "name": product.our_product_id,
        "vendor_item": product.vendor_product_id or "",
        "category": product.category or "",
        "stock": int(stock.quantity_on_hand or 0) if stock else 0,
        "sales": sales,
        "purchase": purchase,
    }


def _item_sales(db, product_id, from_date, to_date) -> dict:
    bills = {b.id: b for b in _live_bills(db, from_date, to_date)}
    lines = []
    if bills:
        lines = (
            db.query(CustomerBillLine)
            .filter(
                CustomerBillLine.catalog_product_id == product_id,
                CustomerBillLine.bill_id.in_(list(bills)),
                CustomerBillLine.status != "cancelled",
            )
            .all()
        )
    qty = sum((_d(ln.quantity_shipped) for ln in lines), Decimal("0"))
    value = sum((_d(ln.line_total) for ln in lines), Decimal("0"))
    last = _latest_sale(lines, bills)
    return {
        "value": _money(value),
        "qty": _money(qty),
        "invoices": len({ln.bill_id for ln in lines}),
        "last_date": last[0],
        "last_rate": last[1],
    }


def _latest_sale(lines, bills):
    best = None
    for ln in lines:
        bill = bills.get(ln.bill_id)
        day = (bill.bill_date.isoformat() if bill and bill.bill_date else "") or ""
        qty = _d(ln.quantity_shipped)
        rate = ( _d(ln.line_total) / qty) if qty else _d(ln.unit_price)
        stamp = (day, ln.id)
        if best is None or stamp > best[0]:
            best = (stamp, _money(rate), day)
    if not best:
        return "", "0.00"
    return best[2], best[1]


def _item_purchases(db, product_id, from_date, to_date) -> dict:
    rows = [
        (ln, receipt, value)
        for ln, receipt, value in _purchase_lines(db, from_date, to_date, None, None)
        if ln.catalog_product_id == product_id
    ]
    qty = sum((_d(ln.quantity_received or ln.quantity_billed) for ln, _r, _v in rows), Decimal("0"))
    value = sum((v for _ln, _r, v in rows), Decimal("0"))
    last_day, last_rate = "", Decimal("0")
    for ln, receipt, _value in rows:
        day = _day(receipt.received_at)
        if day >= last_day:
            last_day = day
            last_rate = _d(ln.buying_price)
    return {
        "value": _money(value),
        "qty": _money(qty),
        "receipts": len({r.id for _ln, r, _v in rows}),
        "last_date": last_day,
        "last_rate": _money(last_rate),
    }


def item_customers(db, product_id, from_date, to_date) -> list[dict]:
    bills = {b.id: b for b in _live_bills(db, from_date, to_date)}
    if not bills:
        return []
    lines = (
        db.query(CustomerBillLine)
        .filter(
            CustomerBillLine.catalog_product_id == product_id,
            CustomerBillLine.bill_id.in_(list(bills)),
            CustomerBillLine.status != "cancelled",
        )
        .all()
    )
    names = _names(db, Customer, {bills[ln.bill_id].customer_id for ln in lines if ln.bill_id in bills})
    rows = []
    for ln in lines:
        bill = bills[ln.bill_id]
        qty = _d(ln.quantity_shipped)
        value = _d(ln.line_total)
        rate = (value / qty) if qty else _d(ln.unit_price)
        rows.append({
            "bill_id": bill.id,
            "bill_number": bill.bill_number,
            "date": bill.bill_date.isoformat() if bill.bill_date else _day(bill.created_at),
            "party": names.get(bill.customer_id) or f"Customer #{bill.customer_id}",
            "qty": _money(qty),
            "rate": _money(rate),
            "amount": _money(value),
        })
    rows.sort(key=lambda row: row["date"], reverse=True)
    return rows


def item_suppliers(db, product_id, from_date, to_date) -> list[dict]:
    rows = []
    picked = [
        (ln, receipt, value)
        for ln, receipt, value in _purchase_lines(db, from_date, to_date, None, None)
        if ln.catalog_product_id == product_id
    ]
    names = _names(db, Vendor, {r.vendor_id for _ln, r, _v in picked})
    for ln, receipt, value in picked:
        qty = _d(ln.quantity_received or ln.quantity_billed)
        rows.append({
            "receipt_id": receipt.id,
            "receipt_number": receipt.bill_number or receipt.order_receipt_number or f"R-{receipt.id}",
            "date": _day(receipt.received_at),
            "party": names.get(receipt.vendor_id) or f"Vendor #{receipt.vendor_id}",
            "qty": _money(qty),
            "rate": _money(_d(ln.buying_price)),
            "amount": _money(value),
        })
    rows.sort(key=lambda row: row["date"], reverse=True)
    return rows


def customer_bill(db, bill_id: int) -> dict:
    bill = db.get(CustomerBill, bill_id)
    if not bill or bill.deleted_at:
        return {}
    customer = db.get(Customer, bill.customer_id)
    lines = db.query(CustomerBillLine).filter(CustomerBillLine.bill_id == bill.id).order_by(CustomerBillLine.id.asc()).all()
    return {
        "id": bill.id,
        "number": bill.bill_number,
        "date": bill.bill_date.isoformat() if bill.bill_date else _day(bill.created_at),
        "party": customer.business_name if customer else "",
        "cancelled": bill.cancelled_at is not None,
        "total": _money(_d(bill.grand_total)),
        "lines": [
            {
                "product_id": ln.catalog_product_id,
                "name": ln.our_product_id,
                "qty": _money(_d(ln.quantity_shipped)),
                "rate": _money((_d(ln.line_total) / _d(ln.quantity_shipped)) if _d(ln.quantity_shipped) else _d(ln.unit_price)),
                "amount": _money(_d(ln.line_total)),
            }
            for ln in lines
        ],
    }


def supplier_receipt(db, receipt_id: int) -> dict:
    receipt = db.get(StockReceipt, receipt_id)
    if not receipt or receipt.deleted_at:
        return {}
    vendor = db.get(Vendor, receipt.vendor_id)
    lines = db.query(StockReceiptLine).filter(StockReceiptLine.receipt_id == receipt.id).order_by(StockReceiptLine.id.asc()).all()
    total = Decimal("0")
    out_lines = []
    for ln in lines:
        qty = _d(ln.quantity_received or ln.quantity_billed)
        value = _d(ln.billed_amount) if _d(ln.billed_amount) else _d(ln.buying_price) * qty
        total += value
        out_lines.append({
            "product_id": ln.catalog_product_id,
            "name": ln.our_product_id,
            "qty": _money(qty),
            "rate": _money(_d(ln.buying_price)),
            "amount": _money(value),
        })
    return {
        "id": receipt.id,
        "number": receipt.bill_number or receipt.order_receipt_number or f"R-{receipt.id}",
        "date": _day(receipt.received_at),
        "party": vendor.business_name if vendor else "",
        "total": _money(total),
        "lines": out_lines,
    }
