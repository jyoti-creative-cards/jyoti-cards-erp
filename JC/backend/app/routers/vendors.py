from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import AuthContext, get_auth_context, require_permission
from app.models.addon_product import AddonProduct
from app.models.catalog_product import CatalogProduct
from app.models.city import City
from app.models.vendor import Vendor
from app.schemas.ledger import EntityLedgerResponse
from app.schemas.vendor import VendorBillingTerms, VendorCreate, VendorPublic, VendorUpdate
from app.services.activity import log_from_auth
from app.services.ledger import build_vendor_ledger
from app.services.history import TRACKED_FIELDS, diff_summary, list_entity_history, record_entity_history, row_snapshot
from app.services.soft_delete import apply_is_active
from app.services.storage import rename_vendor_folder, update_image_keys_after_vendor_rename, vendor_folder_slug

router = APIRouter(prefix="/vendors", tags=["vendors"])


def _normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D+", "", (raw or "").strip())
    if len(digits) != 10:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="phone must be 10 digits")
    return digits


def _to_public(row: Vendor, db: Session, include_history: bool = False) -> VendorPublic:
    city_name = None
    if row.city_id:
        city = db.get(City, row.city_id)
        city_name = city.name if city else None
    history = []
    if include_history:
        history = [{"change_summary": h.change_summary, "valid_from": h.valid_from.isoformat(), "snapshot_json": h.snapshot_json} for h in list_entity_history(db, "vendor", row.id)]
    from app.services.ap_ledger import get_opening_balance

    opening = get_opening_balance(db, row.id)
    return VendorPublic(
        id=row.id,
        business_name=row.business_name,
        phone=row.phone,
        person_name=row.person_name,
        secondary_phone=row.secondary_phone,
        alias=row.alias,
        address=row.address,
        city_id=row.city_id,
        city_name=city_name,
        gst_number=row.gst_number,
        is_active=row.is_active,
        opening_balance_due=format(opening.amount, "f") if opening else None,
        opening_balance_as_on=opening.value_date.isoformat() if opening and opening.value_date else None,
        billing_terms=VendorBillingTerms(
            billing_pct=float(row.billing_pct), additional_charge=float(row.additional_charge),
            additional_charge_label=row.additional_charge_label, discount_pct=float(row.discount_pct),
            gst_included=row.gst_included, gst_rate_pct=float(row.gst_rate_pct), billing_notes=row.billing_notes,
        ),
        created_at=row.created_at,
        updated_at=row.updated_at,
        deleted_at=row.deleted_at,
        change_history=history,
    )


def _validate_city(db: Session, city_id: int) -> None:
    city = db.get(City, city_id)
    if city is None or not city.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="city not found")


@router.get("", response_model=List[VendorPublic], dependencies=[Depends(require_permission("vendors.read"))])
def list_vendors(
    db: Session = Depends(get_db),
    search: Optional[str] = Query(None),
    city_id: Optional[int] = Query(None),
) -> List[VendorPublic]:
    q = db.query(Vendor).filter(Vendor.is_active.is_(True), Vendor.deleted_at.is_(None))
    if city_id is not None:
        q = q.filter(Vendor.city_id == city_id)
    if search:
        from app.services.token_search import sort_parties_by_search, token_match

        q = q.outerjoin(City, Vendor.city_id == City.id)
        clause = token_match(
            search,
            [
                Vendor.business_name,
                Vendor.person_name,
                Vendor.phone,
                Vendor.alias,
                Vendor.address,
                City.name,
            ],
        )
        if clause is not None:
            q = q.filter(clause)
        rows = q.all()
        city_ids = sorted({r.city_id for r in rows if r.city_id})
        cities = {
            c.id: c.name
            for c in (db.query(City).filter(City.id.in_(city_ids)).all() if city_ids else [])
        }
        rows = sort_parties_by_search(rows, search, city_lookup=cities)
    else:
        rows = q.order_by(Vendor.id.desc()).all()
        city_ids = sorted({r.city_id for r in rows if r.city_id})
        cities = {
            c.id: c.name
            for c in (db.query(City).filter(City.id.in_(city_ids)).all() if city_ids else [])
        }
    out = []
    for r in rows:
        city_name = cities.get(r.city_id) if r.city_id else None
        out.append(
            VendorPublic(
                id=r.id,
                business_name=r.business_name,
                phone=r.phone,
                person_name=r.person_name,
                secondary_phone=r.secondary_phone,
                alias=r.alias,
                address=r.address,
                city_id=r.city_id,
                city_name=city_name,
                gst_number=r.gst_number,
                is_active=r.is_active,
                billing_terms=VendorBillingTerms(
                    billing_pct=float(r.billing_pct), additional_charge=float(r.additional_charge),
                    additional_charge_label=r.additional_charge_label, discount_pct=float(r.discount_pct),
                    gst_included=r.gst_included, gst_rate_pct=float(r.gst_rate_pct), billing_notes=r.billing_notes,
                ),
                created_at=r.created_at,
                updated_at=r.updated_at,
                deleted_at=r.deleted_at,
                change_history=[],
            )
        )
    return out


