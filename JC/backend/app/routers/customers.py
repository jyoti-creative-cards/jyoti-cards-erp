from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, text
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
from app.services.passwords import generate_portal_password, hash_password

router = APIRouter(prefix="/customers", tags=["customers"])
logger = logging.getLogger("jc.customers")


def _normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D+", "", (raw or "").strip())
    if len(digits) != 10:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="phone must be 10 digits")
    return digits


def _row_to_public(
    row: Customer,
    *,
    city_name: Optional[str],
    route_name: Optional[str],
    opening_amount=None,
    opening_as_on=None,
    history: Optional[list] = None,
    outstanding: Optional[Decimal] = None,
) -> CustomerPublic:
    # available_credit: only meaningful when a real (non-null, non-zero) limit is set
    if row.credit_limit is not None and row.credit_limit > Decimal("0") and outstanding is not None:
        available: Optional[Decimal] = row.credit_limit - outstanding
    elif row.credit_limit is not None and row.credit_limit == Decimal("0") and outstanding is not None:
        # track-only (limit=0): available = 0 - outstanding (informational, can be negative)
        available = Decimal("0") - outstanding
    else:
        available = None
    return CustomerPublic(
        id=row.id,
        business_name=row.business_name,
        person_name=row.person_name,
        phone=row.phone,
        secondary_phone=row.secondary_phone,
        alias=row.alias,
        address=row.address,
        additional_details=getattr(row, "additional_details", None),
        city_id=row.city_id,
        route_id=row.route_id,
        city_name=city_name,
        route_name=route_name,
        credit_limit=format(row.credit_limit, "f") if row.credit_limit is not None else None,
        credit_override=row.credit_override,
        gst_number=row.gst_number,
        is_active=row.is_active,
        opening_balance_due=format(opening_amount, "f") if opening_amount is not None else None,
        opening_balance_as_on=opening_as_on.isoformat() if opening_as_on else None,
        outstanding_balance=format(outstanding, "f") if outstanding is not None else None,
        available_credit=format(available, "f") if available is not None else None,
        party_number=getattr(row, "party_number", None),
        marker_1=getattr(row, "marker_1", None),
        marker_2=getattr(row, "marker_2", None),
        payment_type=getattr(row, "payment_type", None),
        notes=getattr(row, "notes", None),
        created_at=row.created_at,
        updated_at=row.updated_at,
        deleted_at=row.deleted_at,
        change_history=history or [],
    )


def _to_public(row: Customer, db: Session, include_history: bool = False) -> CustomerPublic:
    return _to_public_many([row], db, include_history=include_history)[0]


