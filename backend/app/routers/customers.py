from __future__ import annotations

import io
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db, legacy_active_value, sql_is_active_true
from app.deps import require_admin
from app.integrations.whatsapp.client import send_account_creation, _e164 as normalize_whatsapp_e164
from app.models.ar_invoice import ARInvoice
from app.models.customer import Customer
from app.models.customer_order import CustomerOrder
from app.models.invoice_payment import InvoicePayment
from app.schemas.customer import CustomerCreate, CustomerPublic, CustomerUpdate
from app.services.passwords import hash_password

router = APIRouter(prefix="/customers", tags=["customers"])


def _to_public(row: Customer) -> CustomerPublic:
    return CustomerPublic(
        id=row.id,
        name=row.name,
        phone=row.phone,
        company_name=row.company_name,
        alias=row.alias,
        address=row.address,
        secondary_phone=row.secondary_phone,
        city=row.city,
        city_id=row.city_id,
        route_id=row.route_id,
        credit_limit=format(row.credit_limit, "f") if row.credit_limit is not None else None,
        credit_override=row.credit_override or False,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _send_wa_safe(name: str, phone: str, plain: str) -> None:
    try:
        send_account_creation(phone=phone, customer_name=name, login_phone=phone, password=plain)
    except Exception as ex:
        print("WhatsApp send failed:", ex)


@router.get("", response_model=List[CustomerPublic], dependencies=[Depends(require_admin)])
def list_customers(
    db: Session = Depends(get_db),
    include_inactive: bool = Query(False),
    deleted: Optional[bool] = Query(None, description="true = only deleted; false/omit = exclude deleted"),
    route_id: Optional[int] = Query(None),
    city_id: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
) -> List[CustomerPublic]:
    q = db.query(Customer)
    if deleted is True:
        q = q.filter(Customer.deleted_at.isnot(None))
    else:
        q = q.filter(Customer.deleted_at.is_(None))
        if not include_inactive:
            q = q.filter(sql_is_active_true(Customer.is_active))
    if route_id is not None:
        q = q.filter(Customer.route_id == route_id)
    if city_id is not None:
        q = q.filter(Customer.city_id == city_id)
    if search:
        s = f"%{search.lower()}%"
        from sqlalchemy import func as sqlfunc, or_
        q = q.filter(or_(
            sqlfunc.lower(Customer.name).like(s),
            sqlfunc.lower(Customer.phone).like(s),
            sqlfunc.lower(Customer.alias).like(s),
            sqlfunc.lower(Customer.company_name).like(s),
        ))
    rows = q.order_by(Customer.id.asc()).all()
    return [_to_public(r) for r in rows]


@router.get("/{customer_id}", response_model=CustomerPublic, dependencies=[Depends(require_admin)])
def get_customer(customer_id: int, db: Session = Depends(get_db)) -> CustomerPublic:
    row = db.get(Customer, customer_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="customer not found")
    return _to_public(row)


@router.post("", response_model=CustomerPublic, dependencies=[Depends(require_admin)])
def create_customer(
    body: CustomerCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> Customer:
    phone = normalize_whatsapp_e164(body.phone.strip())
    if not phone:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid phone")
    sec = (body.secondary_phone or "").strip()
    sec_norm = normalize_whatsapp_e164(sec) if sec else None
    if sec and not sec_norm:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid secondary phone")
    # Auto-generate password from last 4 digits of phone if not provided
    import random, string as _str
    plain = (body.password or "").strip() or phone[-4:] or "".join(random.choices(_str.digits, k=4))

    existing = db.query(Customer).filter(Customer.phone == phone).one_or_none()
    if existing is not None and legacy_active_value(existing.is_active):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="phone already registered",
        )

    if existing is not None:
        # Same phone on a soft-deleted row: recycle it so UNIQUE(phone) is not violated.
        existing.name = body.name.strip()
        existing.password_hash = hash_password(plain)
        existing.company_name = body.company_name.strip() if body.company_name else None
        existing.address = body.address.strip() if body.address else None
        existing.secondary_phone = sec_norm
        existing.city = body.city.strip() if body.city else None
        existing.is_active = True
        db.add(existing)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="phone already registered",
            ) from None
        db.refresh(existing)
        background_tasks.add_task(
            _send_wa_safe,
            existing.name,
            existing.phone,
            plain,
        )
        return existing

    row = Customer(
        name=body.name.strip(),
        phone=phone,
        password_hash=hash_password(plain),
        company_name=(body.company_name.strip() if body.company_name else None),
        alias=(body.alias.strip() if body.alias else None),
        address=(body.address.strip() if body.address else None),
        secondary_phone=sec_norm,
        city=(body.city.strip() if body.city else None),
        city_id=body.city_id,
        route_id=body.route_id,
        credit_limit=body.credit_limit,
        credit_override=body.credit_override or False,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="phone already registered",
        ) from None
    db.refresh(row)

    background_tasks.add_task(
        _send_wa_safe,
        row.name,
        row.phone,
        plain,
    )
    return _to_public(row)