@router.get("/{vendor_id}", response_model=VendorPublic, dependencies=[Depends(require_permission("vendors.read"))])
def get_vendor(vendor_id: int, db: Session = Depends(get_db)) -> VendorPublic:
    row = db.get(Vendor, vendor_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor not found")
    return _to_public(row, db, include_history=True)


@router.get("/{vendor_id}/billing-terms", response_model=VendorBillingTerms, dependencies=[Depends(require_permission("vendors.read"))])
def get_vendor_billing_terms(vendor_id: int, db: Session = Depends(get_db)) -> VendorBillingTerms:
    row = db.get(Vendor, vendor_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor not found")
    return _to_public(row, db).billing_terms


@router.patch("/{vendor_id}/billing-terms", response_model=VendorBillingTerms, dependencies=[Depends(require_permission("vendors.write"))])
def update_vendor_billing_terms(
    vendor_id: int,
    body: VendorBillingTerms,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendors.write")),
) -> VendorBillingTerms:
    row = db.get(Vendor, vendor_id)
    if row is None or not row.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor not found")
    if not auth.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="admin only")
    row.billing_pct = body.billing_pct
    row.additional_charge = body.additional_charge
    row.additional_charge_label = body.additional_charge_label
    row.discount_pct = body.discount_pct
    row.gst_included = body.gst_included
    row.gst_rate_pct = body.gst_rate_pct
    row.billing_notes = body.billing_notes
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_public(row, db).billing_terms


@router.get("/{vendor_id}/ledger", response_model=EntityLedgerResponse, dependencies=[Depends(require_permission("vendors.read"))])
def get_vendor_ledger(
    vendor_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
) -> EntityLedgerResponse:
    row = db.get(Vendor, vendor_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor not found")
    items = build_vendor_ledger(db, vendor_id, auth=auth, show_actor=auth.is_admin, include_ap=auth.is_admin)
    return EntityLedgerResponse(items=items, total=len(items))


@router.post("", response_model=VendorPublic, status_code=201, dependencies=[Depends(require_permission("vendors.write"))])
def create_vendor(body: VendorCreate, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permission("vendors.write"))) -> VendorPublic:
    phone = _normalize_phone(body.phone)
    sec = (body.secondary_phone or "").strip()
    sec_norm = _normalize_phone(sec) if sec else None
    if body.city_id is not None:
        _validate_city(db, body.city_id)

    existing = db.query(Vendor).filter(Vendor.phone == phone, Vendor.is_active.is_(True)).one_or_none()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="phone already registered")

    row = Vendor(
        business_name=body.business_name.strip(),
        phone=phone,
        city_id=body.city_id,
        person_name=(body.person_name.strip() if body.person_name else None),
        secondary_phone=sec_norm,
        alias=(body.alias.strip() if body.alias else None),
        address=(body.address.strip() if body.address else None),
        gst_number=(body.gst_number.strip().upper() if body.gst_number else None),
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail="phone already registered") from None
    if body.opening_balance_due and float(body.opening_balance_due) > 0:
        from decimal import Decimal
        from datetime import date as date_cls
        from app.services.ap_ledger import set_opening_balance

        set_opening_balance(
            db,
            vendor_id=row.id,
            amount=Decimal(str(body.opening_balance_due)),
            as_on=body.opening_balance_as_on or date_cls.today(),
            actor_type=auth.actor_type,
            actor_id=auth.actor_id,
            actor_name=auth.actor_name,
        )
    log_from_auth(db, auth, action="create", entity_type="vendor", entity_id=row.id, entity_label=row.business_name)
    db.commit()
    db.refresh(row)
    return _to_public(row, db)


