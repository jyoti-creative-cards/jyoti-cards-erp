from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db, legacy_active_value, sql_is_active_true
from app.deps import require_admin
from app.integrations.whatsapp.client import send_account_creation, _e164 as normalize_whatsapp_e164
from app.models.customer import Customer
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
    route_id: Optional[int] = Query(None),
    city_id: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
) -> List[CustomerPublic]:
    q = db.query(Customer)
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

    existing = db.query(Customer).filter(Customer.phone == phone).one_or_none()
    if existing is not None and legacy_active_value(existing.is_active):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="phone already registered",
        )

    if existing is not None:
        # Same phone on a soft-deleted row: recycle it so UNIQUE(phone) is not violated.
        existing.name = body.name.strip()
        existing.password_hash = hash_password(body.password)
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
            body.password,
        )
        return existing

    row = Customer(
        name=body.name.strip(),
        phone=phone,
        password_hash=hash_password(body.password),
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
        body.password,
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


@router.delete("/{customer_id}", dependencies=[Depends(require_admin)])
def deactivate_customer(customer_id: int, db: Session = Depends(get_db)) -> dict:
    """Soft-delete: sets is_active=False. Hard history preserved."""
    row = db.get(Customer, customer_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="customer not found")
    row.is_active = False
    db.add(row)
    db.commit()
    return {"ok": True, "id": customer_id, "deactivated": True}
