from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server

from config import META_WEBHOOK_PATH, META_WEBHOOK_PORT, META_WEBHOOK_VERIFY_TOKEN


ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
WEBHOOK_LOG_PATH = LOG_DIR / "whatsapp_webhooks.jsonl"


def _read_body(environ) -> str:
    length = int(environ.get("CONTENT_LENGTH") or 0)
    if length <= 0:
        return ""
    return environ["wsgi.input"].read(length).decode("utf-8")


def _json_response(start_response, payload: dict, status: str = "200 OK"):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    start_response(
        status,
        [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(body)))],
    )
    return [body]


def _text_response(start_response, text: str, status: str = "200 OK"):
    body = text.encode("utf-8")
    start_response(status, [("Content-Type", "text/plain; charset=utf-8"), ("Content-Length", str(len(body)))])
    return [body]


def _append_log(payload: dict):
    line = json.dumps(payload, ensure_ascii=False)
    with WEBHOOK_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(f"{line}\n")


def _event_summary(event: dict) -> dict:
    summary = {
        "messages": [],
        "statuses": [],
        "errors": [],
    }
    for entry in event.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value", {}) or {}
            for msg in value.get("messages", []) or []:
                summary["messages"].append(
                    {
                        "from": msg.get("from"),
                        "id": msg.get("id"),
                        "type": msg.get("type"),
                    }
                )
            for status in value.get("statuses", []) or []:
                summary["statuses"].append(
                    {
                        "id": status.get("id"),
                        "status": status.get("status"),
                        "recipient_id": status.get("recipient_id"),
                    }
                )
                for err in status.get("errors", []) or []:
                    summary["errors"].append(
                        {
                            "code": err.get("code"),
                            "title": err.get("title"),
                            "message": err.get("message"),
                        }
                    )
    return summary


def _read_recent_logs(limit: int = 20) -> list[dict]:
    if not WEBHOOK_LOG_PATH.exists():
        return []
    lines = WEBHOOK_LOG_PATH.read_text(encoding="utf-8").splitlines()
    recent = lines[-max(limit, 1):]
    rows = []
    for line in recent:
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            rows.append({"raw": line})
    return rows


def app(environ, start_response):
    method = environ.get("REQUEST_METHOD", "GET")
    path = environ.get("PATH_INFO", "/")
    query = parse_qs(environ.get("QUERY_STRING", ""))

    if path == "/health":
        return _json_response(start_response, {"status": "ok"})

    if path == "/debug/webhooks":
        limit = int((query.get("limit") or ["20"])[0] or "20")
        return _json_response(start_response, {"rows": _read_recent_logs(limit)})

    if path != META_WEBHOOK_PATH:
        return _text_response(start_response, "not found", "404 Not Found")

    if method == "GET":
        mode = (query.get("hub.mode") or [""])[0]
        token = (query.get("hub.verify_token") or [""])[0]
        challenge = (query.get("hub.challenge") or [""])[0]
        if mode == "subscribe" and token == META_WEBHOOK_VERIFY_TOKEN:
            return _text_response(start_response, challenge, "200 OK")
        return _text_response(start_response, "forbidden", "403 Forbidden")

    if method == "POST":
        raw_body = _read_body(environ)
        try:
            body = json.loads(raw_body) if raw_body else {}
        except json.JSONDecodeError:
            body = {"raw_body": raw_body}

        record = {
            "received_at": datetime.now(timezone.utc).isoformat(),
            "event": body,
            "summary": _event_summary(body),
        }
        _append_log(record)
        print(json.dumps({"webhook_event": record["summary"]}, ensure_ascii=False), flush=True)
        return _json_response(start_response, {"status": "received"})

    return _text_response(start_response, "method not allowed", "405 Method Not Allowed")


if __name__ == "__main__":
    print(f"WhatsApp webhook running on http://0.0.0.0:{META_WEBHOOK_PORT}{META_WEBHOOK_PATH}")
    print(f"Verify token: {META_WEBHOOK_VERIFY_TOKEN}")
    print(f"Webhook logs: {WEBHOOK_LOG_PATH}")
    server = make_server("0.0.0.0", META_WEBHOOK_PORT, app)
    server.serve_forever()
