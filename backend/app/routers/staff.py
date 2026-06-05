from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, EmailStr
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import require_admin_only
from app.models.staff_user import StaffUser, PERMISSIONS
from app.services.passwords import hash_password, verify_password
from app.services.tokens import create_staff_token

router = APIRouter(prefix="/staff", tags=["staff"])


# ─── Schemas ──────────────────────────────────────────────────────────────────

class StaffCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    email: str = Field(..., min_length=3, max_length=200)
    phone: Optional[str] = None
    password: str = Field(..., min_length=4)
    role: str = Field(default="staff", pattern="^(admin|staff)$")
    permissions: list[str] = Field(default=[])


class StaffUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    password: Optional[str] = None
    role: Optional[str] = Field(default=None, pattern="^(admin|staff)$")
    permissions: Optional[list[str]] = None
    is_active: Optional[bool] = None


class StaffPublic(BaseModel):
    id: int
    name: str
    email: str
    phone: Optional[str]
    role: str
    is_active: bool
    permissions: list[str]
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class StaffLoginRequest(BaseModel):
    email: str
    password: str


class StaffLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    staff: StaffPublic


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _to_public(row: StaffUser) -> StaffPublic:
    perms = row.permissions if isinstance(row.permissions, list) else []
    return StaffPublic(
        id=row.id,
        name=row.name,
        email=row.email,
        phone=row.phone,
        role=row.role,
        is_active=bool(row.is_active),
        permissions=perms if row.role != "admin" else PERMISSIONS,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


def _effective_permissions(user: StaffUser) -> list[str]:
    if user.role == "admin":
        return PERMISSIONS
    perms = user.permissions
    return perms if isinstance(perms, list) else []


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.post("/login", response_model=StaffLoginResponse)
def staff_login(body: StaffLoginRequest, db: Session = Depends(get_db)) -> StaffLoginResponse:
    email = body.email.strip().lower()
    user = db.query(StaffUser).filter(StaffUser.email == email, StaffUser.is_active.is_(True)).one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="wrong email or password")

    perms = _effective_permissions(user)
    token = create_staff_token(staff_id=user.id, name=user.name, role=user.role, permissions=perms)
    return StaffLoginResponse(access_token=token, staff=_to_public(user))


@router.get("/permissions-list", dependencies=[Depends(require_admin_only)])
def list_permissions() -> list[str]:
    return PERMISSIONS


@router.get("", response_model=list[StaffPublic], dependencies=[Depends(require_admin_only)])
def list_staff(db: Session = Depends(get_db)) -> list[StaffPublic]:
    rows = db.query(StaffUser).order_by(StaffUser.id).all()
    return [_to_public(r) for r in rows]


@router.post("", response_model=StaffPublic, dependencies=[Depends(require_admin_only)])
def create_staff(body: StaffCreate, db: Session = Depends(get_db)) -> StaffPublic:
    email = body.email.strip().lower()
    existing = db.query(StaffUser).filter(StaffUser.email == email).one_or_none()
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="email already registered")

    # Validate permissions
    invalid = [p for p in body.permissions if p not in PERMISSIONS]
    if invalid:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"unknown permissions: {invalid}")

    user = StaffUser(
        name=body.name.strip(),
        email=email,
        phone=(body.phone or "").strip() or None,
        password_hash=hash_password(body.password),
        role=body.role,
        permissions=body.permissions,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _to_public(user)


@router.patch("/{staff_id}", response_model=StaffPublic, dependencies=[Depends(require_admin_only)])
def update_staff(staff_id: int, body: StaffUpdate, db: Session = Depends(get_db)) -> StaffPublic:
    user = db.get(StaffUser, staff_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="staff user not found")

    if body.name is not None:
        user.name = body.name.strip()
    if body.email is not None:
        email = body.email.strip().lower()
        existing = db.query(StaffUser).filter(StaffUser.email == email, StaffUser.id != staff_id).one_or_none()
        if existing:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="email already in use")
        user.email = email
    if body.phone is not None:
        user.phone = body.phone.strip() or None
    if body.password is not None and body.password.strip():
        user.password_hash = hash_password(body.password.strip())
    if body.role is not None:
        user.role = body.role
    if body.permissions is not None:
        invalid = [p for p in body.permissions if p not in PERMISSIONS]
        if invalid:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"unknown permissions: {invalid}")
        user.permissions = body.permissions
    if body.is_active is not None:
        user.is_active = body.is_active

    db.add(user)
    db.commit()
    db.refresh(user)
    return _to_public(user)


@router.delete("/{staff_id}", status_code=204, dependencies=[Depends(require_admin_only)])
def deactivate_staff(staff_id: int, db: Session = Depends(get_db)) -> None:
    user = db.get(StaffUser, staff_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="staff user not found")
    user.is_active = False
    db.add(user)
    db.commit()
