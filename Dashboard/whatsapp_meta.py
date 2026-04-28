"""Meta WhatsApp Cloud API — `send_wa_template(key, ...)`. Each template: `templates/<name>.py` + `wa_templates`."""
from __future__ import annotations

import json
import mimetypes
import os
import re
import sys
import uuid
import urllib.error
import urllib.request
from typing import Any, Optional

from wa_templates import get_wa_template

_DASH = os.path.dirname(os.path.abspath(__file__))
_ENV_PATH = os.path.join(_DASH, ".env")


def _load_env() -> None:
    if not os.path.isfile(_ENV_PATH):
        return
    try:
        from dotenv import load_dotenv

        load_dotenv(_ENV_PATH, override=True)
    except ImportError:
        with open(_ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, rest = line.partition("=")
                k, v = k.strip(), rest.strip()
                if k and v is not None:
                    os.environ[k] = v


_load_env()


def normalize_whatsapp_e164(phone: str, default_cc: str = "91") -> Optional[str]:
    t = re.sub(r"\D+", "", (phone or "").strip())
    if not t:
        return None
    if len(t) == 10 and default_cc:
        t = f"{default_cc}{t}"
    if len(t) < 8:
        return None
    return t


def _upload_image_media(phone_id: str, access_token: str, api_version: str, file_path: str) -> Optional[str]:
    if not file_path or not os.path.isfile(file_path):
        return None
    url = f"https://graph.facebook.com/{api_version}/{phone_id}/media"
    ctype, _ = mimetypes.guess_type(file_path)
    if not ctype or not (ctype.startswith("image/") or ctype == "application/pdf"):
        ctype = "image/jpeg"
    with open(file_path, "rb") as f:
        data = f.read()
    name = os.path.basename(file_path) or "receipt.jpg"
    boundary = f"----{uuid.uuid4().hex}"
    sep = f"--{boundary}\r\n".encode("ascii")
    ctn = ctype or "image/jpeg"
    # multipart: messaging_product, type, file
    body = (
        sep
        + b'Content-Disposition: form-data; name="messaging_product"\r\n\r\n'
        + b"whatsapp\r\n"
        + sep
        + b'Content-Disposition: form-data; name="type"\r\n\r\n'
        + ctn.encode("utf-8")
        + b"\r\n"
        + sep
        + b'Content-Disposition: form-data; name="file"; filename="'
        + name.encode("utf-8", errors="replace")
        + b'"\r\nContent-Type: '
        + ctn.encode("utf-8")
        + b"\r\n\r\n"
        + data
        + f"\r\n--{boundary}--\r\n".encode("ascii")
    )
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            o = json.loads((r.read() or b"{}").decode() or "{}")
    except (urllib.error.HTTPError, OSError) as e:
        print("WhatsApp media upload failed:", e, file=sys.stderr)
        if isinstance(e, urllib.error.HTTPError) and e.fp is not None:
            try:
                print(e.read().decode(), file=sys.stderr)
            except OSError:
                pass
        return None
    mid = o.get("id") if isinstance(o, dict) else None
    return str(mid) if mid else None


def _body_parameters(
    tdef: dict[str, Any], body: dict[str, str]
) -> list[dict[str, str]]:
    keys = tdef.get("body_keys") or ()
    # "named" = {{name}} in Manager; "positional" = {{1}} {{2}} ("Number" variables)
    style = (tdef.get("param_style") or "named").lower()
    out: list[dict[str, str]] = []
    for k in keys:
        text = body.get(k) or "—"
        if len(text) > 1024:
            text = text[:1024]
        if style == "named":
            out.append({"type": "text", "text": text, "parameter_name": k})
        else:
            out.append({"type": "text", "text": text})
    return out


def send_wa_template(
    template_key: str,
    recipient_phone: str,
    body: dict[str, Any],
    *,
    header_image_path: Optional[str] = None,
) -> dict[str, Any]:
    """
    Send an approved template to `recipient_phone` (row phone; normalized to E.164).
    `body` must include every `body_keys` for that template (see `Dashboard/templates/*.py`).
    `header_image_path` — if template SPEC has `header: "image"`, file is uploaded and
    prepended to `components` (optional if `header_optional: True` in SPEC).
    """
    _load_env()
    tdef = get_wa_template(template_key)
    if not tdef:
        return {"ok": False, "error": f"unknown template key: {template_key}"}
    to = normalize_whatsapp_e164(recipient_phone)
    if not to:
        return {"ok": False, "error": "invalid phone"}
    keys = tuple(tdef.get("body_keys") or ())
    missing = [k for k in keys if k not in body]
    if missing:
        return {"ok": False, "error": f"body missing keys: {missing}"}
    # str for JSON; keep numeric 0 as "0" (not truthy-bug to "—")
    body_str: dict[str, str] = {}
    for k in keys:
        v = body[k]
        body_str[k] = "—" if v is None else str(v)[:1024]
    ver = (os.environ.get("WHATSAPP_API_VERSION") or "v21.0").strip()
    pn = (os.environ.get("WHATSAPP_PHONE_NUMBER_ID") or "").strip()
    tok = (os.environ.get("WHATSAPP_ACCESS_TOKEN") or "").strip()
    if not tok or not pn:
        return {"ok": False, "error": "missing WHATSAPP_ACCESS_TOKEN or WHATSAPP_PHONE_NUMBER_ID"}
    tpl = (tdef.get("name") or "").strip()
    lang = (tdef.get("language") or "hi").strip()
    if not tpl:
        return {"ok": False, "error": "template name empty in templates/<name>.py SPEC"}
    url = f"https://graph.facebook.com/{ver}/{pn}/messages"
    params = _body_parameters(tdef, body_str)
    head_kind = (tdef.get("header") or "").strip().lower()
    comp: list[dict[str, Any]] = []
    media_id: Optional[str] = None
    if head_kind == "image" and header_image_path and os.path.isfile(header_image_path):
        media_id = _upload_image_media(pn, tok, ver, header_image_path)
    if head_kind == "image" and media_id:
        comp.append(
            {
                "type": "header",
                "parameters": [
                    {
                        "type": "image",
                        "image": {"id": media_id},
                    }
                ],
            }
        )
    elif head_kind == "image" and not tdef.get("header_optional"):
        return {
            "ok": False,
            "error": "this template needs a header image (or set header_optional in template SPEC)",
        }
    comp.append({"type": "body", "parameters": params})
    payload: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "template",
        "template": {
            "name": tpl,
            "language": {"code": lang},
            "components": comp,
        },
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {tok}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return {"ok": True, "response": json.loads(r.read().decode() or "{}")}
    except urllib.error.HTTPError as e:
        return {"ok": False, "http": e.code, "error": (e.read().decode() if e.fp else "") or str(e)}


def send_wa_template_safe(
    template_key: str,
    recipient_phone: str,
    body: dict[str, Any],
    *,
    header_image_path: Optional[str] = None,
) -> None:
    r = send_wa_template(
        template_key, recipient_phone, body, header_image_path=header_image_path
    )
    if r.get("ok") is not True:
        print("WhatsApp send failed:", r, file=sys.stderr)


def send_wa_for_new_account_safe(
    customer_name: str, phone: str, password_plain: str
) -> None:
    """Convenience: `account_creation` with {{name}}, {{phone}}, {{password}} (digits for login)."""
    uid = re.sub(r"\D+", "", (phone or "").strip()) or (normalize_whatsapp_e164(phone) or "")[-10:]
    send_wa_template_safe(
        "account_creation",
        phone,
        {
            "name": customer_name.strip() or "Customer",
            "phone": uid,
            "password": password_plain,
        },
    )
