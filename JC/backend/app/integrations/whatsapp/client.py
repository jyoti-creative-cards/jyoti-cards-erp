from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from typing import Any, Dict, Optional
from urllib.parse import quote

from app.config import get_settings

logger = logging.getLogger("jc.whatsapp")


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
            body = json.loads(r.read().decode() or "{}")
            logger.info("WA sent ok to %s", payload.get("to"))
            return {"ok": True, "response": body}
    except urllib.error.HTTPError as e:
        err = (e.read().decode() if e.fp else "") or str(e)
        logger.error("WA error %s: %s", e.code, err)
        return {"ok": False, "http": e.code, "error": err}


def send_account_creation(
    phone: str,
    customer_name: str,
    login_phone: str,
    password: str,
    button_suffix: str = "",
) -> Dict[str, Any]:
    """Send account_creation_confirmation_3 template.

    The Meta template uses a static URL button — only pass button_suffix when
    the template URL has a dynamic {{1}} segment (CUSTOMER_PORTAL_URL_BUTTON_SUFFIX).
    """
    to = _e164(phone)
    if not to:
        return {"ok": False, "error": "invalid phone"}
    components: list = [
        {
            "type": "body",
            "parameters": [
                {"type": "text", "parameter_name": "name", "text": str(customer_name)[:1024]},
                {"type": "text", "parameter_name": "phone", "text": re.sub(r"\D+", "", login_phone or "")[-10:]},
                {"type": "text", "parameter_name": "password", "text": str(password)[:1024]},
            ],
        },
    ]
    # Only add button param when template has dynamic URL suffix
    suffix = (button_suffix or "").strip()
    if suffix:
        components.append({
            "type": "button",
            "sub_type": "url",
            "index": "0",
            "parameters": [{"type": "text", "text": suffix[:1024]}],
        })
    return _post({
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "template",
        "template": {
            "name": "account_creation_confirmation_3",
            "language": {"code": "hi"},
            "components": components,
        },
    })


def upload_media(data: bytes, filename: str, mime: str = "application/pdf") -> Dict[str, Any]:
    """Upload bytes to WhatsApp Cloud API media; returns {ok, media_id}."""
    s = get_settings()
    if s.whatsapp_disable:
        return {"ok": False, "error": "WHATSAPP_DISABLE"}
    tok = s.whatsapp_access_token.strip()
    pn = s.whatsapp_phone_number_id.strip()
    ver = (s.whatsapp_api_version or "v22.0").strip()
    if not tok or not pn:
        return {"ok": False, "error": "missing WA credentials"}
    boundary = "----JCFormBoundary7MA4YWxkTrZu0gW"
    fname = filename or "document.pdf"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="messaging_product"\r\n\r\nwhatsapp\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="type"\r\n\r\n{mime}\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{fname}"\r\n'
        f"Content-Type: {mime}\r\n\r\n"
    ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
    url = f"https://graph.facebook.com/{ver}/{pn}/media"
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {tok}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            resp = json.loads(r.read().decode() or "{}")
            mid = resp.get("id")
            if not mid:
                return {"ok": False, "error": f"no media id: {resp}"}
            return {"ok": True, "media_id": mid, "response": resp}
    except urllib.error.HTTPError as e:
        err = (e.read().decode() if e.fp else "") or str(e)
        logger.error("WA media upload error %s: %s", e.code, err)
        return {"ok": False, "http": e.code, "error": err}


def send_document(
    phone: str,
    *,
    media_id: Optional[str] = None,
    link: Optional[str] = None,
    filename: str = "document.pdf",
    caption: str = "",
) -> Dict[str, Any]:
    """Send a document message. Works in 24h customer-care window without a template.
    For cold outreach you need an approved template with a DOCUMENT header — not wired yet.
    """
    to = _e164(phone)
    if not to:
        return {"ok": False, "error": "invalid phone"}
    if not media_id and not link:
        return {"ok": False, "error": "media_id or link required"}
    doc: Dict[str, Any] = {"filename": filename[:240]}
    if caption:
        doc["caption"] = caption[:1024]
    if media_id:
        doc["id"] = media_id
    else:
        doc["link"] = link
    return _post({
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "document",
        "document": doc,
    })


def send_text(phone: str, body: str) -> Dict[str, Any]:
    to = _e164(phone)
    if not to:
        return {"ok": False, "error": "invalid phone"}
    return _post({
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {"preview_url": True, "body": (body or "")[:4096]},
    })


def wa_me_link(phone: str, text: str) -> Optional[str]:
    to = _e164(phone)
    if not to:
        return None
    return f"https://wa.me/{to}?text={quote(text or '')}"
