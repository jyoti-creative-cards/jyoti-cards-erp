"""Admin analytics numbers.

Stock uses a start date through today. Closing quantity is what is in the
godown today. Sale percentage is money already collected, not what is still due.
The party list is every active party. Switched-off parties stay out.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.accounts_receivable import ArLedgerEntry
from app.models.catalog_product import CatalogProduct
from app.models.city import City
from app.models.customer import Customer
from app.models.customer_bill import CustomerBill, CustomerBillLine
from app.models.stock import StockBalance, StockLedger
from app.models.our_catalog import OurCatalog, OurCatalogIssue
from app.models.vendor import Vendor
from app.services.biz_date import ist_range_bounds_utc, today_ist, to_ist
from app.services.our_catalogs.core import _real_issue, catalog_name_for_bill_sku
from app.services.reports.stock_group_summary import _INWARD_TYPES

DEFAULT_ALERT = Decimal("20")


def collected_percent(sale: Decimal, received: Decimal) -> Optional[Decimal]:
    """Share of the sale that has already been collected."""
    if sale <= 0:
        return None
    return _q2(received / sale * Decimal("100"))


def under_threshold(inward: Decimal, closing: Decimal, percent: Decimal) -> bool:
    """True when today's stock is below percent of everything received so far."""
    if inward <= 0 or percent <= 0:
        return False
    return closing < inward * percent / Decimal("100")


def filter_choices(db: Session) -> dict:
    products = (
        db.query(CatalogProduct.category, CatalogProduct.second_category, CatalogProduct.category_3, CatalogProduct.year_group)
        .filter(CatalogProduct.deleted_at.is_(None))
        .all()
    )
    cats: set[str] = set()
    years: set[str] = set()
    for category, second, third, year in products:
        for value in (category, second, third):
            text = (value or "").strip()
            if text:
                cats.add(text)
        year_text = (year or "").strip()
        if year_text:
            years.add(year_text)
    return {
        "categories": sorted(cats, key=str.lower),
        "year_groups": sorted(years, key=str.lower),
        "today": today_ist().isoformat(),
    }


def stock_report(
    db: Session,
    *,
    from_date: Optional[date] = None,
    categories: Optional[list[str]] = None,
    year_group: str = "",
) -> dict:
    end = today_ist()
    start, finish = ist_range_bounds_utc(from_date, end)
    products = _stock_products(db, categories or [], year_group)
    ids = [p.id for p in products]
    inward = _inward(db, ids, start, finish)
    outward = _outward(db, ids, from_date, end)
    on_hand = _on_hand(db, ids)
    last = _last_inward(db, ids, start, finish)
    vendors = _vendors(db, {p.vendor_id for p in products if p.vendor_id})
    items = []
    for product in products:
        inn = inward.get(product.id, Decimal("0"))
        out = outward["qty"].get(product.id, Decimal("0"))
        bills = outward["bills"].get(product.id, 0)
        close = on_hand.get(product.id, Decimal("0"))
        if inn == 0 and out == 0 and bills == 0 and close == 0:
            continue
        rate = _d(product.buying_price)
        ratio = _q2(close / inn * Decimal("100")) if inn > 0 else None
        vendor = vendors.get(product.vendor_id)
        items.append({
            "id": product.id,
            "item": product.our_product_id,
            "alias": ((vendor.alias if vendor and vendor.alias else "") or product.vendor_product_id or ""),
            "party": vendor.business_name if vendor else "",
            "category_1": product.category or "",
            "category_2": product.second_category or "",
            "category_3": product.category_3 or "",
            "bills": bills,
            "inward": _num(inn),
            "outward": _num(out),
            "closing_stock": _num(close),
            "closing_value": _money(close * rate),
            "percent": _money(ratio) if ratio is not None else "",
            "last_received": last.get(product.id).isoformat() if product.id in last else "",
        })
    items.sort(key=lambda row: (row["party"].lower(), row["item"].lower()))
    return {
        "from_date": from_date.isoformat() if from_date else None,
        "to_date": end.isoformat(),
        "items": items,
    }


