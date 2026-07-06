from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db, sql_is_active_true
from app.deps import require_admin
from app.integrations.whatsapp.client import _e164 as normalize_e164
from app.models.vendor import Vendor
from app.schemas.vendor import VendorCreate, VendorPublic, VendorUpdate

router = APIRouter(prefix="/vendors", tags=["vendors"])


def _apply_fields(row: Vendor, body: VendorCreate | VendorUpdate, phone: str, sec_norm: Optional[str]) -> None:
    """Write all fields from body onto a Vendor row."""
    company = body.company_name.strip() if body.company_name else ""
    person = (body.person_name or "").strip() or company
    row.company_name = company
    row.person_name = person
    row.phone = phone
    row.secondary_phone = sec_norm
    row.address = body.address.strip() if body.address else None
    row.city_id = body.city_id
    row.gst_number = body.gst_number.strip().upper() if body.gst_number else None
    row.alias = body.alias.strip() if body.alias else None


@router.get("", response_model=List[VendorPublic], dependencies=[Depends(require_admin)])
def list_vendors(
    db: Session = Depends(get_db),
    include_inactive: bool = Query(False),
    deleted: Optional[bool] = Query(None),
) -> List[Vendor]:
    q = db.query(Vendor)
    if deleted is True:
        q = q.filter(Vendor.deleted_at.isnot(None))
    else:
        q = q.filter(Vendor.deleted_at.is_(None))
        if not include_inactive:
            q = q.filter(sql_is_active_true(Vendor.is_active))
    return q.order_by(Vendor.id.asc()).all()


@router.get("/{vendor_id}", response_model=VendorPublic, dependencies=[Depends(require_admin)])
def get_vendor(vendor_id: int, db: Session = Depends(get_db)) -> Vendor:
    row = db.get(Vendor, vendor_id)
    if row is None or row.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor not found")
    return row


@router.post("", response_model=VendorPublic, dependencies=[Depends(require_admin)])
def create_vendor(body: VendorCreate, db: Session = Depends(get_db)) -> Vendor:
    phone = normalize_e164(body.phone.strip())
    if not phone:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid phone")
    sec = (body.secondary_phone or "").strip()
    sec_norm = normalize_e164(sec) if sec else None
    if sec and not sec_norm:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid secondary phone")

    existing = db.query(Vendor).filter(Vendor.phone == phone).one_or_none()

    # Active vendor with same phone → conflict
    if existing is not None and existing.deleted_at is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="phone already registered with an active vendor")

    if existing is not None:
        # Soft-deleted vendor — restore and update all fields
        _apply_fields(existing, body, phone, sec_norm)
        existing.is_active = True
        existing.deleted_at = None
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return existing

    # New vendor
    row = Vendor(is_active=True)
    _apply_fields(row, body, phone, sec_norm)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail="phone already registered") from None
    db.refresh(row)
    return row


@router.patch("/{vendor_id}", response_model=VendorPublic, dependencies=[Depends(require_admin)])
def update_vendor(vendor_id: int, body: VendorUpdate, db: Session = Depends(get_db)) -> Vendor:
    row = db.get(Vendor, vendor_id)
    if row is None or row.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor not found")

    data = body.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="no fields to update")

    if "phone" in data:
        phone = normalize_e164(str(data.pop("phone")).strip())
        if not phone:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid phone")
        row.phone = phone
    else:
        data.pop("phone", None)

    if "person_name" in data:
        row.person_name = str(data.pop("person_name")).strip() or row.company_name or ""
    if "company_name" in data:
        v = data.pop("company_name")
        row.company_name = v.strip() if isinstance(v, str) and v.strip() else None
    if "address" in data:
        v = data.pop("address")
        row.address = v.strip() if isinstance(v, str) and v.strip() else None
    if "city_id" in data:
        row.city_id = data.pop("city_id")
    if "gst_number" in data:
        v = data.pop("gst_number")
        row.gst_number = v.strip().upper() if isinstance(v, str) and v.strip() else None
    if "alias" in data:
        v = data.pop("alias")
        row.alias = v.strip() if isinstance(v, str) and v.strip() else None
    if "secondary_phone" in data:
        sec = data.pop("secondary_phone")
        if not sec or (isinstance(sec, str) and not sec.strip()):
            row.secondary_phone = None
        else:
            sec_norm = normalize_e164(str(sec).strip())
            if not sec_norm:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid secondary phone")
            row.secondary_phone = sec_norm

    # Ignore free-text city (city_id only)
    data.pop("city", None)

    if data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"unknown fields: {list(data.keys())}")

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail="phone already registered") from None
    db.refresh(row)
    return row


@router.post("/{vendor_id}/restore", dependencies=[Depends(require_admin)])
def restore_vendor(vendor_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(Vendor, vendor_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor not found")
    row.deleted_at = None
    row.is_active = True
    db.add(row)
    db.commit()
    return {"ok": True, "id": vendor_id, "restored": True}


@router.post("/{vendor_id}/reactivate", dependencies=[Depends(require_admin)])
def reactivate_vendor(vendor_id: int, db: Session = Depends(get_db)) -> dict:
    """Alias for restore — kept for backwards compatibility."""
    row = db.get(Vendor, vendor_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor not found")
    row.is_active = True
    row.deleted_at = None
    db.add(row)
    db.commit()
    return {"ok": True, "id": vendor_id, "reactivated": True}


@router.delete("/{vendor_id}/permanent", dependencies=[Depends(require_admin)])
def permanently_delete_vendor(vendor_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(Vendor, vendor_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor not found")
    db.delete(row)
    db.commit()
    return {"ok": True, "id": vendor_id, "permanently_deleted": True}


@router.delete("/{vendor_id}", dependencies=[Depends(require_admin)])
def deactivate_vendor(vendor_id: int, db: Session = Depends(get_db)) -> dict:
    """Soft-delete: sets deleted_at and is_active=False."""
    row = db.get(Vendor, vendor_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor not found")
    row.is_active = False
    row.deleted_at = datetime.now(timezone.utc)
    db.add(row)
    db.commit()
    return {"ok": True, "id": vendor_id, "deactivated": True}
