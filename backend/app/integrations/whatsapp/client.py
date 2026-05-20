"""WhatsApp Cloud API — 4 send functions, nothing else."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from app.config import get_settings


def _e164(phone: str) -> Optional[str]:
    t = re.sub(r"\D+", "", (phone or "").strip())
    if not t:
        return None
    if len(t) == 10:
        t = f"91{t}"
    return t if len(t) >= 8 else None


def _post(payload: Dict[str, Any]) -> Dict[str, Any]:
    s = get_settings()
    if s.whatsapp_disable:
        return {"ok": False, "error": "WHATSAPP_DISABLE"}
    tok = s.whatsapp_access_token.strip()
    pn = s.whatsapp_phone_number_id.strip()
    ver = (s.whatsapp_api_version or "v22.0").strip()
    if not tok or not pn:
        return {"ok": False, "error": "missing WA credentials"}
    url = f"https://graph.facebook.com/{ver}/{pn}/messages"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return {"ok": True, "response": json.loads(r.read().decode() or "{}")}
    except urllib.error.HTTPError as e:
        err = (e.read().decode() if e.fp else "") or str(e)
        print(f"WA _post error {e.code}: {err}")
        return {"ok": False, "http": e.code, "error": err}


def upload_media(data: bytes, mime_type: str, filename: str) -> Optional[str]:
    """Upload bytes to Meta media servers. Returns media_id."""
    s = get_settings()
    if s.whatsapp_disable:
        return None
    tok = s.whatsapp_access_token.strip()
    pn = s.whatsapp_phone_number_id.strip()
    ver = (s.whatsapp_api_version or "v22.0").strip()
    if not tok or not pn:
        return None
    boundary = "WAboundaryX9mZ"
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"messaging_product\"\r\n\r\nwhatsapp\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"type\"\r\n\r\n{mime_type}\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\nContent-Type: {mime_type}\r\n\r\n"
    ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
    url = f"https://graph.facebook.com/{ver}/{pn}/media"
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Authorization": f"Bearer {tok}", "Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            mid = json.loads(r.read().decode() or "{}").get("id")
            print(f"upload_media ok: {filename} -> {mid}")
            return mid
    except urllib.error.HTTPError as e:
        print(f"upload_media error {e.code}: {(e.read().decode() if e.fp else '')}")
        return None
    except Exception as e:
        print(f"upload_media exception: {e}")
        return None


def send_order_confirmation(
    phone: str,
    customer_name: str,
    order_id: int,
    items_summary: str,
    quantity: int,
    amount: str,
    note: str,
    pdf_media_id: str,
    order_url_suffix: str = "",
) -> Dict[str, Any]:
    """Send order_confirmation template with PDF header."""
    to = _e164(phone)
    if not to:
        return {"ok": False, "error": "invalid phone"}
    components: list = [
        {"type": "header", "parameters": [{"type": "document", "document": {"id": pdf_media_id, "filename": f"Order_{order_id}.pdf"}}]},
        {"type": "body", "parameters": [
            {"type": "text", "text": str(customer_name)[:1024]},
            {"type": "text", "text": str(order_id)},
            {"type": "text", "text": str(items_summary)[:1024]},
            {"type": "text", "text": str(quantity)},
            {"type": "text", "text": str(amount)[:1024]},
            {"type": "text", "text": str(note or "—")[:1024]},
        ]},
    ]
    if order_url_suffix:
        components.append({"type": "button", "sub_type": "url", "index": "0", "parameters": [{"type": "text", "text": order_url_suffix[:1024]}]})
    return _post({
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "template",
        "template": {"name": "order_confirmation", "language": {"code": "hi"}, "components": components},
    })


def send_order_billed(
    phone: str,
    customer_name: str,
    order_id: int,
    amount: str,
    note: str,
    pdf_media_id: str,
    order_url_suffix: str = "",
) -> Dict[str, Any]:
    """Send order_billed template with bill PDF header."""
    to = _e164(phone)
    if not to:
        return {"ok": False, "error": "invalid phone"}
    components: list = [
        {"type": "header", "parameters": [{"type": "document", "document": {"id": pdf_media_id, "filename": f"Bill_{order_id}.pdf"}}]},
        {"type": "body", "parameters": [
            {"type": "text", "text": str(customer_name)[:1024]},
            {"type": "text", "text": str(order_id)},
            {"type": "text", "text": str(amount)[:1024]},
            {"type": "text", "text": str(note or "—")[:1024]},
        ]},
    ]
    if order_url_suffix:
        components.append({"type": "button", "sub_type": "url", "index": "0", "parameters": [{"type": "text", "text": order_url_suffix[:1024]}]})
    return _post({
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "template",
        "template": {"name": "order_billed", "language": {"code": "hi"}, "components": components},
    })


def send_shipment_confirmation(
    phone: str,
    customer_name: str,
    receipt: str,
    contact: str,
    service: str,
    notes: str,
    tracking_url_suffix: str = "",
) -> Dict[str, Any]:
    """Send shipment_confirmation template (no header)."""
    to = _e164(phone)
    if not to:
        return {"ok": False, "error": "invalid phone"}
    components: list = [
        {"type": "body", "parameters": [
            {"type": "text", "text": str(customer_name)[:1024]},
            {"type": "text", "text": str(receipt)[:1024]},
            {"type": "text", "text": str(contact)[:1024]},
            {"type": "text", "text": str(service or "—")[:1024]},
            {"type": "text", "text": str(notes or "—")[:1024]},
        ]},
    ]
    if tracking_url_suffix:
        components.append({"type": "button", "sub_type": "url", "index": "0", "parameters": [{"type": "text", "text": tracking_url_suffix[:1024]}]})
    return _post({
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "template",
        "template": {"name": "shipment_confirmation", "language": {"code": "hi"}, "components": components},
    })


def send_account_creation(
    phone: str,
    customer_name: str,
    login_phone: str,
    password: str,
    portal_url_suffix: str = "",
) -> Dict[str, Any]:
    """Send account_creation_confirmation_3 template."""
    to = _e164(phone)
    if not to:
        return {"ok": False, "error": "invalid phone"}
    components: list = [
        {"type": "body", "parameters": [
            {"type": "text", "parameter_name": "name", "text": str(customer_name)[:1024]},
            {"type": "text", "parameter_name": "phone", "text": re.sub(r"\D+", "", login_phone or "")[-10:]},
            {"type": "text", "parameter_name": "password", "text": str(password)[:1024]},
        ]},
    ]
    if portal_url_suffix:
        components.append({"type": "button", "sub_type": "url", "index": "0", "parameters": [{"type": "text", "text": portal_url_suffix[:1024]}]})
    return _post({
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "template",
        "template": {"name": "account_creation_confirmation_3", "language": {"code": "hi"}, "components": components},
    })