def sale_balance_report(db: Session, *, from_date: Optional[date] = None, to_date: Optional[date] = None) -> dict:
    end = to_date or today_ist()
    sales = _customer_sales(db, from_date, end)
    pays = _customer_payments(db, from_date, end)
    ids = set(sales) | set(pays)
    due = _outstanding(db, ids)
    people = _customers(db, ids)
    items = []
    for cid, person in people.items():
        sale = sales.get(cid, Decimal("0"))
        received, receipts, last_pay = pays.get(cid, (Decimal("0"), 0, None))
        if sale == 0 and receipts == 0:
            continue
        ratio = collected_percent(sale, received)
        items.append({
            "id": cid,
            "party": person.business_name,
            "city": person.city_name,
            "sale": _money(sale),
            "balance": _money(due.get(cid, Decimal("0"))),
            "collected_percent": _money(ratio) if ratio is not None else "",
            "last_payment": last_pay.isoformat() if last_pay else "",
            "receipts": receipts,
        })
    items.sort(key=lambda row: row["party"].lower())
    return {
        "from_date": from_date.isoformat() if from_date else None,
        "to_date": end.isoformat(),
        "items": items,
    }


def party_activity_report(db: Session, *, from_date: Optional[date] = None, to_date: Optional[date] = None) -> dict:
    """Every party we still do business with. Switched-off parties stay out."""
    end = to_date or today_ist()
    people = _active_customers(db)
    ids = set(people)
    sales = _customer_sales(db, from_date, end, ids)
    albums = _albums_sent(db, from_date, end, ids)
    last_pay = _last_payment_ever(db, ids)
    due = _outstanding(db, ids)
    items = []
    for cid, person in people.items():
        sale, bills = sales.get(cid, (Decimal("0"), 0))
        paid_on = last_pay.get(cid)
        items.append({
            "id": cid,
            "party": person.business_name,
            "city": person.city_name,
            "bills": bills,
            "sale": _money(sale),
            "albums": ", ".join(sorted(albums.get(cid, set()), key=str.lower)),
            "balance": _money(due.get(cid, Decimal("0"))),
            "last_payment": paid_on.isoformat() if paid_on else "",
        })
    items.sort(key=lambda row: row["party"].lower())
    return {
        "from_date": from_date.isoformat() if from_date else None,
        "to_date": end.isoformat(),
        "items": items,
    }


def threshold_list(db: Session, *, q: str = "") -> dict:
    needle = (q or "").strip().lower()
    products = (
        db.query(CatalogProduct)
        .filter(CatalogProduct.deleted_at.is_(None), CatalogProduct.is_active.is_(True))
        .all()
    )
    ids = [p.id for p in products]
    inward = _inward(db, ids, None, None)
    on_hand = _on_hand(db, ids)
    vendors = _vendors(db, {p.vendor_id for p in products if p.vendor_id})
    items = []
    for product in products:
        inn = inward.get(product.id, Decimal("0"))
        close = on_hand.get(product.id, Decimal("0"))
        percent = _alert_percent(product)
        vendor = vendors.get(product.vendor_id)
        alias = ((vendor.alias if vendor and vendor.alias else "") or product.vendor_product_id or "")
        party = vendor.business_name if vendor else ""
        blob = " ".join([product.our_product_id, product.vendor_product_id or "", alias, party]).lower()
        if needle and needle not in blob:
            continue
        low = under_threshold(inn, close, percent)
        if needle or low:
            items.append({
                "id": product.id,
                "item": product.our_product_id,
                "alias": alias,
                "party": party,
                "inward": _num(inn),
                "closing_stock": _num(close),
                "percent": _money(percent),
                "below": low,
            })
    items.sort(key=lambda row: (not row["below"], row["item"].lower()))
    return {"default_percent": _money(DEFAULT_ALERT), "items": items}


