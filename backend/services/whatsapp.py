from __future__ import annotations

from dataclasses import dataclass
import base64
import requests

from config import (
    BUSINESS_WHATSAPP_NUMBER,
    INTERNAL_ALERT_NUMBER,
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


def send_whatsapp_message(db, phone: str, message: str, related_type: str = None, related_id: int = None) -> NotificationResult:
    if not phone:
        log_message(db, phone or "", "out", message, related_type, related_id, status="skipped")
        return NotificationResult(status="skipped", error="missing phone")

    if WHATSAPP_PROVIDER != "meta" or not META_ACCESS_TOKEN or not META_PHONE_NUMBER_ID:
        log_message(db, phone, "out", message, related_type, related_id, status="sent")
        return NotificationResult(status="sent")

    url = f"https://graph.facebook.com/{META_API_VERSION}/{META_PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "text",
        "text": {"body": message},
    }
    headers = {
        "Authorization": f"Bearer {META_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    response = requests.post(url, json=payload, headers=headers, timeout=30)
    if response.ok:
        provider_id = response.json().get("messages", [{}])[0].get("id", "")
        log_message(db, phone, "out", message, related_type, related_id, status="sent")
        return NotificationResult(status="sent", provider_message_id=provider_id)

    log_message(db, phone, "out", message, related_type, related_id, status="failed")
    return NotificationResult(status="failed", error=response.text)


def send_whatsapp_document(db, phone: str, filename: str, file_bytes: bytes, caption: str = "", related_type: str = None, related_id: int = None) -> NotificationResult:
    if not phone:
        log_message(db, phone or "", "out", f"DOCUMENT:{filename}", related_type, related_id, status="skipped")
        return NotificationResult(status="skipped", error="missing phone")

    if WHATSAPP_PROVIDER != "meta" or not META_ACCESS_TOKEN or not META_PHONE_NUMBER_ID:
        log_message(db, phone, "out", f"DOCUMENT:{filename}", related_type, related_id, status="sent")
        return NotificationResult(status="sent")

    media_url = f"https://graph.facebook.com/{META_API_VERSION}/{META_PHONE_NUMBER_ID}/media"
    headers = {"Authorization": f"Bearer {META_ACCESS_TOKEN}"}
    files = {
        "file": (filename, file_bytes, "application/pdf"),
        "messaging_product": (None, "whatsapp"),
        "type": (None, "application/pdf"),
    }
    upload_response = requests.post(media_url, headers=headers, files=files, timeout=60)
    if not upload_response.ok:
        log_message(db, phone, "out", f"DOCUMENT:{filename}", related_type, related_id, status="failed")
        return NotificationResult(status="failed", error=upload_response.text)

    media_id = upload_response.json().get("id", "")
    message_url = f"https://graph.facebook.com/{META_API_VERSION}/{META_PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "document",
        "document": {"id": media_id, "filename": filename, "caption": caption},
    }
    response = requests.post(message_url, json=payload, headers={**headers, "Content-Type": "application/json"}, timeout=30)
    if response.ok:
        provider_id = response.json().get("messages", [{}])[0].get("id", "")
        log_message(db, phone, "out", f"DOCUMENT:{filename}", related_type, related_id, status="sent")
        return NotificationResult(status="sent", provider_message_id=provider_id)

    log_message(db, phone, "out", f"DOCUMENT:{filename}", related_type, related_id, status="failed")
    return NotificationResult(status="failed", error=response.text)


def send_internal_alert(db, message: str, related_type: str = None, related_id: int = None):
    return send_whatsapp_message(db, INTERNAL_ALERT_NUMBER, message, related_type, related_id)


def business_number():
    return BUSINESS_WHATSAPP_NUMBER