@router.patch("/{customer_id}", response_model=CustomerPublic, dependencies=[Depends(require_admin)])
def update_customer(
    customer_id: int,
    body: CustomerUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> Customer:
    row = db.get(Customer, customer_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="customer not found")

    data = body.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="no fields to update")

    plain_password_for_wa = data.get("password")

    if "password" in data:
        row.password_hash = hash_password(data.pop("password"))

    if "phone" in data:
        phone = normalize_whatsapp_e164(str(data.pop("phone")).strip())
        if not phone:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid phone")
        if phone != row.phone:
            other = (
                db.query(Customer)
                .filter(Customer.phone == phone, Customer.id != row.id)
                .one_or_none()
            )
            if other is not None:
                if legacy_active_value(other.is_active):
                    raise HTTPException(
                        status.HTTP_409_CONFLICT,
                        detail="phone already registered",
                    )
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    detail="phone is tied to a deactivated customer; create with that phone to reopen it",
                )
        row.phone = phone

    if "name" in data:
        row.name = str(data.pop("name")).strip()

    if "company_name" in data:
        v = data.pop("company_name")
        row.company_name = v.strip() if isinstance(v, str) and v.strip() else None

    if "address" in data:
        v = data.pop("address")
        row.address = v.strip() if isinstance(v, str) and v.strip() else None

    if "city" in data:
        v = data.pop("city")
        row.city = v.strip() if isinstance(v, str) and v.strip() else None

    if "secondary_phone" in data:
        sec = data.pop("secondary_phone")
        if sec is None or (isinstance(sec, str) and not str(sec).strip()):
            row.secondary_phone = None
        else:
            sec_norm = normalize_whatsapp_e164(str(sec).strip())
            if not sec_norm:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid secondary phone")
            row.secondary_phone = sec_norm

    for field in ("alias", "city_id", "route_id", "credit_limit", "credit_override"):
        if field in data:
            setattr(row, field, data.pop(field))

    if data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"unknown fields: {list(data.keys())}")

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="phone already registered",
        ) from None
    db.refresh(row)
    pw_msg = (
        plain_password_for_wa
        if plain_password_for_wa is not None
        else "unchanged — use your existing password"
    )
    background_tasks.add_task(_send_wa_safe, row.name, row.phone, pw_msg)
    return _to_public(row)