def threshold_detail(db: Session, product_id: int) -> Optional[dict]:
    product = db.query(CatalogProduct).filter(CatalogProduct.id == product_id, CatalogProduct.deleted_at.is_(None)).first()
    if product is None:
        return None
    inward = _inward(db, [product.id], None, None).get(product.id, Decimal("0"))
    close = _on_hand(db, [product.id]).get(product.id, Decimal("0"))
    percent = _alert_percent(product)
    vendor = _vendors(db, {product.vendor_id} if product.vendor_id else set()).get(product.vendor_id)
    rows = (
        db.query(CustomerBill, CustomerBillLine, Customer, City.name)
        .join(CustomerBillLine, CustomerBillLine.bill_id == CustomerBill.id)
        .join(Customer, Customer.id == CustomerBill.customer_id)
        .outerjoin(City, City.id == Customer.city_id)
        .filter(
            CustomerBillLine.catalog_product_id == product.id,
            CustomerBill.deleted_at.is_(None),
            CustomerBill.cancelled_at.is_(None),
            CustomerBillLine.status != "cancelled",
            CustomerBillLine.quantity_shipped > 0,
        )
        .order_by(CustomerBill.bill_date.desc(), CustomerBill.id.desc())
        .all()
    )
    bills = []
    for bill, line, customer, city in rows:
        bills.append({
            "bill_id": bill.id,
            "bill_number": bill.bill_number,
            "bill_date": bill.bill_date.isoformat() if bill.bill_date else "",
            "party": customer.business_name,
            "city": city or "",
            "quantity": _num(_d(line.quantity_shipped)),
            "rate": _money(_d(line.unit_price)),
            "amount": _money(_d(line.line_total)),
        })
    return {
        "id": product.id,
        "item": product.our_product_id,
        "alias": ((vendor.alias if vendor and vendor.alias else "") or product.vendor_product_id or ""),
        "party": vendor.business_name if vendor else "",
        "category_1": product.category or "",
        "category_2": product.second_category or "",
        "category_3": product.category_3 or "",
        "inward": _num(inward),
        "closing_stock": _num(close),
        "percent": _money(percent),
        "below": under_threshold(inward, close, percent),
        "bills": bills,
    }


def set_threshold(db: Session, product_id: int, percent: Decimal) -> Optional[dict]:
    product = db.query(CatalogProduct).filter(CatalogProduct.id == product_id, CatalogProduct.deleted_at.is_(None)).first()
    if product is None:
        return None
    product.stock_alert_percent = _q2(percent)
    db.flush()
    return threshold_detail(db, product_id)


def set_default_threshold(db: Session, percent: Decimal = DEFAULT_ALERT) -> int:
    value = _q2(percent)
    count = (
        db.query(CatalogProduct)
        .filter(CatalogProduct.deleted_at.is_(None))
        .update({CatalogProduct.stock_alert_percent: value}, synchronize_session=False)
    )
    db.flush()
    db.expire_all()
    return int(count or 0)


def _stock_products(db: Session, categories: list[str], year_group: str) -> list[CatalogProduct]:
    q = db.query(CatalogProduct).filter(CatalogProduct.deleted_at.is_(None), CatalogProduct.is_active.is_(True))
    year = (year_group or "").strip()
    if year:
        q = q.filter(CatalogProduct.year_group == year)
    wanted = {c.strip() for c in categories if (c or "").strip()}
    if wanted:
        q = q.filter(or_(
            CatalogProduct.category.in_(wanted),
            CatalogProduct.second_category.in_(wanted),
            CatalogProduct.category_3.in_(wanted),
        ))
    return q.all()


def _inward(db: Session, ids: list[int], start: Optional[datetime], finish: Optional[datetime]) -> dict[int, Decimal]:
    if not ids:
        return {}
    q = (
        db.query(StockLedger.catalog_product_id, func.coalesce(func.sum(StockLedger.quantity_delta), 0))
        .filter(StockLedger.catalog_product_id.in_(ids), StockLedger.entry_type.in_(_INWARD_TYPES))
    )
    if start is not None:
        q = q.filter(StockLedger.created_at >= start)
    if finish is not None:
        q = q.filter(StockLedger.created_at <= finish)
    return {int(pid): _d(total) for pid, total in q.group_by(StockLedger.catalog_product_id).all()}


def _last_inward(db: Session, ids: list[int], start: Optional[datetime], finish: Optional[datetime]) -> dict[int, date]:
    if not ids:
        return {}
    q = (
        db.query(StockLedger.catalog_product_id, func.max(StockLedger.created_at))
        .filter(
            StockLedger.catalog_product_id.in_(ids),
            StockLedger.entry_type.in_(_INWARD_TYPES),
            StockLedger.quantity_delta > 0,
        )
    )
    if start is not None:
        q = q.filter(StockLedger.created_at >= start)
    if finish is not None:
        q = q.filter(StockLedger.created_at <= finish)
    out = {}
    for pid, stamp in q.group_by(StockLedger.catalog_product_id).all():
        if stamp is not None:
            out[int(pid)] = to_ist(stamp).date()
    return out


