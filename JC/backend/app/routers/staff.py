from __future__ import annotations

import logging
import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_db
from app.deps import AuthContext, require_admin
from app.integrations.whatsapp.client import send_account_creation
from app.models.staff import Staff
from app.schemas.staff import (
    PermissionGroupOut,
    StaffCreate,
    StaffCreateResponse,
    StaffPublic,
    StaffUpdate,
)
from app.services.activity import log_from_auth
from app.services.passwords import hash_password
from app.services.permissions import ALL_STAFF_PERMISSIONS, PERMISSION_GROUPS, dump_permissions, parse_permissions
from app.services.soft_delete import apply_is_active

router = APIRouter(prefix="/staff", tags=["staff"])
logger = logging.getLogger("jc.staff")


def _normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D+", "", (raw or "").strip())
    if len(digits) != 10:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="phone must be 10 digits")
    return digits


def _to_public(row: Staff) -> StaffPublic:
    return StaffPublic(
        id=row.id,
        name=row.name,
        phone=row.phone,
        permissions=sorted(parse_permissions(row.permissions_json)),
        is_active=row.is_active,
        created_at=row.created_at,
        updated_at=row.updated_at,
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
    return False, str(result.get("error") or "whatsapp failed")


@router.get("/permissions", response_model=List[PermissionGroupOut], dependencies=[Depends(require_admin)])
def list_permission_groups() -> List[PermissionGroupOut]:
    return [
        PermissionGroupOut(label=label, permissions=[{"key": k, "label": desc} for k, desc in perms])
        for label, perms in PERMISSION_GROUPS
    ]


@router.get("", response_model=List[StaffPublic], dependencies=[Depends(require_admin)])
def list_staff(db: Session = Depends(get_db)) -> List[StaffPublic]:
    rows = db.query(Staff).filter(Staff.is_active.is_(True)).order_by(Staff.id.desc()).all()
    return [_to_public(r) for r in rows]


@router.get("/{staff_id}", response_model=StaffPublic, dependencies=[Depends(require_admin)])
def get_staff(staff_id: int, db: Session = Depends(get_db)) -> StaffPublic:
    row = db.get(Staff, staff_id)
    if not row or not row.is_active:
        raise HTTPException(404, "staff not found")
    return _to_public(row)


@router.post("", response_model=StaffCreateResponse, status_code=201, dependencies=[Depends(require_admin)])
def create_staff(
    body: StaffCreate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
) -> StaffCreateResponse:
    phone = _normalize_phone(body.phone)
    existing = db.query(Staff).filter(Staff.phone == phone, Staff.is_active.is_(True)).first()
    if existing:
        raise HTTPException(409, "phone already registered")

    plain = phone[-4:]
    perms = dump_permissions(body.permissions)
    row = Staff(
        name=body.name.strip(),
        phone=phone,
        password_hash=hash_password(plain),
        permissions_json=perms,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "phone already registered") from None
    db.refresh(row)

    wa_ok, wa_err = _send_whatsapp(row.name, row.phone, plain)
    log_from_auth(
        db, auth, action="create", entity_type="staff", entity_id=row.id,
        entity_label=row.name, detail=f"permissions: {perms}",
    )
    db.commit()

    pub = _to_public(row)
    return StaffCreateResponse(**pub.model_dump(), whatsapp_sent=wa_ok, whatsapp_error=wa_err, temp_password=plain)


@router.patch("/{staff_id}", response_model=StaffPublic, dependencies=[Depends(require_admin)])
def update_staff(
    staff_id: int,
    body: StaffUpdate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
) -> StaffPublic:
    row = db.get(Staff, staff_id)
    if not row or not row.is_active:
        raise HTTPException(404, "staff not found")
    data = body.model_dump(exclude_unset=True)
    if "name" in data and data["name"]:
        row.name = data["name"].strip()
    if "permissions" in data and data["permissions"] is not None:
        row.permissions_json = dump_permissions(data["permissions"])
    if "is_active" in data and data["is_active"] is not None:
        apply_is_active(row, data["is_active"])
    log_from_auth(db, auth, action="update", entity_type="staff", entity_id=row.id, entity_label=row.name)
    db.commit()
    db.refresh(row)
    return _to_public(row)


@router.delete("/{staff_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_staff(staff_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)) -> None:
    row = db.get(Staff, staff_id)
    if not row or not row.is_active:
        raise HTTPException(404, "staff not found")
    from datetime import datetime, timezone
    row.is_active = False
    row.deleted_at = datetime.now(timezone.utc)
    log_from_auth(db, auth, action="delete", entity_type="staff", entity_id=row.id, entity_label=row.name)
    db.commit()
