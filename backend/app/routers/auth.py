from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db, sql_is_active_true
from app.deps import get_current_customer
from app.integrations.whatsapp.client import _e164 as normalize_whatsapp_e164
from app.models.customer import Customer
from app.schemas.customer import CustomerPublic, LoginRequest, LoginResponse
from app.services.passwords import verify_password
from app.services.tokens import create_access_token
from app.config import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    phone = normalize_whatsapp_e164(body.phone.strip())
    if not phone:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid phone")
    row = (
        db.query(Customer)
        .filter(Customer.phone == phone, sql_is_active_true(Customer.is_active))
        .one_or_none()
    )
    if row is None or not verify_password(body.password, row.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="wrong phone or password")
    s = get_settings()
    token = create_access_token(customer_id=row.id, phone=row.phone)
    return LoginResponse(
        access_token=token,
        expires_in_minutes=s.jwt_expire_minutes,
    )


@router.get("/me", response_model=CustomerPublic)
def me(customer: Customer = Depends(get_current_customer)) -> CustomerPublic:
    return customer