def _outward(db: Session, ids: list[int], from_date: Optional[date], to_date: Optional[date]) -> dict:
    qty: dict[int, Decimal] = {}
    bills: dict[int, set[int]] = {}
    if not ids:
        return {"qty": qty, "bills": {}}
    q = (
        db.query(CustomerBillLine.catalog_product_id, CustomerBill.id, CustomerBillLine.quantity_shipped)
        .join(CustomerBill, CustomerBill.id == CustomerBillLine.bill_id)
        .filter(
            CustomerBillLine.catalog_product_id.in_(ids),
            CustomerBill.deleted_at.is_(None),
            CustomerBill.cancelled_at.is_(None),
            CustomerBillLine.status != "cancelled",
            CustomerBillLine.quantity_shipped > 0,
        )
    )
    if from_date is not None:
        q = q.filter(CustomerBill.bill_date >= from_date)
    if to_date is not None:
        q = q.filter(CustomerBill.bill_date <= to_date)
    for pid, bill_id, shipped in q.all():
        qty[int(pid)] = qty.get(int(pid), Decimal("0")) + _d(shipped)
        bills.setdefault(int(pid), set()).add(int(bill_id))
    return {"qty": qty, "bills": {pid: len(seen) for pid, seen in bills.items()}}


def _on_hand(db: Session, ids: list[int]) -> dict[int, Decimal]:
    if not ids:
        return {}
    rows = db.query(StockBalance.catalog_product_id, StockBalance.quantity_on_hand).filter(
        StockBalance.catalog_product_id.in_(ids)
    ).all()
    return {int(pid): _d(qty) for pid, qty in rows}


def _vendors(db: Session, ids: set[Optional[int]]) -> dict[int, Vendor]:
    clean = {int(i) for i in ids if i}
    if not clean:
        return {}
    return {v.id: v for v in db.query(Vendor).filter(Vendor.id.in_(clean)).all()}


class _Person:
    def __init__(self, customer: Customer, city_name: str):
        self.business_name = customer.business_name
        self.is_active = bool(customer.is_active)
        self.city_name = city_name or ""


def _customers(db: Session, ids: set[int]) -> dict[int, _Person]:
    if not ids:
        return {}
    rows = (
        db.query(Customer, City.name)
        .outerjoin(City, City.id == Customer.city_id)
        .filter(Customer.id.in_(ids), Customer.deleted_at.is_(None))
        .all()
    )
    return {customer.id: _Person(customer, city or "") for customer, city in rows}


def _active_customers(db: Session) -> dict[int, _Person]:
    rows = (
        db.query(Customer, City.name)
        .outerjoin(City, City.id == Customer.city_id)
        .filter(Customer.deleted_at.is_(None), Customer.is_active.is_(True))
        .all()
    )
    return {customer.id: _Person(customer, city or "") for customer, city in rows}


def _customer_sales(db: Session, from_date: Optional[date], to_date: Optional[date], only: Optional[set[int]] = None) -> dict:
    """Sale total, and bill count when only is set (the party list needs both)."""
    q = db.query(CustomerBill.customer_id, func.count(CustomerBill.id), func.coalesce(func.sum(CustomerBill.grand_total), 0)).filter(
        CustomerBill.deleted_at.is_(None),
        CustomerBill.cancelled_at.is_(None),
    )
    if from_date is not None:
        q = q.filter(CustomerBill.bill_date >= from_date)
    if to_date is not None:
        q = q.filter(CustomerBill.bill_date <= to_date)
    if only is not None:
        if not only:
            return {}
        q = q.filter(CustomerBill.customer_id.in_(only))
    out = {}
    for cid, bills, total in q.group_by(CustomerBill.customer_id).all():
        if only is None:
            out[int(cid)] = _d(total)
        else:
            out[int(cid)] = (_d(total), int(bills or 0))
    return out


