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

from app.routers.customers.router import router
from app.routers.customers.support import _to_public, _to_public_many

@router.get("", response_model=List[CustomerPublic])
def list_customers(
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("customers.read")),
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

        # Strip leading # so "#123" searches party_number 123
        search_clean = search.lstrip("#").strip()

        # Join city so tokens like "anjad" match city as well as name
        q = q.outerjoin(City, Customer.city_id == City.id)
        clause = token_match(
            search_clean,
            [
                Customer.business_name,
                Customer.person_name,
                Customer.phone,
                Customer.secondary_phone,
                Customer.alias,
                City.name,
            ],
            exact_int_columns=[Customer.party_number],
        )
        # Address is not searched: many parties share landmark text ("shop",
        # a market name), which made unrelated parties show up for any query.
        # No tokens (e.g. "#" only) must return nobody, not the full list.
        if clause is None:
            return []
        rows = q.filter(clause).all()
        city_ids = {r.city_id for r in rows if r.city_id}
        city_lookup = {
            c.id: c.name
            for c in (db.query(City).filter(City.id.in_(city_ids)).all() if city_ids else [])
        }
        rows = sort_parties_by_search(rows, search_clean, city_lookup=city_lookup)
        return _to_public_many(rows, db, auth=auth)
    from sqlalchemy import nulls_last
    rows = q.order_by(nulls_last(Customer.party_number.asc()), Customer.business_name.asc()).all()
    return _to_public_many(rows, db, auth=auth)

@router.get("/quick-search")
def quick_search_customers(
    q: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    # Same reasoning as vendors.py's quick_search_vendors: finance.js's "Record
    # customer payment" quick-entry button needs a name/city lookup, but the
    # documented finance.write-only "entry-only accountant" role has no
    # customers.read — the full GET /customers list also leaks AR outstanding
    # balance/credit-limit fields that role is explicitly meant not to see.
    auth: AuthContext = Depends(require_any_permission("customers.read", "finance.write")),
) -> List[dict]:
    from app.services.token_search import sort_parties_by_search, token_match

    search_clean = q.lstrip("#").strip()
    query = db.query(Customer).filter(Customer.is_active.is_(True), Customer.deleted_at.is_(None))
    query = query.outerjoin(City, Customer.city_id == City.id)
    clause = token_match(
        search_clean,
        [
            Customer.business_name,
            Customer.person_name,
            Customer.phone,
            Customer.secondary_phone,
            Customer.alias,
            City.name,
        ],
        exact_int_columns=[Customer.party_number],
    )
    if clause is None:
        return []
    # Rank every real match, then keep 8. A limit before ranking kept the
    # oldest rows and dropped the party that actually matched the typed name.
    rows = query.filter(clause).all()
    city_ids = sorted({r.city_id for r in rows if r.city_id})
    cities = {c.id: c.name for c in (db.query(City).filter(City.id.in_(city_ids)).all() if city_ids else [])}
    rows = sort_parties_by_search(rows, search_clean, city_lookup=cities)
    return [
        {
            "id": r.id,
            "business_name": r.business_name,
            "city_name": cities.get(r.city_id),
            "phone": r.phone,
            "party_number": r.party_number,
            "person_name": r.person_name,
            "alias": r.alias,
            "marker_1": r.marker_1,
            "marker_2": r.marker_2,
            "payment_type": r.payment_type,
        }
        for r in rows[:8]
    ]

def search_sticker_parties(db: Session, q: str) -> list[Customer]:
    """Party-number prefix only. A typed 3 must not match a name or a phone."""
    text = (q or "").strip()
    if not text.isdigit():
        return []
    number = sa_cast(Customer.party_number, SAString)
    return (
        db.query(Customer)
        .filter(
            Customer.is_active.is_(True),
            Customer.deleted_at.is_(None),
            Customer.party_number.isnot(None),
            number.like(f"{text}%"),
        )
        .order_by(Customer.party_number.asc())
        .limit(8)
        .all()
    )


@router.get("/sticker-search")
def sticker_party_search(
    q: str = Query("", max_length=20),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_any_permission("stickers.print", "customers.read", "finance.write")),
) -> list[dict]:
    rows = search_sticker_parties(db, q if isinstance(q, str) else "")
    city_ids = sorted({r.city_id for r in rows if r.city_id})
    cities = {c.id: c.name for c in (db.query(City).filter(City.id.in_(city_ids)).all() if city_ids else [])}
    return [
        {
            "id": r.id,
            "business_name": r.business_name,
            "city_name": cities.get(r.city_id),
            "phone": r.phone,
            "party_number": r.party_number,
        }
        for r in rows
    ]


@router.get("/sticker-prints")
def list_customer_sticker_prints(
    q: str = Query("", max_length=80),
    limit: int = Query(40, ge=1, le=100),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_any_permission("stickers.print", "customers.read", "finance.write")),
) -> list[dict]:
    from app.services.sticker_labels import list_sticker_prints, print_payload

    text = q if isinstance(q, str) else ""
    cap = limit if isinstance(limit, int) else 40
    return [print_payload(row) for row in list_sticker_prints(db, text, cap)]

@router.post("/{customer_id}/sticker-prints")
def post_customer_sticker_print(
    customer_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_any_permission("stickers.print", "customers.read", "finance.write")),
) -> dict:
    """Record one A5 print and return the Hindi lines plus the English print time."""
    from app.services.sticker_labels import print_payload, record_sticker_print

    row = db.get(Customer, customer_id)
    if row is None or row.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="customer not found")
    city_name = None
    if row.city_id:
        city = db.get(City, row.city_id)
        if city is not None and city.deleted_at is None:
            city_name = city.name
    saved = record_sticker_print(db, row, city_name, auth.actor_name)
    return print_payload(saved)

@router.get("/{customer_id}/sticker")
def get_customer_sticker(
    customer_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_any_permission("stickers.print", "customers.read", "finance.write")),
) -> dict:
    """Hindi name and city for the A5 sticker. The phone stays as stored."""
    from app.services.sticker_labels import label_for_customer

    row = db.get(Customer, customer_id)
    if row is None or row.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="customer not found")
    city_name = None
    if row.city_id:
        city = db.get(City, row.city_id)
        if city is not None and city.deleted_at is None:
            city_name = city.name
    label = label_for_customer(db, row, city_name)
    return {
        "customer_id": row.id,
        "name_hi": label.name_hi,
        "city_hi": label.city_hi,
        "phone": row.phone,
    }

@router.get("/{customer_id}", response_model=CustomerPublic)
def get_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("customers.read")),
) -> CustomerPublic:
    row = db.get(Customer, customer_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="customer not found")
    return _to_public(row, db, include_history=True, auth=auth)

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
