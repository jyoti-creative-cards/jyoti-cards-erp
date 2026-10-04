from __future__ import annotations
import logging
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, text
from sqlalchemy import String as SAString
from sqlalchemy.sql.expression import cast as sa_cast
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.config import get_settings
from app.db.session import get_db
from app.deps import AuthContext, get_auth_context, require_any_permission, require_permission
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
from app.services import response_cache
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
    show_ar: bool = True,
) -> CustomerPublic:
    # available_credit: only meaningful when a real (non-null, non-zero) limit is set
    if row.credit_limit is not None and row.credit_limit > Decimal("0") and outstanding is not None:
        available: Optional[Decimal] = row.credit_limit - outstanding
    elif row.credit_limit is not None and row.credit_limit == Decimal("0") and outstanding is not None:
        # track-only (limit=0): available = 0 - outstanding (informational, can be negative)
        available = Decimal("0") - outstanding
    else:
        available = None
    # ar.read gates AR outstanding/credit figures — there's a dedicated permission
    # specifically so only accountant-type staff see "customer outstanding, ledger &
    # statements" (permissions.py). Without this, any staffer with plain
    # customers.read (needed just to browse the directory) or any order-taking staffer
    # via the offline-order picker could see every customer's exact dues.
    if not show_ar:
        outstanding = None
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
        credit_limit=format(row.credit_limit, "f") if (show_ar and row.credit_limit is not None) else None,
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

def _to_public(row: Customer, db: Session, include_history: bool = False, auth: Optional[AuthContext] = None) -> CustomerPublic:
    return _to_public_many([row], db, include_history=include_history, auth=auth)[0]

def _to_public_many(
    rows: List[Customer],
    db: Session,
    *,
    include_history: bool = False,
    auth: Optional[AuthContext] = None,
) -> List[CustomerPublic]:
    """Batch city/route/opening lookups — avoids N+1 on list endpoints."""
    if not rows:
        return []
    # The customer directory stays blank on dues. Opening one customer
    # (include_history) shows that party's own figures so staff can work the bill.
    show_ar = bool(
        auth and (
            auth.is_admin
            or auth.has("ar.read")
            or auth.has("ar.write")
            or include_history
        )
    )

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
                show_ar=show_ar,
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
