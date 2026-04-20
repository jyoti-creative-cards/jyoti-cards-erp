from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, List
import requests

from config import (
    BUSINESS_WHATSAPP_NUMBER,
    INTERNAL_ALERT_NUMBER,
    CUSTOMER_WELCOME_TEMPLATE,
    META_DEFAULT_TEMPLATE_LANGUAGE,
    META_ACCESS_TOKEN,
    META_PHONE_NUMBER_ID,
    META_API_VERSION,
    WHATSAPP_PROVIDER,
)
from db.models import WhatsAppLog


@dataclass
class NotificationResult:
    status: str
    provider_message_id: str = ""
    error: str = ""


def _headers_json():
    return {
        "Authorization": f"Bearer {META_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def _headers_auth():
    return {"Authorization": f"Bearer {META_ACCESS_TOKEN}"}


def _is_live():
    return WHATSAPP_PROVIDER == "meta" and META_ACCESS_TOKEN and META_PHONE_NUMBER_ID


def normalize_phone(phone: str) -> str:
    if not phone:
        return ""
    digits = "".join(ch for ch in str(phone) if ch.isdigit())
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 10:
        return f"91{digits}"
    return digits


def log_message(db, phone: str, direction: str, message: str, related_type: str = None, related_id: int = None, status: str = "logged"):
    entry = WhatsAppLog(
        phone=phone,
        direction=direction,
        message=message,
        related_type=related_type,
        related_id=related_id,
        status=status,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


# ── text message ──────────────────────────────────────────────────────────────

def send_whatsapp_message(db, phone: str, message: str, related_type: str = None, related_id: int = None) -> NotificationResult:
    phone = normalize_phone(phone)
    if not phone:
        log_message(db, phone or "", "out", message, related_type, related_id, status="skipped")
        return NotificationResult(status="skipped", error="missing phone")

    if not _is_live():
        log_message(db, phone, "out", message, related_type, related_id, status="sent")
        return NotificationResult(status="sent")

    url = f"https://graph.facebook.com/{META_API_VERSION}/{META_PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "text",
        "text": {"body": message},
    }
    response = requests.post(url, json=payload, headers=_headers_json(), timeout=30)
    if response.ok:
        provider_id = response.json().get("messages", [{}])[0].get("id", "")
        log_message(db, phone, "out", message, related_type, related_id, status="sent")
        return NotificationResult(status="sent", provider_message_id=provider_id)

    log_message(db, phone, "out", message, related_type, related_id, status="failed")
    return NotificationResult(status="failed", error=response.text)


# ── media upload ──────────────────────────────────────────────────────────────

def upload_media(filepath: str, mime_type: str = "application/pdf") -> str:
    """Upload a file to Meta and return the media_id. Returns '' on failure or mock mode."""
    if not _is_live():
        return ""
    url = f"https://graph.facebook.com/{META_API_VERSION}/{META_PHONE_NUMBER_ID}/media"
    with open(filepath, "rb") as f:
        resp = requests.post(
            url,
            headers=_headers_auth(),
            files={"file": (os.path.basename(filepath), f, mime_type)},
            data={"messaging_product": "whatsapp"},
            timeout=60,
        )
    if resp.ok:
        return resp.json().get("id", "")
    return ""


# ── document message ──────────────────────────────────────────────────────────

def send_whatsapp_document(db, phone: str, filepath: str, caption: str, filename: str,
                           related_type: str = None, related_id: int = None) -> NotificationResult:
    """Send a PDF (or any doc) via WhatsApp to a phone number."""
    phone = normalize_phone(phone)
    log_text = f"[Document: {filename}] {caption}"

    if not phone:
        log_message(db, phone or "", "out", log_text, related_type, related_id, status="skipped")
        return NotificationResult(status="skipped", error="missing phone")

    if not _is_live():
        log_message(db, phone, "out", log_text, related_type, related_id, status="sent")
        return NotificationResult(status="sent")

    media_id = upload_media(filepath)
    if not media_id:
        log_message(db, phone, "out", log_text, related_type, related_id, status="failed")
        return NotificationResult(status="failed", error="media upload failed")

    url = f"https://graph.facebook.com/{META_API_VERSION}/{META_PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "document",
        "document": {
            "id": media_id,
            "caption": caption,
            "filename": filename,
        },
    }
    response = requests.post(url, json=payload, headers=_headers_json(), timeout=30)
    if response.ok:
        provider_id = response.json().get("messages", [{}])[0].get("id", "")
        log_message(db, phone, "out", log_text, related_type, related_id, status="sent")
        return NotificationResult(status="sent", provider_message_id=provider_id)

    log_message(db, phone, "out", log_text, related_type, related_id, status="failed")
    return NotificationResult(status="failed", error=response.text)


def send_whatsapp_template(
    db,
    phone: str,
    template_name: str,
    language_code: str = None,
    components: Optional[List[dict]] = None,
    related_type: str = None,
    related_id: int = None,
) -> NotificationResult:
    """Send a WhatsApp template message."""
    phone = normalize_phone(phone)
    if not phone:
        log_message(db, phone or "", "out", f"[Template: {template_name}]", related_type, related_id, status="skipped")
        return NotificationResult(status="skipped", error="missing phone")

    if not template_name:
        log_message(db, phone, "out", "[Template: missing]", related_type, related_id, status="skipped")
        return NotificationResult(status="skipped", error="missing template")

    if not _is_live():
        log_message(db, phone, "out", f"[Template: {template_name}]", related_type, related_id, status="sent")
        return NotificationResult(status="sent")

    url = f"https://graph.facebook.com/{META_API_VERSION}/{META_PHONE_NUMBER_ID}/messages"
    template = {
        "name": template_name,
        "language": {"code": language_code or META_DEFAULT_TEMPLATE_LANGUAGE},
    }
    if components:
        template["components"] = components
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "template",
        "template": template,
    }
    response = requests.post(url, json=payload, headers=_headers_json(), timeout=30)
    if response.ok:
        provider_id = response.json().get("messages", [{}])[0].get("id", "")
        log_message(db, phone, "out", f"[Template: {template_name}]", related_type, related_id, status="sent")
        return NotificationResult(status="sent", provider_message_id=provider_id)

    log_message(db, phone, "out", f"[Template: {template_name}]", related_type, related_id, status="failed")
    return NotificationResult(status="failed", error=response.text)


# ── helpers ───────────────────────────────────────────────────────────────────

def send_internal_alert(db, message: str, related_type: str = None, related_id: int = None):
    return send_whatsapp_message(db, INTERNAL_ALERT_NUMBER, message, related_type, related_id)


def business_number():
    return BUSINESS_WHATSAPP_NUMBER


def customer_welcome_template():
    return CUSTOMER_WELCOME_TEMPLATE
