from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_db
from app.deps import get_current_customer
from app.models.city import City
from app.models.customer import Customer
from app.models.route import Route
from app.models.staff import Staff
from app.schemas.customer import CustomerPublic, LoginRequest, LoginResponse
from app.schemas.staff import StaffLoginRequest, StaffLoginResponse, StaffPublic
from app.services.passwords import verify_password
from app.services.permissions import parse_permissions
from app.services.rate_limit import record_failure, record_success, seconds_until_unlocked
from app.services.tokens import create_access_token, create_staff_token, customer_token_ttl_minutes

router = APIRouter(prefix="/auth", tags=["auth"])


def _to_public(row: Customer, db: Session) -> CustomerPublic:
    city_name = None
    route_name = None
    if row.city_id:
        city = db.get(City, row.city_id)
        city_name = city.name if city else None
    if row.route_id:
        route = db.get(Route, row.route_id)
        route_name = route.name if route else None
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
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    digits = re.sub(r"\D+", "", body.phone.strip())
    if len(digits) != 10:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid phone")
    lock_key = f"customer_login:{digits}"
    wait = seconds_until_unlocked(lock_key)
    if wait > 0:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail=f"too many attempts — try again in {int(wait // 60) + 1} min")
    row = db.query(Customer).filter(Customer.phone == digits, Customer.is_active.is_(True)).one_or_none()
    if row is None or not verify_password(body.password, row.password_hash):
        record_failure(lock_key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="wrong phone or password")
    record_success(lock_key)
    token = create_access_token(customer_id=row.id, phone=row.phone)
    return LoginResponse(access_token=token, expires_in_minutes=customer_token_ttl_minutes())


@router.get("/me", response_model=CustomerPublic)
def me(customer: Customer = Depends(get_current_customer), db: Session = Depends(get_db)) -> CustomerPublic:
    return _to_public(customer, db)


def _staff_public(row: Staff) -> StaffPublic:
    return StaffPublic(
        id=row.id,
        name=row.name,
        phone=row.phone,
        permissions=sorted(parse_permissions(row.permissions_json)),
        is_active=row.is_active,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.post("/staff/login", response_model=StaffLoginResponse)
def staff_login(body: StaffLoginRequest, db: Session = Depends(get_db)) -> StaffLoginResponse:
    import re
    digits = re.sub(r"\D+", "", body.phone.strip())
    if len(digits) != 10:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid phone")
    lock_key = f"staff_login:{digits}"
    wait = seconds_until_unlocked(lock_key)
    if wait > 0:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail=f"too many attempts — try again in {int(wait // 60) + 1} min")
    row = db.query(Staff).filter(Staff.phone == digits, Staff.is_active.is_(True)).one_or_none()
    if row is None or not verify_password(body.password, row.password_hash):
        record_failure(lock_key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="wrong phone or password")
    record_success(lock_key)
    s = get_settings()
    token = create_staff_token(staff_id=row.id, phone=row.phone)
    return StaffLoginResponse(
        access_token=token,
        expires_in_minutes=s.jwt_expire_minutes,
        staff=_staff_public(row),
    )
