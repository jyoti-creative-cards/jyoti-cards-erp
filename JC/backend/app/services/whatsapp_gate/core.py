"""On/off switch for every outbound WhatsApp send. Missing row means off."""
from __future__ import annotations

import logging

from app.models.runtime_flag import RuntimeFlag

log = logging.getLogger("jc.whatsapp")

WHATSAPP_SENDS = "whatsapp_sends"


def _read_flag() -> str | None:
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        row = db.get(RuntimeFlag, WHATSAPP_SENDS)
        return None if row is None else str(row.value or "")
    finally:
        db.close()


def whatsapp_sends_enabled() -> bool:
    try:
        return _read_flag() == "1"
    except Exception:
        log.exception("whatsapp flag read failed; treating sends as off")
        return False


def set_whatsapp_sends(enabled: bool) -> bool:
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        row = db.get(RuntimeFlag, WHATSAPP_SENDS)
        if row is None:
            row = RuntimeFlag(key=WHATSAPP_SENDS, value="1" if enabled else "0")
            db.add(row)
        else:
            row.value = "1" if enabled else "0"
        db.commit()
        return row.value == "1"
    finally:
        db.close()
