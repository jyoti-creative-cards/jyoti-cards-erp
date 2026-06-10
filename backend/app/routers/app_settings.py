"""App-wide key-value settings (cancel PIN, etc.)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import require_admin

router = APIRouter(prefix="/app-settings", tags=["app-settings"])

_DEFAULTS: dict[str, str] = {
    "cancel_order_pin": "1234",
    "session_timeout_minutes": "15",
}


def _ensure_table(db: Session) -> None:
    db.execute(text(
        "CREATE TABLE IF NOT EXISTS portal_app_settings "
        "(key VARCHAR(100) PRIMARY KEY, value TEXT NOT NULL)"
    ))
    db.commit()


def _get(db: Session, key: str) -> str:
    _ensure_table(db)
    row = db.execute(text("SELECT value FROM portal_app_settings WHERE key = :k"), {"k": key}).fetchone()
    return row[0] if row else _DEFAULTS.get(key, "")


def _set(db: Session, key: str, value: str) -> None:
    _ensure_table(db)
    db.execute(
        text("INSERT INTO portal_app_settings (key, value) VALUES (:k, :v) "
             "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"),
        {"k": key, "v": value},
    )
    db.commit()


class SettingsPublic(BaseModel):
    cancel_order_pin: str
    session_timeout_minutes: str


class SettingsUpdate(BaseModel):
    cancel_order_pin: str | None = None
    session_timeout_minutes: str | None = None


@router.get("", response_model=SettingsPublic, dependencies=[Depends(require_admin)])
def get_settings(db: Session = Depends(get_db)) -> SettingsPublic:
    return SettingsPublic(
        cancel_order_pin=_get(db, "cancel_order_pin"),
        session_timeout_minutes=_get(db, "session_timeout_minutes"),
    )


@router.post("", response_model=SettingsPublic, dependencies=[Depends(require_admin)])
def update_settings(body: SettingsUpdate, db: Session = Depends(get_db)) -> SettingsPublic:
    if body.cancel_order_pin is not None:
        pin = body.cancel_order_pin.strip()
        if not pin.isdigit() or len(pin) < 4:
            from fastapi import HTTPException, status
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="PIN must be at least 4 digits")
        _set(db, "cancel_order_pin", pin)
    if body.session_timeout_minutes is not None:
        _set(db, "session_timeout_minutes", body.session_timeout_minutes)
    return get_settings(db)
