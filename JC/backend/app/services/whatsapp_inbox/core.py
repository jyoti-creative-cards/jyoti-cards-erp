"""Store and list WhatsApp messages that arrive on the business number."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.whatsapp_message import WhatsAppMessage

_MEDIA = {
    "image": "Photo",
    "video": "Video",
    "audio": "Voice note",
    "document": "Document",
    "sticker": "Sticker",
}


def digits(phone: str) -> str:
    return re.sub(r"\D+", "", phone or "")


def phone_key(phone: str) -> str:
    """Last 10 digits when the number is long enough, otherwise the digits we have."""
    d = digits(phone)
    if len(d) >= 10:
        return d[-10:]
    return d


def message_text(msg: dict) -> tuple[str, str]:
    kind = str(msg.get("type") or "unknown")[:32]
    if kind == "text":
        return kind, str((msg.get("text") or {}).get("body") or "")[:4000]
    if kind in _MEDIA:
        block = msg.get(kind) or {}
        extra = str(block.get("filename") or block.get("caption") or "").strip()
        label = _MEDIA[kind]
        text = f"[{label}] {extra}".strip() if extra else f"[{label}]"
        return kind, text[:4000]
    if kind == "button":
        return kind, str((msg.get("button") or {}).get("text") or "[Button]")[:4000]
    if kind == "interactive":
        block = msg.get("interactive") or {}
        title = (
            (block.get("button_reply") or {}).get("title")
            or (block.get("list_reply") or {}).get("title")
            or "[Reply]"
        )
        return kind, str(title)[:4000]
    if kind == "reaction":
        return kind, str((msg.get("reaction") or {}).get("emoji") or "")[:32]
    if kind == "location":
        block = msg.get("location") or {}
        return kind, str(block.get("name") or block.get("address") or "[Location]")[:4000]
    return kind, f"[{kind}]"


def _when(raw: object) -> datetime:
    try:
        return datetime.fromtimestamp(int(str(raw)), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return datetime.now(timezone.utc)


def match_customer(db: Session, phone: str) -> Optional[Customer]:
    tail = phone_key(phone)
    if len(tail) < 10:
        return None
    rows = (
        db.query(Customer)
        .filter(Customer.deleted_at.is_(None))
        .filter(
            (Customer.phone.like(f"%{tail}")) | (Customer.secondary_phone.like(f"%{tail}"))
        )
        .limit(8)
        .all()
    )
    for row in rows:
        if phone_key(row.phone) == tail or phone_key(row.secondary_phone or "") == tail:
            return row
    return None


def ingest_payload(db: Session, payload: dict) -> int:
    """Save inbound messages. Returns how many new rows were stored."""
    saved = 0
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            names = {}
            for contact in value.get("contacts") or []:
                wa_id = phone_key(str(contact.get("wa_id") or ""))
                profile = (contact.get("profile") or {}).get("name")
                if wa_id and profile:
                    names[wa_id] = str(profile)[:200]
            for msg in value.get("messages") or []:
                if not isinstance(msg, dict):
                    continue
                wamid = str(msg.get("id") or "").strip()[:160]
                phone = phone_key(str(msg.get("from") or ""))
                if not wamid or not phone:
                    continue
                if db.query(WhatsAppMessage.id).filter(WhatsAppMessage.wamid == wamid).first():
                    continue
                kind, body = message_text(msg)
                customer = match_customer(db, phone)
                db.add(WhatsAppMessage(
                    wamid=wamid,
                    direction="in",
                    phone=phone,
                    contact_name=names.get(phone),
                    customer_id=customer.id if customer else None,
                    message_type=kind,
                    body=body,
                    wa_timestamp=_when(msg.get("timestamp")),
                ))
                saved += 1
    if saved:
        db.commit()
    return saved


def store_outbound(db: Session, phone: str, body: str, wamid: str, customer_id: Optional[int]) -> WhatsAppMessage:
    row = WhatsAppMessage(
        wamid=(wamid or f"local-{phone}-{int(datetime.now(timezone.utc).timestamp())}")[:160],
        direction="out",
        phone=phone_key(phone),
        customer_id=customer_id,
        message_type="text",
        body=(body or "")[:4000],
        wa_timestamp=datetime.now(timezone.utc),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def thread_public(row: WhatsAppMessage, customer_name: Optional[str]) -> dict[str, Any]:
    return {
        "id": row.id,
        "direction": row.direction,
        "phone": row.phone,
        "contact_name": row.contact_name,
        "customer_id": row.customer_id,
        "customer_name": customer_name,
        "message_type": row.message_type,
        "body": row.body,
        "at": row.wa_timestamp.isoformat() if row.wa_timestamp else None,
    }