def _customer_payments(db: Session, from_date: Optional[date], to_date: Optional[date]) -> dict[int, tuple[Decimal, int, Optional[date]]]:
    q = db.query(ArLedgerEntry).filter(
        ArLedgerEntry.deleted_at.is_(None),
        ArLedgerEntry.entry_type == "payment",
        ArLedgerEntry.amount < 0,
    )
    rows = q.all()
    grouped: dict[int, list] = {}
    for row in rows:
        when = row.value_date or (to_ist(row.created_at).date() if row.created_at else None)
        if from_date and (when is None or when < from_date):
            continue
        if to_date and (when is None or when > to_date):
            continue
        grouped.setdefault(int(row.customer_id), []).append((when, -_d(row.amount)))
    out = {}
    for cid, pays in grouped.items():
        received = sum((amount for _when, amount in pays), Decimal("0"))
        dates = [when for when, _amount in pays if when]
        out[cid] = (_q2(received), len(pays), max(dates) if dates else None)
    return out


def _last_payment_ever(db: Session, ids: set[int]) -> dict[int, date]:
    if not ids:
        return {}
    rows = db.query(ArLedgerEntry).filter(
        ArLedgerEntry.customer_id.in_(ids),
        ArLedgerEntry.deleted_at.is_(None),
        ArLedgerEntry.entry_type == "payment",
        ArLedgerEntry.amount < 0,
    ).all()
    out: dict[int, date] = {}
    for row in rows:
        when = row.value_date or (to_ist(row.created_at).date() if row.created_at else None)
        if when and (row.customer_id not in out or when > out[row.customer_id]):
            out[int(row.customer_id)] = when
    return out


def _outstanding(db: Session, ids: set[int]) -> dict[int, Decimal]:
    if not ids:
        return {}
    rows = (
        db.query(ArLedgerEntry.customer_id, func.coalesce(func.sum(ArLedgerEntry.amount), 0))
        .filter(ArLedgerEntry.customer_id.in_(ids), ArLedgerEntry.deleted_at.is_(None))
        .group_by(ArLedgerEntry.customer_id)
        .all()
    )
    return {int(cid): _q2(_d(total)) for cid, total in rows}


def _albums_sent(db: Session, from_date: Optional[date], to_date: Optional[date], ids: set[int]) -> dict[int, set[str]]:
    if not ids:
        return {}
    q = (
        db.query(CustomerBill.customer_id, CustomerBillLine.our_product_id)
        .join(CustomerBillLine, CustomerBillLine.bill_id == CustomerBill.id)
        .filter(
            CustomerBill.customer_id.in_(ids),
            CustomerBill.deleted_at.is_(None),
            CustomerBill.cancelled_at.is_(None),
            CustomerBillLine.status != "cancelled",
            CustomerBillLine.quantity_shipped > 0,
            or_(
                CustomerBillLine.our_product_id.ilike("%ALBUM%"),
                CustomerBillLine.our_product_id.ilike("%BOX%"),
            ),
        )
    )
    if from_date is not None:
        q = q.filter(CustomerBill.bill_date >= from_date)
    if to_date is not None:
        q = q.filter(CustomerBill.bill_date <= to_date)
    out: dict[int, set[str]] = {}
    for cid, sku in q.all():
        name = catalog_name_for_bill_sku(sku or "")
        if name:
            out.setdefault(int(cid), set()).add(name)
    issued = (
        db.query(OurCatalogIssue.customer_id, OurCatalog.name, OurCatalogIssue.note)
        .join(OurCatalog, OurCatalog.id == OurCatalogIssue.catalog_id)
        .filter(OurCatalogIssue.customer_id.in_(ids))
    )
    if from_date is not None:
        issued = issued.filter(OurCatalogIssue.issued_on >= from_date)
    if to_date is not None:
        issued = issued.filter(OurCatalogIssue.issued_on <= to_date)
    for cid, name, note in issued.all():
        if name and _real_issue(note):
            out.setdefault(int(cid), set()).add(name)
    return out


def _alert_percent(product: CatalogProduct) -> Decimal:
    if product.stock_alert_percent is None:
        return DEFAULT_ALERT
    return _d(product.stock_alert_percent)


def _d(value) -> Decimal:
    return Decimal(str(value or 0))


def _q2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def _money(value: Optional[Decimal]) -> str:
    if value is None:
        return ""
    return f"{_q2(value):.2f}"


def _num(value: Decimal) -> str:
    whole = value == value.to_integral()
    return str(int(value)) if whole else f"{_q2(value):.2f}"