@router.get("/{customer_id}/credit-summary", dependencies=[Depends(require_admin)])
def get_credit_summary(customer_id: int, db: Session = Depends(get_db)) -> dict:
    """Return credit limit, outstanding AR, and remaining credit for a customer."""
    row = db.get(Customer, customer_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="customer not found")

    outstanding = Decimal("0")
    from app.models.ar_invoice import ARInvoice
    from app.services.accounting import amount_paid_on_ar
    open_invoices = db.query(ARInvoice).filter(
        ARInvoice.customer_id == customer_id,
        ARInvoice.status != "paid",
    ).all()
    for inv in open_invoices:
        paid = amount_paid_on_ar(db, inv)
        bal = Decimal(str(inv.amount)) - paid
        if bal > 0:
            outstanding += bal

    credit_limit = row.credit_limit
    remaining = (credit_limit - outstanding) if credit_limit is not None else None

    return {
        "customer_id": customer_id,
        "credit_limit": format(credit_limit, "f") if credit_limit is not None else None,
        "outstanding": format(outstanding, "f"),
        "remaining": format(remaining, "f") if remaining is not None else None,
        "credit_override": row.credit_override or False,
    }


@router.post("/{customer_id}/reactivate", dependencies=[Depends(require_admin)])
def reactivate_customer(customer_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(Customer, customer_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="customer not found")
    row.is_active = True
    db.add(row)
    db.commit()
    return {"ok": True, "id": customer_id, "reactivated": True}


@router.post("/{customer_id}/restore", dependencies=[Depends(require_admin)])
def restore_customer(customer_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(Customer, customer_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="customer not found")
    row.deleted_at = None
    row.is_active = True
    db.add(row)
    db.commit()
    return {"ok": True, "id": customer_id, "restored": True}


@router.delete("/{customer_id}/permanent", dependencies=[Depends(require_admin)])
def permanently_delete_customer(customer_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(Customer, customer_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="customer not found")
    db.delete(row)
    db.commit()
    return {"ok": True, "id": customer_id, "permanently_deleted": True}


@router.delete("/{customer_id}", dependencies=[Depends(require_admin)])
def deactivate_customer(customer_id: int, db: Session = Depends(get_db)) -> dict:
    """Soft-delete: sets deleted_at and is_active=False."""
    row = db.get(Customer, customer_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="customer not found")
    row.is_active = False
    row.deleted_at = datetime.now(timezone.utc)
    db.add(row)
    db.commit()
    return {"ok": True, "id": customer_id, "deactivated": True}


# ── Statement schemas ──────────────────────────────────────────────────────────

class StatementEntry(BaseModel):
    date: datetime
    type: str          # "bill" | "payment"
    reference: str
    description: str
    debit: float
    credit: float
    running_balance: float
    order_id: Optional[int] = None
    order_status: Optional[str] = None
    bill_id: Optional[int] = None
    bill_no: Optional[str] = None


class CustomerStatementResponse(BaseModel):
    customer_id: int
    customer_name: str
    phone: str
    company_name: Optional[str]
    total_orders: int
    total_billed: float
    total_paid: float
    outstanding: float
    statement_date: datetime
    entries: List[StatementEntry]


# ── Stats schema ───────────────────────────────────────────────────────────────

class CustomerStats(BaseModel):
    customer_id: int
    total_orders: int
    total_billed: float
    invoice_count: int
    hot_score: float


# ── Helpers ────────────────────────────────────────────────────────────────────

def _build_statement(
    customer_id: int,
    db: Session,
    entry_filter: str = "all",  # "all" | "bills" | "receipts"
) -> CustomerStatementResponse:
    from app.models.customer_bill import CustomerBill

    cust = db.get(Customer, customer_id)
    if cust is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="customer not found")

    events: list[dict] = []

    # debit entries — only orders that have a bill (closed/billed orders)
    orders = (
        db.query(CustomerOrder)
        .filter(
            CustomerOrder.customer_id == customer_id,
            CustomerOrder.status.in_(["closed", "billed", "shipped"]),
            CustomerOrder.deleted_at.is_(None),
        )
        .all()
    )
    # Pre-fetch bills for these orders
    order_ids = [o.id for o in orders]
    bills_by_order: dict[int, CustomerBill] = {}
    if order_ids:
        for b in db.query(CustomerBill).filter(
            CustomerBill.customer_order_id.in_(order_ids),
            CustomerBill.bill_status != "cancelled",
        ).all():
            bills_by_order[b.customer_order_id] = b

    total_billed = Decimal("0")
    for o in orders:
        bill = bills_by_order.get(o.id)
        # Use bill grand_total if available (more accurate with GST/discount); else order total
        if bill and isinstance(bill.totals, dict):
            amt = Decimal(str(bill.totals.get("grand_total") or o.total_amount))
        else:
            amt = Decimal(str(o.total_amount))
        total_billed += amt
        item_count = len(o.items) if isinstance(o.items, list) else 0
        bill_label = f"Bill {bill.bill_no}" if bill and bill.bill_no else (f"Bill #{bill.id}" if bill else f"Order #{o.id}")
        events.append({
            "date": bill.created_at if bill else o.created_at,
            "type": "bill",
            "reference": bill_label,
            "description": f"{bill_label} — {item_count} item{'s' if item_count != 1 else ''}",
            "debit": float(amt),
            "credit": 0.0,
            "order_id": o.id,
            "order_status": o.status,
            "bill_id": bill.id if bill else None,
            "bill_no": bill.bill_no if bill else None,
        })

    # credit entries — payments on AR invoices for this customer
    ar_invoices = (
        db.query(ARInvoice)
        .filter(ARInvoice.customer_id == customer_id)
        .all()
    )
    ar_ids = [inv.id for inv in ar_invoices]
    total_paid = Decimal("0")
    if ar_ids:
        payments = (
            db.query(InvoicePayment)
            .filter(InvoicePayment.kind == "ar", InvoicePayment.ref_id.in_(ar_ids))
            .all()
        )
        for pmt in payments:
            amt = Decimal(str(pmt.amount))
            total_paid += amt
            ref = pmt.transaction_id or f"PMT-{pmt.id}"
            dt = pmt.created_at
            events.append({
                "date": dt,
                "type": "payment",
                "reference": ref,
                "description": f"Payment received — {ref}",
                "debit": 0.0,
                "credit": float(amt),
            })

    # Apply filter
    if entry_filter == "bills":
        events = [e for e in events if e["type"] == "bill"]
    elif entry_filter == "receipts":
        events = [e for e in events if e["type"] == "payment"]

    # Sort chronologically
    events.sort(key=lambda e: e["date"] if e["date"] else datetime.min.replace(tzinfo=timezone.utc))

    running = Decimal("0")
    entries: list[StatementEntry] = []
    for e in events:
        running = running + Decimal(str(e["debit"])) - Decimal(str(e["credit"]))
        entries.append(
            StatementEntry(
                date=e["date"],
                type=e["type"],
                reference=e["reference"],
                description=e["description"],
                debit=e["debit"],
                credit=e["credit"],
                running_balance=float(running),
                order_id=e.get("order_id"),
                order_status=e.get("order_status"),
                bill_id=e.get("bill_id"),
                bill_no=e.get("bill_no"),
            )
        )

    outstanding = total_billed - total_paid
    return CustomerStatementResponse(
        customer_id=customer_id,
        customer_name=cust.name,
        phone=cust.phone,
        company_name=cust.company_name,
        total_orders=len(orders),
        total_billed=float(total_billed),
        total_paid=float(total_paid),
        outstanding=float(outstanding),
        statement_date=datetime.now(tz=timezone.utc),
        entries=entries,
    )


# ── Statement endpoints ────────────────────────────────────────────────────────

@router.get(
    "/{customer_id}/statement",
    response_model=CustomerStatementResponse,
    dependencies=[Depends(require_admin)],
)
def get_customer_statement(
    customer_id: int,
    db: Session = Depends(get_db),
    filter: Optional[str] = Query(default="all", alias="filter"),
) -> CustomerStatementResponse:
    return _build_statement(customer_id, db, entry_filter=filter or "all")


@router.get("/{customer_id}/statement/pdf")
def get_customer_statement_pdf(
    customer_id: int,
    db: Session = Depends(get_db),
    x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key"),
    api_key: Optional[str] = Query(None, description="Admin key as query param for browser downloads"),
) -> Response:
    from app.config import get_settings
    expected = (get_settings().admin_api_key or "").strip()
    provided = (x_admin_key or api_key or "").strip()
    if not expected or provided != expected:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid admin key")
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    stmt = _build_statement(customer_id, db)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                            topMargin=2 * cm, bottomMargin=2 * cm)
    styles = getSampleStyleSheet()
    story = []

    title = f"Statement of Account — {stmt.customer_name}"
    story.append(Paragraph(title, styles["Title"]))
    story.append(Spacer(1, 0.3 * cm))

    meta_lines = [
        f"<b>Phone:</b> {stmt.phone}",
        f"<b>Company:</b> {stmt.company_name or '—'}",
        f"<b>Statement Date:</b> {stmt.statement_date.strftime('%d %b %Y')}",
    ]
    for ml in meta_lines:
        story.append(Paragraph(ml, styles["Normal"]))
    story.append(Spacer(1, 0.5 * cm))

    headers = ["Date", "Type", "Description", "Debit", "Credit", "Balance"]
    table_data = [headers]
    for e in stmt.entries:
        table_data.append([
            e.date.strftime("%d %b %Y"),
            e.type.capitalize(),
            e.description,
            f"{e.debit:,.2f}" if e.debit else "—",
            f"{e.credit:,.2f}" if e.credit else "—",
            f"{e.running_balance:,.2f}",
        ])

    col_widths = [2.5 * cm, 2 * cm, 7 * cm, 2.5 * cm, 2.5 * cm, 2.5 * cm]
    tbl = Table(table_data, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2563EB")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
            ("ALIGN", (0, 0), (2, -1), "LEFT"),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 1), (-1, -1), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F1F5F9")]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ])
    )
    story.append(tbl)
    story.append(Spacer(1, 0.8 * cm))

    outstanding_line = (
        f"<b>Outstanding Balance: {stmt.outstanding:,.2f}</b>  |  "
        f"Total Billed: {stmt.total_billed:,.2f}  |  "
        f"Total Paid: {stmt.total_paid:,.2f}"
    )
    story.append(Paragraph(outstanding_line, styles["Normal"]))

    doc.build(story)
    pdf_bytes = buf.getvalue()
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=statement_{customer_id}.pdf"},
    )


