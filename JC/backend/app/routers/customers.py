from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_db
from app.deps import AuthContext, get_auth_context, require_permission
from app.integrations.whatsapp.client import send_account_creation
from app.models.city import City
from app.models.customer import Customer
from app.models.route import Route
from app.schemas.customer import CustomerCreate, CustomerCreateResponse, CustomerPublic, CustomerUpdate
from app.schemas.ledger import EntityLedgerResponse
from app.services.soft_delete import apply_is_active
from app.services.activity import log_from_auth
from app.services.ledger import build_customer_ledger
from app.services.history import TRACKED_FIELDS, diff_summary, list_entity_history, record_entity_history, row_snapshot
from app.services.passwords import hash_password

router = APIRouter(prefix="/customers", tags=["customers"])
logger = logging.getLogger("jc.customers")


def _normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D+", "", (raw or "").strip())
    if len(digits) != 10:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="phone must be 10 digits")
    return digits


def _to_public(row: Customer, db: Session, include_history: bool = False) -> CustomerPublic:
    city_name = None
    route_name = None
    if row.city_id:
        city = db.get(City, row.city_id)
        city_name = city.name if city else None
    if row.route_id:
        route = db.get(Route, row.route_id)
        route_name = route.name if route else None
    history = []
    if include_history:
        history = [{"change_summary": h.change_summary, "valid_from": h.valid_from.isoformat(), "snapshot_json": h.snapshot_json} for h in list_entity_history(db, "customer", row.id)]
    return CustomerPublic(
        id=row.id,
        business_name=row.business_name,
        person_name=row.person_name,
        phone=row.phone,
        secondary_phone=row.secondary_phone,
        alias=row.alias,
        address=row.address,
        city_id=row.city_id,
        route_id=row.route_id,
        city_name=city_name,
        route_name=route_name,
        credit_limit=format(row.credit_limit, "f") if row.credit_limit is not None else None,
        credit_override=row.credit_override,
        gst_number=row.gst_number,
        is_active=row.is_active,
        created_at=row.created_at,
        updated_at=row.updated_at,
        deleted_at=row.deleted_at,
        change_history=history,
    )


def _send_whatsapp(name: str, phone: str, plain: str) -> tuple[bool, Optional[str]]:
    s = get_settings()
    suffix = (s.customer_portal_url_button_suffix or "").strip()
    result = send_account_creation(
        phone=phone,
        customer_name=name,
        login_phone=phone,
        password=plain,
        button_suffix=suffix,
    )
    if result.get("ok"):
        return True, None
    err = str(result.get("error") or "unknown error")
    logger.error("WhatsApp failed for %s: %s", phone, err)
    return False, err


def _route_from_city(db: Session, city_id: Optional[int]) -> Optional[int]:
    if not city_id:
        return None
    city = db.get(City, city_id)
    if city is None or not city.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="city not found")
    return city.route_id


@router.get("", response_model=List[CustomerPublic], dependencies=[Depends(require_permission("customers.read"))])
def list_customers(
    db: Session = Depends(get_db),
    search: Optional[str] = Query(None),
    city_id: Optional[int] = Query(None),
    route_id: Optional[int] = Query(None),
    include_inactive: bool = Query(False),
) -> List[CustomerPublic]:
    q = db.query(Customer)
    if not include_inactive:
        q = q.filter(Customer.is_active.is_(True))
    if city_id is not None:
        q = q.filter(Customer.city_id == city_id)
    if route_id is not None:
        q = q.filter(Customer.route_id == route_id)
    if search:
        s = f"%{search.lower()}%"
        q = q.filter(or_(
            func.lower(Customer.business_name).like(s),
            func.lower(Customer.person_name).like(s),
            func.lower(Customer.phone).like(s),
            func.lower(Customer.alias).like(s),
        ))
    rows = q.order_by(Customer.id.desc()).all()
    return [_to_public(r, db) for r in rows]


@router.get("/{customer_id}", response_model=CustomerPublic, dependencies=[Depends(require_permission("customers.read"))])
def get_customer(customer_id: int, db: Session = Depends(get_db)) -> CustomerPublic:
    row = db.get(Customer, customer_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="customer not found")
    return _to_public(row, db, include_history=True)


@router.get("/{customer_id}/ledger", response_model=EntityLedgerResponse, dependencies=[Depends(require_permission("customers.read"))])
def get_customer_ledger(
    customer_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
) -> EntityLedgerResponse:
    row = db.get(Customer, customer_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="customer not found")
    items = build_customer_ledger(db, customer_id, show_actor=auth.is_admin)
    return EntityLedgerResponse(items=items, total=len(items))


