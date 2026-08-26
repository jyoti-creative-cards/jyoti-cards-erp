from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.catalog_product import CatalogProduct
from app.models.city import City
from app.models.customer import Customer
from app.models.customer_bill import CustomerBill, CustomerBillLine
from app.models.customer_return import CustomerReturn, CustomerReturnLine
from app.services.ar_ledger import post_credit_note_entry
from app.services.stock_receipt import add_stock
from app.services.storage import customer_folder_slug, customer_return_key, presigned_urls, storage_configured, upload_bytes


def _d(v) -> Decimal:
    return Decimal(str(v or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _customer_label(db: Session, customer_id: int) -> str:
    c = db.get(Customer, customer_id)
    if not c:
        return f"Customer #{customer_id}"
    city_name = None
    if c.city_id:
        city = db.get(City, c.city_id)
        city_name = city.name if city else None
    return f"{c.business_name} — {city_name}" if city_name else c.business_name


def _sold_unit_price(bill: CustomerBill, line: CustomerBillLine) -> Decimal:
    """Effective sold price incl. discount allocation."""
    qty = int(line.quantity_shipped or 0)
    totals = bill.totals_json or {}
    for tl in totals.get("lines") or []:
        if int(tl.get("catalog_product_id") or 0) == line.catalog_product_id:
            ep = tl.get("effective_price")
            if ep is not None:
                return _d(ep)
            after = tl.get("line_inclusive_after_discount") or tl.get("line_total")
            if after is not None and qty > 0:
                return _d(Decimal(str(after)) / Decimal(qty))
    if qty > 0 and line.line_total is not None:
        return _d(Decimal(str(line.line_total)) / Decimal(qty))
    return _d(line.unit_price)


def _returned_qty_map(db: Session, bill_line_ids: list[int]) -> dict[int, int]:
    if not bill_line_ids:
        return {}
    rows = (
        db.query(CustomerReturnLine.bill_line_id, func.coalesce(func.sum(CustomerReturnLine.quantity_returned), 0))
        .join(CustomerReturn, CustomerReturn.id == CustomerReturnLine.return_id)
        .filter(CustomerReturnLine.bill_line_id.in_(bill_line_ids), CustomerReturn.deleted_at.is_(None))
        .group_by(CustomerReturnLine.bill_line_id)
        .all()
    )
    return {int(lid): int(qty or 0) for lid, qty in rows}


def list_returnable_lines(db: Session, customer_id: int) -> list[dict]:
    rows = (
        db.query(CustomerBillLine, CustomerBill)
        .join(CustomerBill, CustomerBillLine.bill_id == CustomerBill.id)
        .filter(CustomerBill.customer_id == customer_id, CustomerBillLine.status == "billed", CustomerBillLine.quantity_shipped > 0)
        .order_by(CustomerBill.created_at.desc(), CustomerBillLine.id.asc())
        .all()
    )
    returned = _returned_qty_map(db, [ln.id for ln, _ in rows])
    out: list[dict] = []
    for line, bill in rows:
        already = returned.get(line.id, 0)
        remaining = int(line.quantity_shipped) - already
        if remaining <= 0:
            continue
        sold = _sold_unit_price(bill, line)
        out.append(
            {
                "bill_line_id": line.id,
                "bill_id": bill.id,
                "bill_number": bill.bill_number,
                "catalog_product_id": line.catalog_product_id,
                "our_product_id": line.our_product_id,
                "quantity_billed": int(line.quantity_shipped),
                "quantity_returned": already,
                "quantity_returnable": remaining,
                "sold_unit_price": format(sold, "f"),
                "unit_price": format(_d(line.unit_price), "f"),
                "bill_date": bill.created_at,
            }
        )
    return out


def _next_return_number(db: Session, customer_id: int) -> str:
    count = db.query(func.count(CustomerReturn.id)).filter(CustomerReturn.customer_id == customer_id).scalar() or 0
    return f"CN-{customer_id}-{int(count) + 1:04d}"


def create_customer_return(
    db: Session,
    *,
    customer_id: int,
    lines: list[dict],
    credit_amount: Decimal,
    notes: Optional[str],
    actor_type: str,
    actor_id: Optional[int],
    actor_name: str,
) -> CustomerReturn:
    customer = db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(404, "customer not found")
    if not lines:
        raise HTTPException(400, "add at least one return line")

    returnable = {r["bill_line_id"]: r for r in list_returnable_lines(db, customer_id)}
    calc_total = Decimal("0")
    prepared: list[dict] = []

    for raw in lines:
        bill_line_id = int(raw["bill_line_id"])
        qty = int(raw.get("quantity") or 0)
        if qty <= 0:
            continue
        info = returnable.get(bill_line_id)
        if not info:
            raise HTTPException(400, f"bill line {bill_line_id} not returnable")
        if qty > info["quantity_returnable"]:
            raise HTTPException(
                400,
                f"{info['our_product_id']}: max returnable {info['quantity_returnable']}",
            )
        sold = _d(info["sold_unit_price"])
        line_calc = (sold * Decimal(qty)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        calc_total += line_calc
        prepared.append(
            {
                "bill_line_id": bill_line_id,
                "bill_id": info["bill_id"],
                "catalog_product_id": info["catalog_product_id"],
                "our_product_id": info["our_product_id"],
                "quantity": qty,
                "sold_unit_price": sold,
                "line_calculated": line_calc,
            }
        )

    if not prepared:
        raise HTTPException(400, "enter return qty on at least one line")

    credit = credit_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if credit < 0:
        raise HTTPException(400, "credit amount cannot be negative")

    ret = CustomerReturn(
        customer_id=customer_id,
        return_number=_next_return_number(db, customer_id),
        calculated_amount=calc_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        credit_amount=credit,
        notes=(notes or "").strip() or None,
        created_by_type=actor_type,
        created_by_id=actor_id,
        created_by_name=actor_name,
    )
    db.add(ret)
    db.flush()

    for p in prepared:
        db.add(
            CustomerReturnLine(
                return_id=ret.id,
                bill_id=p["bill_id"],
                bill_line_id=p["bill_line_id"],
                catalog_product_id=p["catalog_product_id"],
                our_product_id=p["our_product_id"],
                quantity_returned=p["quantity"],
                sold_unit_price=p["sold_unit_price"],
                line_calculated=p["line_calculated"],
            )
        )
        add_stock(
            db,
            catalog_product_id=p["catalog_product_id"],
            our_product_id=p["our_product_id"],
            quantity=p["quantity"],
            entry_type="customer_return",
            reference_type="customer_return",
            reference_id=ret.id,
            party=customer.business_name,
            notes=f"Return {ret.return_number}",
        )

    post_credit_note_entry(
        db,
        customer_id=customer_id,
        return_id=ret.id,
        amount=credit,
        description=f"Credit note {ret.return_number} — ₹{credit}",
        actor_type=actor_type,
        actor_id=actor_id,
        actor_name=actor_name,
    )

    try:
        generate_customer_return_document(db, ret.id)
    except Exception:
        pass

    return ret


def list_returns_by_customer(db: Session) -> list[dict]:
    rows = (
        db.query(
            CustomerReturn.customer_id,
            func.count(CustomerReturn.id),
            func.coalesce(func.sum(CustomerReturn.credit_amount), 0),
            func.max(CustomerReturn.created_at),
        )
        .filter(CustomerReturn.deleted_at.is_(None))
        .group_by(CustomerReturn.customer_id)
        .all()
    )
    ids = [int(cid) for cid, *_ in rows]
    customers = {c.id: c for c in db.query(Customer).filter(Customer.id.in_(ids)).all()} if ids else {}
    city_ids = {c.city_id for c in customers.values() if c.city_id}
    cities = {
        c.id: c.name
        for c in (db.query(City).filter(City.id.in_(city_ids)).all() if city_ids else [])
    }
    out = []
    for customer_id, cnt, credit_sum, last_at in rows:
        c = customers.get(int(customer_id))
        city_name = cities.get(c.city_id) if c and c.city_id else None
        business = c.business_name if c else f"Customer #{customer_id}"
        label = f"{business} — {city_name}" if city_name else business
        out.append(
            {
                "customer_id": int(customer_id),
                "customer_label": label,
                "business_name": business,
                "person_name": c.person_name if c else None,
                "alias": c.alias if c else None,
                "phone": c.phone if c else None,
                "city_name": city_name,
                "return_count": int(cnt or 0),
                "credit_total": format(_d(credit_sum), "f"),
                "last_return_at": last_at,
            }
        )
    out.sort(key=lambda x: (x["customer_label"] or "").lower())
    return out


def list_customer_returns(db: Session, customer_id: int) -> list[dict]:
    rows = (
        db.query(CustomerReturn)
        .filter(CustomerReturn.customer_id == customer_id, CustomerReturn.deleted_at.is_(None))
        .order_by(CustomerReturn.created_at.desc())
        .all()
    )
    out = []
    for r in rows:
        line_count = db.query(func.count(CustomerReturnLine.id)).filter(CustomerReturnLine.return_id == r.id).scalar() or 0
        qty = (
            db.query(func.coalesce(func.sum(CustomerReturnLine.quantity_returned), 0))
            .filter(CustomerReturnLine.return_id == r.id)
            .scalar()
            or 0
        )
        out.append(
            {
                "id": r.id,
                "return_number": r.return_number,
                "credit_amount": format(_d(r.credit_amount), "f"),
                "calculated_amount": format(_d(r.calculated_amount), "f"),
                "notes": r.notes,
                "line_count": int(line_count),
                "total_quantity": int(qty),
                "document_key": r.document_key,
                "created_by_name": r.created_by_name,
                "created_at": r.created_at,
            }
        )
    return out


def get_return_detail(db: Session, return_id: int) -> dict:
    ret = db.get(CustomerReturn, return_id)
    if not ret:
        raise HTTPException(404, "return not found")
    lines = db.query(CustomerReturnLine).filter(CustomerReturnLine.return_id == return_id).order_by(CustomerReturnLine.id).all()
    bill_ids = {ln.bill_id for ln in lines}
    bills = {b.id: b for b in db.query(CustomerBill).filter(CustomerBill.id.in_(bill_ids)).all()} if bill_ids else {}
    return {
        "id": ret.id,
        "customer_id": ret.customer_id,
        "customer_label": _customer_label(db, ret.customer_id),
        "return_number": ret.return_number,
        "credit_amount": format(_d(ret.credit_amount), "f"),
        "calculated_amount": format(_d(ret.calculated_amount), "f"),
        "notes": ret.notes,
        "document_key": ret.document_key,
        "created_by_name": ret.created_by_name,
        "created_at": ret.created_at,
        "deleted_at": ret.deleted_at,
        "deleted_reason": ret.deleted_reason,
        "lines": [
            {
                "id": ln.id,
                "bill_id": ln.bill_id,
                "bill_number": bills[ln.bill_id].bill_number if ln.bill_id in bills else str(ln.bill_id),
                "bill_line_id": ln.bill_line_id,
                "catalog_product_id": ln.catalog_product_id,
                "our_product_id": ln.our_product_id,
                "quantity_returned": ln.quantity_returned,
                "sold_unit_price": format(_d(ln.sold_unit_price), "f"),
                "line_calculated": format(_d(ln.line_calculated), "f"),
            }
            for ln in lines
        ],
    }


def generate_customer_return_document(db: Session, return_id: int) -> str | None:
    from app.services.pdf_documents import render_customer_return_pdf

    ret = db.get(CustomerReturn, return_id)
    if not ret:
        return None
    customer = db.get(Customer, ret.customer_id)
    if not customer:
        return None
    city_name = None
    if customer.city_id:
        city = db.get(City, customer.city_id)
        city_name = city.name if city else None

    lines = db.query(CustomerReturnLine).filter(CustomerReturnLine.return_id == return_id).all()
    bill_ids = {ln.bill_id for ln in lines}
    bills = {b.id: b for b in db.query(CustomerBill).filter(CustomerBill.id.in_(bill_ids)).all()} if bill_ids else {}

    pdf_lines = []
    image_urls: dict[int, str | None] = {}
    order_ids: list[str] = []
    for ln in lines:
        bill = bills.get(ln.bill_id)
        if bill and bill.bill_number not in order_ids:
            order_ids.append(bill.bill_number)
        prod = db.get(CatalogProduct, ln.catalog_product_id)
        urls = presigned_urls(prod.image_keys or []) if prod else []
        image_urls[ln.catalog_product_id] = urls[0] if urls else None
        pdf_lines.append(
            {
                "catalog_product_id": ln.catalog_product_id,
                "our_product_id": ln.our_product_id,
                "name": prod.vendor_product_id if prod else ln.our_product_id,
                "quantity": ln.quantity_returned,
                "unit_price": format(_d(ln.sold_unit_price), "f"),
                "line_total": format(_d(ln.line_calculated), "f"),
                "bill_number": bill.bill_number if bill else str(ln.bill_id),
            }
        )

    pdf = render_customer_return_pdf(
        return_id=ret.id,
        return_number=ret.return_number,
        customer_name=customer.business_name,
        customer_phone=customer.phone,
        customer_address=customer.address,
        customer_city=city_name,
        lines=pdf_lines,
        image_urls=image_urls,
        calculated_amount=format(_d(ret.calculated_amount), "f"),
        credit_amount=format(_d(ret.credit_amount), "f"),
        notes=ret.notes,
        bill_numbers=order_ids,
        created_by=ret.created_by_name,
        created_at=ret.created_at or datetime.now(timezone.utc),
    )
    if not storage_configured():
        return None
    slug = customer_folder_slug(customer.business_name)
    key = customer_return_key(slug, ret.id, ret.return_number)
    upload_bytes(key, pdf, content_type="application/pdf")
    ret.document_key = key
    db.flush()
    return key
