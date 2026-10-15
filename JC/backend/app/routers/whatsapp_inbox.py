"""Public Meta webhook plus the staff inbox for messages on the business number."""
from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_db
from app.deps import AuthContext, get_auth_context
from app.integrations.whatsapp.client import send_text
from app.models.customer import Customer
from app.models.whatsapp_message import WhatsAppMessage
from app.services.whatsapp_inbox import ingest_payload, match_customer, phone_key, store_outbound, thread_public

logger = logging.getLogger("jc.whatsapp")

router = APIRouter(tags=["whatsapp"])


class ReplyIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


def _signature_ok(body: bytes, header: Optional[str]) -> bool:
    secret = (get_settings().whatsapp_app_secret or "").strip()
    if not secret:
        return True
    if not header or not header.startswith("sha256="):
        return False
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header[7:], digest)


def _names(db: Session, customer_ids: list[int]) -> dict[int, str]:
    if not customer_ids:
        return {}
    rows = db.query(Customer).filter(Customer.id.in_(customer_ids)).all()
    return {row.id: row.business_name for row in rows}


@router.get("/webhooks/whatsapp")
def verify_webhook(
    mode: Optional[str] = Query(None, alias="hub.mode"),
    token: Optional[str] = Query(None, alias="hub.verify_token"),
    challenge: Optional[str] = Query(None, alias="hub.challenge"),
):
    expected = (get_settings().whatsapp_webhook_verify_token or "").strip()
    if not expected:
        raise HTTPException(503, "WhatsApp webhook verify token is not set")
    if mode == "subscribe" and token and hmac.compare_digest(token, expected):
        return PlainTextResponse(challenge or "")
    raise HTTPException(403, "verification failed")


@router.post("/webhooks/whatsapp")
async def receive_webhook(request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    if not _signature_ok(raw, request.headers.get("x-hub-signature-256")):
        raise HTTPException(403, "bad signature")
    try:
        payload = await request.json()
    except Exception:
        return {"ok": True, "saved": 0}
    if not isinstance(payload, dict):
        return {"ok": True, "saved": 0}
    saved = ingest_payload(db, payload)
    return {"ok": True, "saved": saved}


@router.get("/whatsapp/inbox")
def list_threads(
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    del auth
    latest = (
        db.query(WhatsAppMessage.phone, func.max(WhatsAppMessage.id).label("mid"))
        .group_by(WhatsAppMessage.phone)
        .subquery()
    )
    rows = (
        db.query(WhatsAppMessage)
        .join(latest, WhatsAppMessage.id == latest.c.mid)
        .order_by(WhatsAppMessage.wa_timestamp.desc())
        .limit(200)
        .all()
    )
    names = _names(db, [row.customer_id for row in rows if row.customer_id])
    return {
        "threads": [
            thread_public(row, names.get(row.customer_id) if row.customer_id else None)
            for row in rows
        ]
    }


@router.get("/whatsapp/inbox/{phone}")
def list_messages(
    phone: str,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    del auth
    key = phone_key(phone)
    if not key:
        raise HTTPException(400, "phone required")
    rows = (
        db.query(WhatsAppMessage)
        .filter(WhatsAppMessage.phone == key)
        .order_by(WhatsAppMessage.wa_timestamp.asc(), WhatsAppMessage.id.asc())
        .limit(500)
        .all()
    )
    names = _names(db, [row.customer_id for row in rows if row.customer_id])
    return {
        "phone": key,
        "messages": [
            thread_public(row, names.get(row.customer_id) if row.customer_id else None)
            for row in rows
        ],
    }


@router.post("/whatsapp/inbox/{phone}/reply")
def reply(
    phone: str,
    body: ReplyIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    del auth
    key = phone_key(phone)
    if not key:
        raise HTTPException(400, "phone required")
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "message is empty")
    result = send_text(key, text)
    if not result.get("ok"):
        err = str(result.get("error") or "WhatsApp did not send")
        if "131047" in err or "131026" in err:
            raise HTTPException(
                400,
                "WhatsApp only allows a free reply within 24 hours of the customer's last message. "
                "Order, bill, and dispatch updates still go out as templates.",
            )
        logger.warning("inbox reply failed: %s", err[:300])
        raise HTTPException(400, "WhatsApp did not send that reply")
    response = result.get("response") or {}
    messages = response.get("messages") or []
    wamid = ""
    if messages and isinstance(messages[0], dict):
        wamid = str(messages[0].get("id") or "")
    customer = match_customer(db, key)
    row = store_outbound(db, key, text, wamid, customer.id if customer else None)
    return thread_public(row, customer.business_name if customer else None)