@router.patch("/{vendor_id}", response_model=VendorPublic, dependencies=[Depends(require_permission("vendors.write"))])
def update_vendor(vendor_id: int, body: VendorUpdate, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permission("vendors.write"))) -> VendorPublic:
    row = db.get(Vendor, vendor_id)
    if row is None or not row.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor not found")

    data = body.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="no fields to update")

    before = row_snapshot(row, TRACKED_FIELDS["vendor"])
    old_business_name = row.business_name

    if "phone" in data and data["phone"] is not None:
        phone = _normalize_phone(data["phone"])
        clash = db.query(Vendor).filter(Vendor.phone == phone, Vendor.id != vendor_id, Vendor.is_active.is_(True)).one_or_none()
        if clash:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="phone already registered")
        row.phone = phone
        del data["phone"]

    if "secondary_phone" in data:
        sec = (data["secondary_phone"] or "").strip()
        row.secondary_phone = _normalize_phone(sec) if sec else None
        del data["secondary_phone"]

    if "city_id" in data:
        if data["city_id"] is not None:
            _validate_city(db, data["city_id"])
        row.city_id = data["city_id"]
        del data["city_id"]

    for field in ("business_name", "person_name", "alias", "address"):
        if field in data:
            val = data[field]
            setattr(row, field, val.strip() if val else None)
            del data[field]

    if "gst_number" in data:
        row.gst_number = data["gst_number"].strip().upper() if data["gst_number"] else None
        del data["gst_number"]

    if "is_active" in data and data["is_active"] is not None:
        apply_is_active(row, data["is_active"])
        del data["is_active"]

    after = row_snapshot(row, TRACKED_FIELDS["vendor"])
    summary = diff_summary("vendor", before, after)
    if summary != "updated":
        record_entity_history(db, "vendor", row.id, before, summary)

    if row.business_name != old_business_name:
        old_slug = vendor_folder_slug(old_business_name)
        new_slug = vendor_folder_slug(row.business_name)
        rename_vendor_folder(old_slug, new_slug)
        for p in db.query(CatalogProduct).filter(CatalogProduct.vendor_id == vendor_id).all():
            p.image_keys = update_image_keys_after_vendor_rename(p.image_keys or [], old_slug, new_slug)
        for a in db.query(AddonProduct).filter(AddonProduct.vendor_id == vendor_id).all():
            a.image_keys = update_image_keys_after_vendor_rename(a.image_keys or [], old_slug, new_slug)

    db.add(row)
    log_from_auth(db, auth, action="update", entity_type="vendor", entity_id=row.id, entity_label=row.business_name, detail=summary if summary != "updated" else None)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail="phone already registered") from None
    db.refresh(row)
    return _to_public(row, db)


@router.delete("/{vendor_id}", status_code=204, dependencies=[Depends(require_permission("vendors.write"))])
def delete_vendor(vendor_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permission("vendors.write"))) -> None:
    row = db.get(Vendor, vendor_id)
    if not row or not row.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor not found")
    from decimal import Decimal
    from app.services.ap_ledger import vendor_ap_totals
    due = vendor_ap_totals(db, vendor_id)["outstanding"]
    if due > Decimal("0.009"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete — ₹{due} still to pay. Settle first.",
        )
    row.is_active = False
    row.deleted_at = datetime.now(timezone.utc)
    log_from_auth(db, auth, action="delete", entity_type="vendor", entity_id=row.id, entity_label=row.business_name)
    db.commit()
