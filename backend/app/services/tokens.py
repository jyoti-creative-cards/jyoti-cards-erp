from __future__ import annotations

import time
from typing import Optional

from jose import JWTError, jwt

from app.config import get_settings


def create_access_token(*, customer_id: int, phone: str) -> str:
    s = get_settings()
    exp = int(time.time()) + s.jwt_expire_minutes * 60
    payload = {"sub": str(customer_id), "phone": phone, "exp": exp, "type": "customer"}
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    s = get_settings()
    return jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm])


def token_customer_id(payload: dict) -> int:
    sub = payload.get("sub")
    if sub is None:
        raise JWTError("missing sub")
    return int(sub)


def safe_decode_customer_id(token: str) -> Optional[int]:
    try:
        p = decode_access_token(token)
        return token_customer_id(p)
    except JWTError:
        return None


def create_staff_token(*, staff_id: int, name: str, role: str, permissions: list[str]) -> str:
    s = get_settings()
    exp = int(time.time()) + s.jwt_expire_minutes * 60
    payload = {
        "sub": f"staff:{staff_id}",
        "name": name,
        "role": role,
        "permissions": permissions,
        "exp": exp,
        "type": "staff",
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)


def decode_staff_token(token: str) -> dict:
    s = get_settings()
    payload = jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm])
    if payload.get("type") != "staff":
        raise JWTError("not a staff token")
    return payload


def staff_id_from_payload(payload: dict) -> int:
    sub = payload.get("sub", "")
    return int(sub.split(":")[1])