# ── Stats endpoint ─────────────────────────────────────────────────────────────

@router.get(
    "/{customer_id}/stats",
    response_model=CustomerStats,
    dependencies=[Depends(require_admin)],
)
def get_customer_stats(
    customer_id: int,
    db: Session = Depends(get_db),
) -> CustomerStats:
    cust = db.get(Customer, customer_id)
    if cust is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="customer not found")

    orders = (
        db.query(CustomerOrder)
        .filter(
            CustomerOrder.customer_id == customer_id,
            CustomerOrder.status != "cancelled",
        )
        .all()
    )
    total_orders = len(orders)
    total_billed = float(sum(Decimal(str(o.total_amount)) for o in orders))

    # invoice_count = orders that have a customer bill (billed/shipped)
    from app.models.customer_bill import CustomerBill
    order_ids = [o.id for o in orders]
    invoice_count = 0
    if order_ids:
        invoice_count = (
            db.query(CustomerBill)
            .filter(CustomerBill.customer_order_id.in_(order_ids), CustomerBill.bill_status != "cancelled")
            .count()
        )

    hot_score = round(invoice_count / max(1, total_orders) * 100, 2)

    return CustomerStats(
        customer_id=customer_id,
        total_orders=total_orders,
        total_billed=total_billed,
        invoice_count=invoice_count,
        hot_score=hot_score,
    )
