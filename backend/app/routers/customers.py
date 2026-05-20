from __future__ import annotations

from typing import List

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


def _send_wa_safe(name: str, phone: str, plain: str) -> None:
    try:
        send_account_creation(phone=phone, customer_name=name, login_phone=phone, password=plain)
    except Exception as ex:
        print("WhatsApp send failed:", ex)


@router.get("", response_model=List[CustomerPublic], dependencies=[Depends(require_admin)])
def list_customers(
    db: Session = Depends(get_db),
    include_inactive: bool = Query(False),
) -> List[Customer]:
    q = db.query(Customer)
    if not include_inactive:
        q = q.filter(sql_is_active_true(Customer.is_active))
    return q.order_by(Customer.id.asc()).all()


@router.get("/{customer_id}", response_model=CustomerPublic, dependencies=[Depends(require_admin)])
def get_customer(customer_id: int, db: Session = Depends(get_db)) -> Customer:
    row = db.get(Customer, customer_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="customer not found")
    return row


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
        address=(body.address.strip() if body.address else None),
        secondary_phone=sec_norm,
        city=(body.city.strip() if body.city else None),
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
    return row


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
    return row


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