def _to_public_many(
    rows: List[Customer],
    db: Session,
    *,
    include_history: bool = False,
) -> List[CustomerPublic]:
    """Batch city/route/opening lookups — avoids N+1 on list endpoints."""
    if not rows:
        return []

    city_ids = {r.city_id for r in rows if r.city_id}
    route_ids = {r.route_id for r in rows if r.route_id}
    cities = {
        c.id: c.name
        for c in (db.query(City).filter(City.id.in_(city_ids)).all() if city_ids else [])
    }
    routes = {
        r.id: r.name
        for r in (db.query(Route).filter(Route.id.in_(route_ids)).all() if route_ids else [])
    }

    from app.models.accounts_receivable import ArLedgerEntry
    from app.services.ar_ledger import batch_customer_outstanding

    cust_ids = [r.id for r in rows]
    openings: dict[int, ArLedgerEntry] = {}
    if cust_ids:
        for e in (
            db.query(ArLedgerEntry)
            .filter(
                ArLedgerEntry.customer_id.in_(cust_ids),
                ArLedgerEntry.entry_type == "opening_balance",
            )
            .all()
        ):
            prev = openings.get(e.customer_id)
            if prev is None or e.id > prev.id:
                openings[e.customer_id] = e

    # Batch-fetch outstanding balances for all customers in one query
    try:
        outstanding_map: dict[int, Decimal] = batch_customer_outstanding(db, cust_ids)
    except Exception:
        outstanding_map = {}

    out: List[CustomerPublic] = []
    for row in rows:
        history = []
        outstanding_val: Optional[Decimal] = outstanding_map.get(row.id)
        if include_history:
            history = [
                {
                    "change_summary": h.change_summary,
                    "valid_from": h.valid_from.isoformat(),
                    "snapshot_json": h.snapshot_json,
                }
                for h in list_entity_history(db, "customer", row.id)
            ]
            if outstanding_val is None:
                # fall back to per-customer totals on detail view
                from app.services.ar_ledger import customer_ar_totals
                try:
                    outstanding_val = customer_ar_totals(db, row.id)["outstanding"]
                except Exception:
                    outstanding_val = None
        opening = openings.get(row.id)
        out.append(
            _row_to_public(
                row,
                city_name=cities.get(row.city_id) if row.city_id else None,
                route_name=routes.get(row.route_id) if row.route_id else None,
                opening_amount=opening.amount if opening else None,
                opening_as_on=opening.value_date if opening else None,
                history=history,
                outstanding=outstanding_val,
            )
        )
    return out


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
    status: Optional[str] = Query(None, description="active (default) | inactive | deleted"),
    include_inactive: bool = Query(False),  # legacy, kept for compatibility
) -> List[CustomerPublic]:
    q = db.query(Customer)
    if status == "inactive":
        q = q.filter(Customer.is_active.is_(False), Customer.deleted_at.is_(None))
    elif status == "deleted":
        q = q.filter(Customer.deleted_at.isnot(None))
    elif status == "all":
        pass  # no filter
    else:
        # default: active only (status="active" or no status)
        # legacy include_inactive=true returns active+inactive but never deleted
        if include_inactive:
            q = q.filter(Customer.deleted_at.is_(None))
        else:
            q = q.filter(Customer.is_active.is_(True), Customer.deleted_at.is_(None))
    if city_id is not None:
        q = q.filter(Customer.city_id == city_id)
    if route_id is not None:
        q = q.filter(Customer.route_id == route_id)
    if search:
        from app.services.token_search import sort_parties_by_search, token_match

        # Join city so tokens like "anjad" match city as well as name
        q = q.outerjoin(City, Customer.city_id == City.id)
        clause = token_match(
            search,
            [
                Customer.business_name,
                Customer.person_name,
                Customer.phone,
                Customer.alias,
                Customer.address,
                City.name,
            ],
        )
        if clause is not None:
            q = q.filter(clause)
        rows = q.all()
        city_ids = {r.city_id for r in rows if r.city_id}
        city_lookup = {
            c.id: c.name
            for c in (db.query(City).filter(City.id.in_(city_ids)).all() if city_ids else [])
        }
        rows = sort_parties_by_search(rows, search, city_lookup=city_lookup)
        return _to_public_many(rows, db)
    from sqlalchemy import nulls_last
    rows = q.order_by(nulls_last(Customer.party_number.asc()), Customer.business_name.asc()).all()
    return _to_public_many(rows, db)


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
    if existing is not None and existing.is_active and existing.deleted_at is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="phone already registered")

    plain = generate_portal_password()
    route_id = _route_from_city(db, body.city_id)
    display_name = (body.person_name or "").strip() or body.business_name.strip()

    # Soft-deleted / inactive row still holds unique phone — recycle it.
    if existing is not None:
        existing.business_name = body.business_name.strip()
        existing.person_name = (body.person_name.strip() if body.person_name else None)
        existing.password_hash = hash_password(plain)
        existing.secondary_phone = sec_norm
        existing.alias = (body.alias.strip() if body.alias else None)
        existing.address = (body.address.strip() if body.address else None)
        existing.additional_details = (body.additional_details.strip() if body.additional_details else None)
        existing.city_id = body.city_id
        existing.route_id = route_id
        existing.credit_limit = Decimal(str(body.credit_limit)) if body.credit_limit is not None else None
        existing.credit_override = body.credit_override
        existing.gst_number = (body.gst_number.strip().upper() if body.gst_number else None)
        existing.is_active = True
        existing.deleted_at = None
        db.add(existing)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, detail="phone already registered") from None
        db.refresh(existing)
        if body.opening_balance_due and float(body.opening_balance_due) > 0:
            from app.services.ar_ledger import set_opening_balance
            from datetime import date as date_cls

            set_opening_balance(
                db,
                customer_id=existing.id,
                amount=Decimal(str(body.opening_balance_due)),
                as_on=body.opening_balance_as_on or date_cls.today(),
                actor_type=auth.actor_type,
                actor_id=auth.actor_id,
                actor_name=auth.actor_name,
            )
        wa_ok, wa_err = _send_whatsapp(display_name, existing.phone, plain)
        log_from_auth(db, auth, action="create", entity_type="customer", entity_id=existing.id, entity_label=existing.business_name)
        db.commit()
        pub = _to_public(existing, db)
        return CustomerCreateResponse(
            **pub.model_dump(), whatsapp_sent=wa_ok, whatsapp_error=wa_err, portal_password=plain
        )

    row = Customer(
        business_name=body.business_name.strip(),
        person_name=(body.person_name.strip() if body.person_name else None),
        phone=phone,
        password_hash=hash_password(plain),
        secondary_phone=sec_norm,
        alias=(body.alias.strip() if body.alias else None),
        address=(body.address.strip() if body.address else None),
        additional_details=(body.additional_details.strip() if body.additional_details else None),
        city_id=body.city_id,
        route_id=route_id,
        credit_limit=Decimal(str(body.credit_limit)) if body.credit_limit is not None else None,
        credit_override=body.credit_override,
        gst_number=(body.gst_number.strip().upper() if body.gst_number else None),
        party_number=body.party_number if body.party_number is not None else (
            (db.execute(text("SELECT COALESCE(MAX(party_number), 0) + 1 FROM jc_customers")).scalar())
        ),
        marker_1=(body.marker_1.strip() if body.marker_1 else None),
        marker_2=(body.marker_2.strip() if body.marker_2 else None),
        payment_type=(body.payment_type.strip().upper() if body.payment_type else None),
        notes=(body.notes.strip() if body.notes else None),
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail="phone already registered") from None
    db.refresh(row)

    if body.opening_balance_due and float(body.opening_balance_due) > 0:
        from app.services.ar_ledger import set_opening_balance
        from datetime import date as date_cls

        set_opening_balance(
            db,
            customer_id=row.id,
            amount=Decimal(str(body.opening_balance_due)),
            as_on=body.opening_balance_as_on or date_cls.today(),
            actor_type=auth.actor_type,
            actor_id=auth.actor_id,
            actor_name=auth.actor_name,
        )
    wa_ok, wa_err = _send_whatsapp(display_name, row.phone, plain)
    log_from_auth(db, auth, action="create", entity_type="customer", entity_id=row.id, entity_label=row.business_name)
    db.commit()
    pub = _to_public(row, db)
    return CustomerCreateResponse(
        **pub.model_dump(), whatsapp_sent=wa_ok, whatsapp_error=wa_err, portal_password=plain
    )


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
        if clash and clash.deleted_at is None:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="phone already registered to another customer")
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

    for field in ("business_name", "person_name", "alias", "address", "gst_number", "additional_details",
                  "marker_1", "marker_2", "payment_type", "notes"):
        if field in data:
            val = data[field]
            if field == "gst_number":
                row.gst_number = val.strip().upper() if val else None
            elif field == "payment_type":
                row.payment_type = val.strip().upper() if val else None
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

    # TEMP: opening balance editable on customer save
    if "opening_balance_due" in data or "opening_balance_as_on" in data:
        from datetime import date as date_cls
        from app.services.ar_ledger import get_opening_balance, set_opening_balance

        amt = data.pop("opening_balance_due", None)
        as_on = data.pop("opening_balance_as_on", None)
        if amt is None:
            existing = get_opening_balance(db, customer_id)
            amt = existing.amount if existing else 0
        if as_on is None:
            as_on = date_cls.today()
        set_opening_balance(
            db,
            customer_id=customer_id,
            amount=Decimal(str(amt or 0)),
            as_on=as_on,
            actor_type=auth.actor_type,
            actor_id=auth.actor_id,
            actor_name=auth.actor_name,
        )

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
    if not row or row.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="customer not found")
    row.is_active = False
    row.deleted_at = datetime.now(timezone.utc)
    log_from_auth(db, auth, action="delete", entity_type="customer", entity_id=row.id, entity_label=row.business_name)
    db.commit()


