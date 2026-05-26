from __future__ import annotations

import time
from typing import Optional

from jose import JWTError, jwt

from app.config import get_settings


def create_access_token(*, customer_id: int, phone: str) -> str:
    s = get_settings()
    exp = int(time.time()) + s.jwt_expire_minutes * 60
    payload = {"sub": str(customer_id), "phone": phone, "exp": exp}
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
