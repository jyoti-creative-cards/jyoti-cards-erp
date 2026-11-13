"""Physical catalogues made from stock and sent to parties."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.catalog_product import CatalogProduct
from app.models.customer import Customer
from app.models.our_catalog import OurCatalog, OurCatalogAssignment, OurCatalogIssue, OurCatalogLine
from app.models.stock_journal import StockJournal, StockJournalLine
from app.services.biz_date import today_ist


def _money(value) -> str:
    return format(Decimal(str(value or 0)).quantize(Decimal("0.01")), "f")


def issued_copies(db: Session, catalog_id: int) -> int:
    total = (
        db.query(func.coalesce(func.sum(OurCatalogIssue.copies), 0))
        .filter(OurCatalogIssue.catalog_id == catalog_id)
        .scalar()
    )
    return int(total or 0)


def received_copies(db: Session, catalog_id: int, customer_id: int) -> int:
    total = (
        db.query(func.coalesce(func.sum(OurCatalogIssue.copies), 0))
        .filter(OurCatalogIssue.catalog_id == catalog_id, OurCatalogIssue.customer_id == customer_id)
        .scalar()
    )
    return int(total or 0)


def list_catalogs(db: Session) -> list[dict]:
    rows = db.query(OurCatalog).order_by(OurCatalog.name.asc()).all()
    out = []
    for row in rows:
        sent = issued_copies(db, row.id)
        assigned = (
            db.query(func.count(OurCatalogAssignment.id))
            .filter(OurCatalogAssignment.catalog_id == row.id)
            .scalar()
        )
        out.append({
            "id": row.id,
            "name": row.name,
            "copies_made": row.copies_made,
            "copies_sent": sent,
            "copies_left": row.copies_made - sent,
            "assigned": int(assigned or 0),
            "expense_id": row.expense_id,
        })
    return out


def catalog_detail(db: Session, catalog_id: int) -> dict:
    row = db.get(OurCatalog, catalog_id)
    if not row:
        raise HTTPException(404, "catalog not found")
    lines = (
        db.query(OurCatalogLine, CatalogProduct.our_product_id)
        .join(CatalogProduct, CatalogProduct.id == OurCatalogLine.catalog_product_id)
        .filter(OurCatalogLine.catalog_id == row.id)
        .order_by(CatalogProduct.our_product_id.asc())
        .all()
    )
    assignments = (
        db.query(OurCatalogAssignment, Customer)
        .join(Customer, Customer.id == OurCatalogAssignment.customer_id)
        .filter(OurCatalogAssignment.catalog_id == row.id)
        .order_by(Customer.business_name.asc())
        .all()
    )
    from app.models.city import City
    from app.models.customer_bill import CustomerBill

    issues = (
        db.query(OurCatalogIssue, Customer, City.name, CustomerBill.bill_number)
        .join(Customer, Customer.id == OurCatalogIssue.customer_id)
        .outerjoin(City, City.id == Customer.city_id)
        .outerjoin(CustomerBill, CustomerBill.id == OurCatalogIssue.bill_id)
        .filter(OurCatalogIssue.catalog_id == row.id)
        .order_by(OurCatalogIssue.issued_on.desc(), OurCatalogIssue.id.desc())
        .all()
    )
    sent = issued_copies(db, row.id)
    received_by = {}
    for issue, _customer, _city, _bill_number in issues:
        received_by[issue.customer_id] = received_by.get(issue.customer_id, 0) + int(issue.copies)
    return {
        "id": row.id,
        "name": row.name,
        "copies_made": row.copies_made,
        "copies_sent": sent,
        "copies_left": row.copies_made - sent,
        "expense_id": row.expense_id,
        "lines": [{"catalog_product_id": ln.catalog_product_id, "our_product_id": sku, "quantity": ln.quantity} for ln, sku in lines],
        "assignments": [
            {
                "customer_id": cust.id,
                "business_name": cust.business_name,
                "party_number": cust.party_number,
                "received": received_by.get(cust.id, 0),
            }
            for _assign, cust in assignments
        ],
        "issues": [
            {
                "id": issue.id,
                "customer_id": issue.customer_id,
                "business_name": customer.business_name,
                "party_number": customer.party_number,
                "city_name": city_name or "",
                "copies": issue.copies,
                "price": _money(issue.price),
                "bill_id": issue.bill_id,
                "bill_number": bill_number or "",
                "issued_on": issue.issued_on.isoformat(),
                "note": issue.note or "",
            }
            for issue, customer, city_name, bill_number in issues
        ],
    }


def _real_issue(note: str | None) -> bool:
    """Album membership on a product bill is not a catalogue the party was given."""
    return not (note or "").strip().lower().startswith("from bill")


def real_received_copies(db: Session, catalog_id: int, customer_id: int | None = None) -> int:
    query = db.query(OurCatalogIssue).filter(OurCatalogIssue.catalog_id == catalog_id)
    if customer_id is not None:
        query = query.filter(OurCatalogIssue.customer_id == customer_id)
    return sum(int(row.copies or 0) for row in query.all() if _real_issue(row.note))


def catalogue_units_billed(db: Session, customer_id: int | None = None) -> dict[str, int]:
    """Copies of the catalogue item on a bill. A card from that album is not a copy."""
    from app.models.customer_bill import CustomerBill, CustomerBillLine

    query = (
        db.query(CustomerBillLine.our_product_id, func.sum(CustomerBillLine.quantity_shipped))
        .join(CustomerBill, CustomerBill.id == CustomerBillLine.bill_id)
        .filter(
            CustomerBill.deleted_at.is_(None),
            CustomerBill.cancelled_at.is_(None),
            CustomerBillLine.status == "billed",
            CustomerBillLine.quantity_shipped > 0,
        )
        .group_by(CustomerBillLine.our_product_id)
    )
    if customer_id is not None:
        query = query.filter(CustomerBill.customer_id == customer_id)
    totals: dict[str, int] = {}
    for sku, qty in query.all():
        name = catalog_name_for_bill_sku(sku or "")
        if not name:
            continue
        totals[name] = totals.get(name, 0) + int(qty or 0)
    return totals


def for_customer(db: Session, customer_id: int) -> list[dict]:
    """Catalogues this party was given, counted from the catalogue item on a bill."""
    assigned_ids = [
        row.catalog_id
        for row in db.query(OurCatalogAssignment).filter(OurCatalogAssignment.customer_id == customer_id).all()
    ]
    catalogs = db.query(OurCatalog).all()
    by_id = {int(row.id): row for row in catalogs}
    by_name = {row.name: row for row in catalogs}
    got_by_id: dict[int, int] = {}
    for issue in db.query(OurCatalogIssue).filter(OurCatalogIssue.customer_id == customer_id).all():
        if not _real_issue(issue.note):
            continue
        cid = int(issue.catalog_id)
        got_by_id[cid] = got_by_id.get(cid, 0) + int(issue.copies or 0)
    for name, qty in catalogue_units_billed(db, customer_id).items():
        row = by_name.get(name)
        if row:
            got_by_id[int(row.id)] = max(got_by_id.get(int(row.id), 0), int(qty))
    sent_by_name = catalogue_units_billed(db)
    ids = list(dict.fromkeys(assigned_ids + list(got_by_id)))
    out = []
    for catalog_id in ids:
        row = by_id.get(int(catalog_id))
        if not row:
            continue
        got = got_by_id.get(int(row.id), 0)
        sent = max(sent_by_name.get(row.name, 0), real_received_copies(db, row.id))
        out.append({
            "id": row.id,
            "name": row.name,
            "received": got,
            "needs_send": catalog_id in assigned_ids and got < 1,
            "copies_left": int(row.copies_made) - sent,
        })
    out.sort(key=lambda item: (not item["needs_send"], item["name"].lower()))
    return out


def assign_parties(db: Session, catalog_id: int, customer_ids: list[int]) -> int:
    row = db.get(OurCatalog, catalog_id)
    if not row:
        raise HTTPException(404, "catalog not found")
    added = 0
    for customer_id in customer_ids:
        if not db.get(Customer, int(customer_id)):
            continue
        exists = (
            db.query(OurCatalogAssignment)
            .filter(OurCatalogAssignment.catalog_id == row.id, OurCatalogAssignment.customer_id == int(customer_id))
            .first()
        )
        if exists:
            continue
        db.add(OurCatalogAssignment(catalog_id=row.id, customer_id=int(customer_id)))
        added += 1
    db.flush()
    return added


def unassign_party(db: Session, catalog_id: int, customer_id: int) -> None:
    row = (
        db.query(OurCatalogAssignment)
        .filter(OurCatalogAssignment.catalog_id == catalog_id, OurCatalogAssignment.customer_id == customer_id)
        .first()
    )
    if row:
        db.delete(row)
        db.flush()


def _manual_issue(db: Session, issue_id: int) -> OurCatalogIssue:
    issue = db.get(OurCatalogIssue, issue_id)
    if not issue:
        raise HTTPException(404, "record not found")
    if issue.bill_id:
        raise HTTPException(400, "This copy is on a bill. Cancel that bill to change it.")
    return issue


def update_issue(db: Session, issue_id: int, *, copies: int, issued_on: date | None) -> OurCatalogIssue:
    issue = _manual_issue(db, issue_id)
    if copies < 1:
        raise HTTPException(400, "Enter how many copies")
    catalog = db.get(OurCatalog, issue.catalog_id)
    sent = issued_copies(db, issue.catalog_id) - int(issue.copies) + copies
    if catalog and sent > catalog.copies_made:
        left = catalog.copies_made - (issued_copies(db, issue.catalog_id) - int(issue.copies))
        raise HTTPException(400, f"Only {left} copies of {catalog.name} are left")
    issue.copies = copies
    if issued_on:
        issue.issued_on = issued_on
    db.flush()
    return issue


def adjust_copies(db: Session, catalog_id: int, delta: int) -> OurCatalog:
    """Change how many copies of this catalogue we hold. Does not move item stock."""
    row = db.get(OurCatalog, catalog_id)
    if not row:
        raise HTTPException(404, "catalog not found")
    if delta == 0:
        raise HTTPException(400, "Enter how many to add or remove")
    sent = issued_copies(db, row.id)
    new_total = int(row.copies_made) + int(delta)
    if new_total < sent:
        raise HTTPException(400, f"{sent} copies are already sent. Left cannot go below zero.")
    if new_total < 1:
        raise HTTPException(400, "Keep at least one copy")
    row.copies_made = new_total
    db.flush()
    return row


def delete_issue(db: Session, issue_id: int) -> int:
    issue = _manual_issue(db, issue_id)
    catalog_id = issue.catalog_id
    db.delete(issue)
    db.flush()
    return catalog_id


def record_issue(
    db: Session,
    *,
    catalog_id: int,
    customer_id: int,
    copies: int,
    price: Decimal,
    issued_on: date | None,
    bill_id: int | None,
    note: str | None,
) -> OurCatalogIssue:
    row = db.get(OurCatalog, catalog_id)
    if not row:
        raise HTTPException(404, "catalog not found")
    if copies < 1:
        raise HTTPException(400, "Enter how many copies")
    sent = issued_copies(db, row.id)
    if sent + copies > row.copies_made:
        raise HTTPException(400, f"Only {row.copies_made - sent} copies of {row.name} are left")
    issue = OurCatalogIssue(
        catalog_id=row.id,
        customer_id=customer_id,
        copies=copies,
        price=Decimal(str(price or 0)).quantize(Decimal("0.01")),
        bill_id=bill_id,
        issued_on=issued_on or today_ist(),
        note=(note or "").strip() or None,
    )
    db.add(issue)
    db.flush()
    return issue


def bill_catalog_charges(db: Session, customer_id: int, catalogs: list[dict]) -> tuple[list[dict], list[dict]]:
    """Return (additional charges for price > 0, print rows for every selected catalog)."""
    charges = []
    printed = []
    for item in catalogs or []:
        catalog_id = int(item.get("catalog_id") or 0)
        row = db.get(OurCatalog, catalog_id)
        if not row:
            raise HTTPException(400, "catalog not found")
        price = Decimal(str(item.get("price") or "0")).quantize(Decimal("0.01"))
        if price < 0:
            price = Decimal("0")
        got = real_received_copies(db, row.id, customer_id)
        printed.append({
            "catalog_id": row.id,
            "name": row.name,
            "price": format(price, "f"),
            "already": got,
        })
        if price > 0:
            charges.append({"name": f"Catalogue {row.name}", "amount": format(price, "f")})
    return charges, printed


def save_bill_catalogs(db: Session, *, bill_id: int, customer_id: int, catalogs: list[dict], issued_on: date | None) -> None:
    from app.models.customer_bill import CustomerBill
    from sqlalchemy.orm.attributes import flag_modified

    printed = []
    for item in catalogs or []:
        catalog_id = int(item.get("catalog_id") or 0)
        row = db.get(OurCatalog, catalog_id)
        if not row:
            continue
        price = Decimal(str(item.get("price") or "0")).quantize(Decimal("0.01"))
        got = real_received_copies(db, row.id, customer_id)
        record_issue(
            db,
            catalog_id=row.id,
            customer_id=customer_id,
            copies=1,
            price=price,
            issued_on=issued_on,
            bill_id=bill_id,
            note="On the bill" if got < 1 else "Another copy on the bill",
        )
        printed.append({"catalog_id": row.id, "name": row.name, "price": format(price, "f"), "already": got})
    if not printed:
        return
    bill = db.get(CustomerBill, bill_id)
    if not bill:
        return
    totals = dict(bill.totals_json or {})
    totals["catalogs"] = printed
    bill.totals_json = totals
    flag_modified(bill, "totals_json")


def release_bill_catalogs(db: Session, bill_id: int) -> None:
    db.query(OurCatalogIssue).filter(OurCatalogIssue.bill_id == bill_id).delete(synchronize_session=False)


def import_sample_journals(db: Session) -> list[str]:
    """Turn the existing sample-catalogue journals into catalogs. Does not post a new expense."""
    journals = (
        db.query(StockJournal)
        .filter(StockJournal.voided_at.is_(None), StockJournal.expense_category == "sample catalogues")
        .order_by(StockJournal.id.asc())
        .all()
    )
    made = []
    for journal in journals:
        if db.query(OurCatalog).filter(OurCatalog.stock_journal_id == journal.id).first():
            continue
        lines = db.query(StockJournalLine).filter(StockJournalLine.journal_id == journal.id).all()
        outward = [ln for ln in lines if int(ln.quantity_delta) < 0]
        if not outward:
            continue
        copies = min(-int(ln.quantity_delta) for ln in outward)
        if copies < 1:
            continue
        name = (journal.narration or f"Catalog {journal.id}").strip()
        catalog = OurCatalog(
            name=name,
            copies_made=copies,
            expense_id=journal.expense_id,
            stock_journal_id=journal.id,
            created_at=journal.created_at,
        )
        db.add(catalog)
        db.flush()
        for ln in outward:
            per_copy = -int(ln.quantity_delta) // copies
            if per_copy < 1:
                per_copy = 1
            db.add(OurCatalogLine(catalog_id=catalog.id, catalog_product_id=ln.catalog_product_id, quantity=per_copy))
        made.append(f"{name} × {copies}")
    db.flush()
    return made


import re

# Each printed catalogue is one product category. The stock-journal names were
# the sampling run, not the catalogue the party was given.
_JOURNAL_TO_CATALOG = {
    "SAMPLING ALBUM NO. 01": "2027 ALBUM NO. 01",
    "SAMPLING ALBUM NO.02": "2027 ALBUM NO. 02",
    "ALBUM NO. 03": "2027 ALBUM NO. 03",
    "SAMPLING ALBUM NO, 04": "2027 ALBUM NO. 04",
    "ALBUM NO. 05 SAMPLING": "2027 ALBUM NO. 05",
    "SAMPLING ALBUM NO. 123": "2027 ALBUM NO. 123",
    "SAMPLING BOX NO. 07": "2027 BOX NO. 07",
    "SAMPLING BOX NO. 09": "2027 BOX NO. 09",
    "SAMPLING BOX NO. 10 (PADDING)": "2027 BOX NO. 10",
    "sampling envelope album": "2027 ENVELOPE ALBUM",
    "SAMPLING BP ALBUM": "BP ALBUM 2027",
    "SAMPLING BP+SC (CARDS)": "BP+SC ALBUM 2027",
}

# slot: category column, second_category, or any of the three album slots.
_CATEGORY_SLOT = {
    "2027 ALBUM NO. 01": ("category", "ALBUM NO. 01"),
    "2027 ALBUM NO. 02": ("category", "ALBUM NO. 02"),
    "2027 ALBUM NO. 03": ("category", "ALBUM NO. 03"),
    "2027 ALBUM NO. 04": ("any", "ALBUM NO. 04"),
    "2027 ALBUM NO. 05": ("any", "ALBUM NO. 05"),
    "2027 ALBUM NO. 123": ("any", "ALBUM NO. 123"),
    "2027 BOX NO. 07": ("category", "BOX NO. 07"),
    "2027 BOX NO. 09": ("category", "BOX NO. 09"),
    "2027 BOX NO. 10": ("category", "BOX NO. 10"),
    "2027 ENVELOPE ALBUM": ("category", "ENVELOPE ALBUM"),
    "BP ALBUM 2027": ("category", "BP ALBUM"),
    "BP+SC ALBUM 2027": ("second", "BP+SC ALBUM"),
}


def catalog_name_for_bill_sku(sku: str) -> str | None:
    """Fold spacing differences (NO.05, NO. 05) onto the 12 category catalogues."""
    raw = re.sub(r"\s+", " ", (sku or "").strip().upper())
    if raw in ("BP ALBUM 2027", "BP+SC ALBUM 2027", "2027 ENVELOPE ALBUM"):
        return raw
    match = re.fullmatch(r"2027 (ALBUM|BOX) NO\.?\s*(\d+)", raw)
    if not match:
        return None
    name = f"2027 {match.group(1)} NO. {match.group(2)}"
    return name if name in _CATEGORY_SLOT else None


def _products_in_album(db: Session, slot: str, album: str) -> list[CatalogProduct]:
    query = db.query(CatalogProduct).filter(CatalogProduct.deleted_at.is_(None))
    if slot == "category":
        query = query.filter(CatalogProduct.category == album)
    elif slot == "second":
        query = query.filter(CatalogProduct.second_category == album)
    else:
        query = query.filter(
            (CatalogProduct.category == album)
            | (CatalogProduct.second_category == album)
            | (CatalogProduct.category_3 == album)
        )
    return query.order_by(CatalogProduct.our_product_id.asc()).all()


def realign_category_catalogs(db: Session) -> dict:
    """Name each catalogue after its category and copy bill sends onto that catalogue.

    Bills, stock journals, and expenses stay as they are. Only the catalogue
    ledger is rewritten.
    """
    from app.models.customer_bill import CustomerBill, CustomerBillLine

    renamed = []
    for old, new in _JOURNAL_TO_CATALOG.items():
        row = db.query(OurCatalog).filter(OurCatalog.name == old).one_or_none()
        if not row:
            continue
        taken = db.query(OurCatalog).filter(OurCatalog.name == new, OurCatalog.id != row.id).first()
        if taken:
            continue
        row.name = new
        renamed.append(new)
    db.flush()

    catalogs = {row.name: row for row in db.query(OurCatalog).all()}
    line_counts = {}
    for name, (slot, album) in _CATEGORY_SLOT.items():
        catalog = catalogs.get(name)
        if not catalog:
            continue
        db.query(OurCatalogLine).filter(OurCatalogLine.catalog_id == catalog.id).delete(synchronize_session=False)
        products = _products_in_album(db, slot, album)
        for product in products:
            db.add(OurCatalogLine(catalog_id=catalog.id, catalog_product_id=product.id, quantity=1))
        line_counts[name] = len(products)
    db.flush()

    db.query(OurCatalogIssue).filter(OurCatalogIssue.note.like("From bill %")).delete(synchronize_session=False)
    db.flush()

    lines = (
        db.query(CustomerBillLine, CustomerBill)
        .join(CustomerBill, CustomerBill.id == CustomerBillLine.bill_id)
        .filter(
            CustomerBill.cancelled_at.is_(None),
            CustomerBillLine.status == "billed",
            CustomerBillLine.quantity_shipped > 0,
        )
        .all()
    )
    grouped: dict[tuple, dict] = {}
    for line, bill in lines:
        name = catalog_name_for_bill_sku(line.our_product_id)
        catalog = catalogs.get(name or "")
        if not catalog:
            continue
        key = (catalog.id, int(bill.customer_id), int(bill.id))
        slot = grouped.setdefault(key, {"copies": 0, "amount": Decimal("0"), "on": bill.bill_date, "number": bill.bill_number, "name": catalog.name})
        qty = int(line.quantity_shipped or 0)
        slot["copies"] += qty
        amount = Decimal(str(line.line_total or 0))
        if amount == 0 and line.unit_price:
            amount = Decimal(str(line.unit_price)) * qty
        slot["amount"] += amount

    by_catalog: dict[int, int] = {}
    for (catalog_id, _customer_id, _bill_id), slot in grouped.items():
        by_catalog[catalog_id] = by_catalog.get(catalog_id, 0) + int(slot["copies"])
    over = []
    for catalog in catalogs.values():
        if catalog.name not in _CATEGORY_SLOT:
            continue
        need = by_catalog.get(catalog.id, 0)
        if need > int(catalog.copies_made or 0):
            over.append(f"{catalog.name} sent {need} made {catalog.copies_made}")
    if over:
        raise HTTPException(400, "; ".join(over))

    added = 0
    for (catalog_id, customer_id, bill_id), slot in grouped.items():
        price = (slot["amount"] / slot["copies"]).quantize(Decimal("0.01")) if slot["copies"] else Decimal("0")
        db.add(OurCatalogIssue(
            catalog_id=catalog_id,
            customer_id=customer_id,
            copies=slot["copies"],
            price=price,
            bill_id=bill_id,
            issued_on=slot["on"] or today_ist(),
            note=f"From bill {slot['number']}",
        ))
        added += 1
    db.flush()
    sent = {}
    for catalog in catalogs.values():
        if catalog.name in _CATEGORY_SLOT:
            sent[catalog.name] = issued_copies(db, catalog.id)
    return {"renamed": renamed, "lines": line_counts, "issues": added, "sent": sent}


def catalog_name_for_categories(category: str | None, second: str | None, third: str | None, sku: str = "") -> str | None:
    """The catalogue a product belongs to, from its album category, then its own name."""
    cats = [(category or "").strip(), (second or "").strip(), (third or "").strip()]
    for name, (slot, album) in _CATEGORY_SLOT.items():
        if slot == "category" and cats[0] == album:
            return name
        if slot == "second" and cats[1] == album:
            return name
        if slot == "any" and album in cats:
            return name
    return catalog_name_for_bill_sku(sku)


def sync_album_sends(db: Session, bill_id: int | None = None) -> int:
    """One catalogue entry per bill that sold an item from that album. Copies stay 1."""
    from app.models.customer_bill import CustomerBill, CustomerBillLine

    catalogs = {row.name: row for row in db.query(OurCatalog).all()}
    albums = [album for _name, (_slot, album) in _CATEGORY_SLOT.items()]
    products = (
        db.query(CatalogProduct)
        .filter(
            CatalogProduct.deleted_at.is_(None),
            (CatalogProduct.category.in_(albums))
            | (CatalogProduct.second_category.in_(albums))
            | (CatalogProduct.category_3.in_(albums)),
        )
        .all()
    )
    products_by_id = {product.id: product for product in products}
    if not products_by_id:
        return 0
    query = (
        db.query(CustomerBillLine, CustomerBill)
        .join(CustomerBill, CustomerBill.id == CustomerBillLine.bill_id)
        .filter(
            CustomerBill.cancelled_at.is_(None),
            CustomerBill.deleted_at.is_(None),
            CustomerBillLine.status == "billed",
            CustomerBillLine.quantity_shipped > 0,
            CustomerBillLine.catalog_product_id.in_(list(products_by_id)),
        )
    )
    if bill_id is not None:
        query = query.filter(CustomerBill.id == bill_id)
    rows = query.all()
    wanted: set[tuple[int, int, int]] = set()
    dates = {}
    numbers = {}
    for line, bill in rows:
        product = products_by_id.get(line.catalog_product_id)
        name = catalog_name_for_categories(
            getattr(product, "category", None),
            getattr(product, "second_category", None),
            getattr(product, "category_3", None),
            line.our_product_id,
        ) if product else catalog_name_for_bill_sku(line.our_product_id)
        catalog = catalogs.get(name or "")
        if not catalog:
            continue
        key = (catalog.id, int(bill.customer_id), int(bill.id))
        wanted.add(key)
        dates[key] = bill.bill_date
        numbers[key] = bill.bill_number
    added = 0
    catalog_ids = {catalog.id for catalog in catalogs.values() if catalog.name in _CATEGORY_SLOT}
    existing = set()
    if catalog_ids:
        for catalog_id, customer_id, this_bill_id in (
            db.query(OurCatalogIssue.catalog_id, OurCatalogIssue.customer_id, OurCatalogIssue.bill_id)
            .filter(OurCatalogIssue.catalog_id.in_(catalog_ids), OurCatalogIssue.bill_id.isnot(None))
            .all()
        ):
            existing.add((int(catalog_id), int(customer_id), int(this_bill_id)))
    sent_by_catalog = {catalog_id: issued_copies(db, catalog_id) for catalog_id in {key[0] for key in wanted}}
    for catalog_id, customer_id, this_bill_id in wanted:
        if (catalog_id, customer_id, this_bill_id) in existing:
            continue
        catalog = db.get(OurCatalog, catalog_id)
        sent = sent_by_catalog.get(catalog_id, 0) + 1
        sent_by_catalog[catalog_id] = sent
        if catalog and sent > int(catalog.copies_made or 0):
            catalog.copies_made = sent
        db.add(OurCatalogIssue(
            catalog_id=catalog_id,
            customer_id=customer_id,
            copies=1,
            price=Decimal("0"),
            bill_id=this_bill_id,
            issued_on=dates.get((catalog_id, customer_id, this_bill_id)) or today_ist(),
            note=f"From bill {numbers.get((catalog_id, customer_id, this_bill_id)) or this_bill_id}",
        ))
        added += 1
    if added:
        db.flush()
    return added