@router.post("/{customer_id}/restore", response_model=CustomerPublic, dependencies=[Depends(require_permission("customers.write"))])
def restore_customer(customer_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permission("customers.write"))) -> CustomerPublic:
    """Restore a soft-deleted customer from recycle bin → active."""
    row = db.get(Customer, customer_id)
    if not row or row.deleted_at is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="customer not in recycle bin")
    row.is_active = True
    row.deleted_at = None
    log_from_auth(db, auth, action="restore", entity_type="customer", entity_id=row.id, entity_label=row.business_name)
    db.commit()
    db.refresh(row)
    return _to_public(row, db)


@router.post("/{customer_id}/reset-password", dependencies=[Depends(require_permission("customers.write"))])
def reset_password(customer_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(Customer, customer_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="customer not found")

    plain = generate_portal_password()
    row.password_hash = hash_password(plain)
    db.add(row)
    db.commit()

    display_name = row.person_name or row.business_name
    wa_ok, wa_err = _send_whatsapp(display_name, row.phone, plain)
    return {
        "ok": True,
        "whatsapp_sent": wa_ok,
        "whatsapp_error": wa_err,
        "portal_password": plain,
        "message": "password reset" + (" and WhatsApp sent" if wa_ok else f" but WhatsApp failed: {wa_err}"),
    }


@router.post("/{customer_id}/resend-whatsapp", dependencies=[Depends(require_permission("customers.write"))])
def resend_whatsapp(customer_id: int, db: Session = Depends(get_db)) -> dict:
    """New unique password + WhatsApp (cannot resend old plain password)."""
    row = db.get(Customer, customer_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="customer not found")
    plain = generate_portal_password()
    row.password_hash = hash_password(plain)
    db.add(row)
    db.commit()
    display_name = row.person_name or row.business_name
    wa_ok, wa_err = _send_whatsapp(display_name, row.phone, plain)
    return {
        "ok": wa_ok,
        "whatsapp_sent": wa_ok,
        "whatsapp_error": wa_err,
        "portal_password": plain,
    }