@router.post("", response_model=CustomerCreateResponse, status_code=201, dependencies=[Depends(require_permission("customers.write"))])
def create_customer(body: CustomerCreate, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permission("customers.write"))) -> CustomerCreateResponse:
    phone = _normalize_phone(body.phone)
    sec = (body.secondary_phone or "").strip()
    sec_norm = _normalize_phone(sec) if sec else None

    existing = db.query(Customer).filter(Customer.phone == phone).one_or_none()
    if existing is not None and existing.is_active:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="phone already registered")

    plain = phone[-4:]
    route_id = _route_from_city(db, body.city_id)
    display_name = (body.person_name or "").strip() or body.business_name.strip()

    row = Customer(
        business_name=body.business_name.strip(),
        person_name=(body.person_name.strip() if body.person_name else None),
        phone=phone,
        password_hash=hash_password(plain),
        secondary_phone=sec_norm,
        alias=(body.alias.strip() if body.alias else None),
        address=(body.address.strip() if body.address else None),
        city_id=body.city_id,
        route_id=route_id,
        credit_limit=Decimal(str(body.credit_limit)) if body.credit_limit is not None else None,
        credit_override=body.credit_override,
        gst_number=(body.gst_number.strip().upper() if body.gst_number else None),
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail="phone already registered") from None
    db.refresh(row)

    wa_ok, wa_err = _send_whatsapp(display_name, row.phone, plain)
    log_from_auth(db, auth, action="create", entity_type="customer", entity_id=row.id, entity_label=row.business_name)
    db.commit()
    pub = _to_public(row, db)
    return CustomerCreateResponse(**pub.model_dump(), whatsapp_sent=wa_ok, whatsapp_error=wa_err)


@router.patch("/{customer_id}", response_model=CustomerPublic, dependencies=[Depends(require_permission("customers.write"))])
def update_customer(customer_id: int, body: CustomerUpdate, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permission("customers.write"))) -> CustomerPublic:
    row = db.get(Customer, customer_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="customer not found")

    data = body.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="no fields to update")

    before = row_snapshot(row, TRACKED_FIELDS["customer"])

    if "phone" in data and data["phone"] is not None:
        phone = _normalize_phone(data["phone"])
        clash = db.query(Customer).filter(Customer.phone == phone, Customer.id != customer_id).one_or_none()
        if clash and clash.is_active:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="phone already registered")
        row.phone = phone
        del data["phone"]

    if "secondary_phone" in data:
        sec = (data["secondary_phone"] or "").strip()
        row.secondary_phone = _normalize_phone(sec) if sec else None
        del data["secondary_phone"]

    if "city_id" in data:
        row.city_id = data["city_id"]
        row.route_id = _route_from_city(db, data["city_id"])
        del data["city_id"]

    for field in ("business_name", "person_name", "alias", "address", "gst_number"):
        if field in data:
            val = data[field]
            if field == "gst_number":
                row.gst_number = val.strip().upper() if val else None
            elif field in ("business_name",):
                setattr(row, field, val.strip() if val else val)
            else:
                setattr(row, field, val.strip() if val else None)
            del data[field]

    if "credit_limit" in data:
        row.credit_limit = Decimal(str(data["credit_limit"])) if data["credit_limit"] is not None else None
        del data["credit_limit"]

    if "credit_override" in data and data["credit_override"] is not None:
        row.credit_override = data["credit_override"]
        del data["credit_override"]

    if "is_active" in data and data["is_active"] is not None:
        apply_is_active(row, data["is_active"])
        del data["is_active"]

    after = row_snapshot(row, TRACKED_FIELDS["customer"])
    summary = diff_summary("customer", before, after)
    if summary != "updated":
        record_entity_history(db, "customer", row.id, before, summary)

    db.add(row)
    log_from_auth(db, auth, action="update", entity_type="customer", entity_id=row.id, entity_label=row.business_name, detail=summary)
    db.commit()
    db.refresh(row)
    return _to_public(row, db)


@router.delete("/{customer_id}", status_code=204, dependencies=[Depends(require_permission("customers.write"))])
def delete_customer(customer_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permission("customers.write"))) -> None:
    row = db.get(Customer, customer_id)
    if not row or not row.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="customer not found")
    row.is_active = False
    row.deleted_at = datetime.now(timezone.utc)
    log_from_auth(db, auth, action="delete", entity_type="customer", entity_id=row.id, entity_label=row.business_name)
    db.commit()


@router.post("/{customer_id}/reset-password", dependencies=[Depends(require_permission("customers.write"))])
def reset_password(customer_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(Customer, customer_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="customer not found")

    plain = row.phone[-4:]
    row.password_hash = hash_password(plain)
    db.add(row)
    db.commit()

    display_name = row.person_name or row.business_name
    wa_ok, wa_err = _send_whatsapp(display_name, row.phone, plain)
    return {
        "ok": True,
        "whatsapp_sent": wa_ok,
        "whatsapp_error": wa_err,
        "message": "password reset" + (" and WhatsApp sent" if wa_ok else f" but WhatsApp failed: {wa_err}"),
    }


@router.post("/{customer_id}/resend-whatsapp", dependencies=[Depends(require_permission("customers.write"))])
def resend_whatsapp(customer_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(Customer, customer_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="customer not found")
    plain = row.phone[-4:]
    display_name = row.person_name or row.business_name
    wa_ok, wa_err = _send_whatsapp(display_name, row.phone, plain)
    return {"ok": wa_ok, "whatsapp_sent": wa_ok, "whatsapp_error": wa_err}
