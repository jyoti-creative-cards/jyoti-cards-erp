"""
WhatsApp webhook server — production version (WSGI, served by gunicorn).

Usage:
    gunicorn webhook_server:application --bind 0.0.0.0:$PORT --workers 1 --timeout 60

Security: only phones registered in the customers table can interact.
Structured order format from stock site: ORDER|SKU:1234|QTY:10

Menu (registered customers):
    1. Place Order          → prompts for SKU + qty or ORDER|SKU:x|QTY:y message
    2. Check Order Status   → asks for order ID
    3. My Orders (last 5)   → lists recent orders with status
    4. Talk to Team         → alerts owner
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs

from config import (
    META_WEBHOOK_PATH,
    META_WEBHOOK_PORT,
    META_WEBHOOK_VERIFY_TOKEN,
    META_ACCESS_TOKEN,
    META_PHONE_NUMBER_ID,
    META_API_VERSION,
    BUSINESS_WHATSAPP_NUMBER,
    INTERNAL_ALERT_NUMBER,
    STOCK_SITE_URL as _CFG_STOCK_SITE_URL,
)

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
WEBHOOK_LOG_PATH = LOG_DIR / "whatsapp_webhooks.jsonl"

STOCK_SITE_URL = os.getenv("STOCK_SITE_URL", _CFG_STOCK_SITE_URL) or "https://jyoti-cards-stock.onrender.com"
_DB_READY = False


def _ensure_db_ready():
    global _DB_READY
    if _DB_READY:
        return
    from db.database import init_db
    init_db()
    _DB_READY = True


# ─── WhatsApp sender ──────────────────────────────────────────────────────────

import urllib.request, urllib.error


def _wa_post(payload: dict) -> dict:
    url  = f"https://graph.facebook.com/{META_API_VERSION}/{META_PHONE_NUMBER_ID}/messages"
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(url, data=data, headers={
        "Authorization": f"Bearer {META_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"[WA ERROR] {e.code}: {body}", flush=True)
        return {"error": body}
    except Exception as e:
        print(f"[WA EXC] {e}", flush=True)
        return {"error": str(e)}


def wa_text(to: str, text: str) -> dict:
    result = _wa_post({
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {"body": text, "preview_url": False},
    })
    _log_wa(to, "outbound", text, status=("failed" if "error" in result else "sent"))
    return result


def wa_buttons(to: str, body: str, buttons: list, header: str = None, footer: str = None) -> dict:
    msg = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": b["id"], "title": b["title"][:20]}}
                    for b in buttons[:3]
                ]
            },
        },
    }
    if header:
        msg["interactive"]["header"] = {"type": "text", "text": header[:60]}
    if footer:
        msg["interactive"]["footer"] = {"text": footer[:60]}
    result = _wa_post(msg)
    _log_wa(to, "outbound", body, status=("failed" if "error" in result else "sent"))
    return result


# ─── DB helpers (SQLAlchemy SessionLocal) ────────────────────────────────────

def _get_db():
    _ensure_db_ready()
    from db.database import SessionLocal
    return SessionLocal()


def _normalise_phone(phone: str) -> str:
    """Strip +, spaces, country code — return last 10 digits."""
    digits = re.sub(r"\D", "", phone or "")
    return digits[-10:]


def _get_customer(phone: str):
    """Return Customer whose whatsapp_phone or phone matches last 10 digits."""
    from db.models import Customer
    local = _normalise_phone(phone)
    if not local:
        return None
    db = _get_db()
    try:
        for cust in db.query(Customer).all():
            wp = _normalise_phone(cust.whatsapp_phone or "")
            ph = _normalise_phone(cust.phone or "")
            if wp == local or ph == local:
                return cust
        return None
    finally:
        db.close()


def _log_wa(phone: str, direction: str, message: str, related_type=None, related_id=None, status: str = "sent"):
    from db.models import WhatsAppLog
    db = _get_db()
    try:
        db.add(WhatsAppLog(phone=phone, direction=direction, message=(message or "")[:2000],
                           related_type=related_type, related_id=related_id, status=status))
        db.commit()
    except Exception as e:
        print(f"[LOG ERROR] {e}", flush=True)
    finally:
        db.close()


def _upsert_conversation(phone: str, customer_id=None, intent: str = None):
    from db.models import WhatsAppConversation
    db = _get_db()
    try:
        conv = db.query(WhatsAppConversation).filter(WhatsAppConversation.phone == phone).first()
        now  = datetime.utcnow()
        if conv:
            conv.last_message_at = now
            conv.last_intent     = intent
            if customer_id:
                conv.customer_id = customer_id
        else:
            db.add(WhatsAppConversation(phone=phone, customer_id=customer_id,
                                        last_message_at=now, last_intent=intent))
        db.commit()
    finally:
        db.close()


def _get_last_intent(phone: str) -> str | None:
    from db.models import WhatsAppConversation
    db = _get_db()
    try:
        conv = db.query(WhatsAppConversation).filter(WhatsAppConversation.phone == phone).first()
        return conv.last_intent if conv else None
    finally:
        db.close()


def _get_product_by_sku(sku: str):
    from db.models import Product, Inventory
    db = _get_db()
    try:
        p = db.query(Product).filter(Product.sku == sku.strip(), Product.active.is_(True)).first()
        if not p:
            return None, 0
        inv = db.query(Inventory).filter(Inventory.product_id == p.id).first()
        stock = inv.quantity_available if inv else 0
        return p, stock
    finally:
        db.close()


def _create_order(customer_id: int, product_id: int, quantity: float, sku: str) -> int:
    from services.sales import create_sales_order
    from services.products import get_product
    db = _get_db()
    try:
        p = get_product(db, product_id)
        so = create_sales_order(
            db,
            customer_id=customer_id,
            items=[{"product_id": product_id, "quantity": quantity,
                    "unit_price": p.selling_price, "discount_percent": 0}],
            channel="whatsapp",
            notes=f"WhatsApp order. SKU: {sku}",
        )
        return so.id
    finally:
        db.close()


def _get_recent_orders(customer_id: int, limit: int = 5) -> list:
    from db.models import SalesOrder
    db = _get_db()
    try:
        orders = (db.query(SalesOrder)
                  .filter(SalesOrder.customer_id == customer_id)
                  .order_by(SalesOrder.created_at.desc())
                  .limit(limit).all())
        result = []
        for o in orders:
            items_text = ", ".join(
                f"{item.product.name} x{item.quantity:.0f}"
                for item in o.items if item.product
            )
            result.append({
                "id": o.id,
                "status": o.status.value if hasattr(o.status, "value") else o.status,
                "date": str(o.order_date),
                "total": o.total_amount,
                "items": items_text,
            })
        return result
    finally:
        db.close()


def _get_order_by_id(customer_id: int, order_id: int):
    from db.models import SalesOrder
    db = _get_db()
    try:
        o = (db.query(SalesOrder)
               .filter(SalesOrder.id == order_id, SalesOrder.customer_id == customer_id)
               .first())
        if not o:
            return None
        items_text = ", ".join(
            f"{item.product.name} x{item.quantity:.0f}"
            for item in o.items if item.product
        )
        return {
            "id": o.id,
            "status": o.status.value if hasattr(o.status, "value") else o.status,
            "date": str(o.order_date),
            "total": o.total_amount,
            "items": items_text,
        }
    finally:
        db.close()


# ─── Session state (in-memory per phone) ──────────────────────────────────────
# _pending_orders: cart awaiting confirm
# _session_state: current menu/step e.g. "awaiting_order_id", "awaiting_sku"
_pending_orders: dict = {}
_session_state: dict = {}


# ─── Bot logic ────────────────────────────────────────────────────────────────

STATUS_EMOJI = {
    "created": "🆕", "pending": "⏳", "confirmed": "✅",
    "packed": "📦", "dispatched": "🚚", "delivered": "📬", "cancelled": "❌",
}


def _main_menu_text(customer_name: str) -> str:
    return (
        f"Hi *{customer_name}*! 👋\n\n"
        f"*Jyoti Creative Cards*\n\n"
        f"1️⃣  Place Order\n"
        f"2️⃣  Check Order Status\n"
        f"3️⃣  My Orders (last 5)\n"
        f"4️⃣  Talk to Team\n\n"
        f"Reply with a number (1-4) to continue.\n"
        f"Stock: {STOCK_SITE_URL}"
    )


def _not_registered_reply(phone: str):
    wa_text(phone,
        "Sorry, your number is not registered with us. 🙏\n\n"
        "You are not registered. Please contact us:\n"
        f"📞 *+91 {BUSINESS_WHATSAPP_NUMBER[-10:]}*\n"
        "⏰ Mon–Sat, 10am–7pm"
    )
    _upsert_conversation(phone, None, "rejected_unregistered")


def handle_message(phone: str, text: str, interactive_id: str = None):
    text = (text or "").strip()
    msg  = (interactive_id or text).lower().strip()

    _log_wa(phone, "inbound", text or interactive_id or "")

    # ── Security gate — registered customers only ─────────────────────────────
    customer = _get_customer(phone)
    if not customer:
        _not_registered_reply(phone)
        return

    cid    = customer.id
    cname  = customer.name
    state  = _session_state.get(phone, {})

    # ── Structured order from stock site: ORDER|SKU:1234|QTY:10 ──────────────
    order_match = re.match(r"ORDER\|SKU:([^\|]+)\|QTY:(\d+(?:\.\d+)?)", text, re.IGNORECASE)
    if order_match:
        sku = order_match.group(1).strip()
        qty = float(order_match.group(2))
        _session_state.pop(phone, None)
        _handle_structured_order(phone, customer, sku, qty)
        return

    # ── Greetings / menu shortcuts ────────────────────────────────────────────
    if msg in ("hi", "hello", "hii", "hey", "start", "menu", "namaste", "jai jinendra", "home", "0"):
        _session_state.pop(phone, None)
        wa_text(phone, _main_menu_text(cname))
        _upsert_conversation(phone, cid, "welcome")
        return

    # ── Confirm / cancel of a pending cart ────────────────────────────────────
    if interactive_id == "confirm_order" or msg in ("confirm", "haan", "yes", "ok"):
        if phone in _pending_orders:
            _finalise_order(phone, customer)
            _session_state.pop(phone, None)
            return

    if interactive_id == "cancel_order" or msg in ("cancel", "nahi", "no"):
        if phone in _pending_orders:
            _pending_orders.pop(phone, None)
            wa_text(phone, "Order cancelled. 😊\n\n" + _main_menu_text(cname))
            _upsert_conversation(phone, cid, "cancelled")
            _session_state.pop(phone, None)
            return

    # ── Multi-step state: awaiting order ID for option 2 ──────────────────────
    if state.get("step") == "awaiting_order_id":
        _session_state.pop(phone, None)
        digits = re.sub(r"\D", "", text)
        if not digits:
            wa_text(phone, "That doesn't look like a valid order number. Try again or type *menu*.")
            return
        order = _get_order_by_id(cid, int(digits))
        if not order:
            wa_text(phone,
                f"No order *#{digits}* found under your account.\n"
                f"Type *3* to see your recent orders, or *menu* to go back."
            )
            return
        em = STATUS_EMOJI.get(order["status"], "📋")
        wa_text(phone,
            f"{em} *Order #{order['id']}*\n"
            f"Date: {order['date']}\n"
            f"Items: {order['items']}\n"
            f"Total: ₹{order['total']:,.0f}\n"
            f"Status: *{order['status'].upper()}*\n\n"
            f"Type *menu* for more options."
        )
        _upsert_conversation(phone, cid, "order_status_result")
        return

    # ── Multi-step state: awaiting SKU+qty for option 1 ───────────────────────
    if state.get("step") == "awaiting_sku":
        _session_state.pop(phone, None)
        # Accept "SKU QTY" or "SKU:xxx QTY:yy" forms
        m = re.search(r"([A-Za-z0-9\-_]+)\D+(\d+(?:\.\d+)?)", text)
        if not m:
            wa_text(phone,
                "Please send your order like:\n"
                "`ORDER|SKU:1234|QTY:10`\n"
                "or just: *1234 10*\n\n"
                "Or browse stock: " + STOCK_SITE_URL
            )
            return
        sku = m.group(1).strip()
        qty = float(m.group(2))
        _handle_structured_order(phone, customer, sku, qty)
        return

    # ── Menu options 1-4 ──────────────────────────────────────────────────────
    if msg in ("1", "1️⃣", "place order", "order"):
        _session_state[phone] = {"step": "awaiting_sku"}
        wa_text(phone,
            "*Place Order* 📦\n\n"
            "Please reply with SKU and quantity, e.g.:\n"
            "`ORDER|SKU:1234|QTY:10`\n"
            "or just: *1234 10*\n\n"
            f"Browse products: {STOCK_SITE_URL}\n"
            "Type *menu* to cancel."
        )
        _upsert_conversation(phone, cid, "awaiting_sku")
        return

    if msg in ("2", "2️⃣", "check order status", "order status", "status"):
        _session_state[phone] = {"step": "awaiting_order_id"}
        wa_text(phone,
            "*Check Order Status* 🔍\n\n"
            "Please send your Order ID (numbers only), e.g. *123*.\n\n"
            "Type *3* to see your recent orders, or *menu* to cancel."
        )
        _upsert_conversation(phone, cid, "awaiting_order_id")
        return

    if msg in ("3", "3️⃣", "my orders", "history", "recent"):
        _session_state.pop(phone, None)
        _send_recent_orders(phone, customer)
        return

    if msg in ("4", "4️⃣", "talk to team", "support", "help"):
        _session_state.pop(phone, None)
        wa_text(phone,
            "Our team will reach out shortly. 😊\n\n"
            f"📞 Call: *+91 {BUSINESS_WHATSAPP_NUMBER[-10:]}*\n"
            "⏰ Mon–Sat, 10am–7pm"
        )
        # Notify internal owner
        alert_phone = "91" + (INTERNAL_ALERT_NUMBER or BUSINESS_WHATSAPP_NUMBER)[-10:]
        wa_text(alert_phone,
            f"🔔 *Customer support request*\n"
            f"Customer: {cname}\n"
            f"Phone: {phone}\n"
            f"Please call back."
        )
        _upsert_conversation(phone, cid, "support")
        return

    # ── Fallback — show the menu again ────────────────────────────────────────
    wa_text(phone, _main_menu_text(cname))
    _upsert_conversation(phone, cid, "welcome")


def _handle_structured_order(phone: str, customer, sku: str, qty: float):
    product, stock = _get_product_by_sku(sku)

    if not product:
        wa_text(phone, f"SKU *{sku}* not found. Please check on the stock site:\n{STOCK_SITE_URL}")
        return

    if stock <= 0:
        wa_text(phone, f"*{product.name}* (SKU: {sku}) is currently out of stock. 😔\nPlease check other products:\n{STOCK_SITE_URL}")
        return

    if qty > stock:
        wa_text(phone,
            f"*{product.name}* has only *{stock:.0f} pcs* available.\n"
            f"You asked for *{qty:.0f} pcs* — please reduce the quantity."
        )
        return

    total = product.selling_price * qty
    _pending_orders[phone] = {
        "product_id": product.id,
        "sku": sku,
        "name": product.name,
        "qty": qty,
        "price": product.selling_price,
        "customer_id": customer.id,
    }

    wa_buttons(phone,
        header=f"Order for {customer.name}",
        body=(
            f"*Confirm Your Order:*\n\n"
            f"📦 Product: *{product.name}*\n"
            f"🔢 SKU: {sku}\n"
            f"🔢 Quantity: *{qty:.0f} pcs*\n"
            f"💰 Price: ₹{product.selling_price:.0f}/pcs\n"
            f"💰 Total: *₹{total:.0f}*\n\n"
            f"Shall we confirm?"
        ),
        buttons=[
            {"id": "confirm_order", "title": "✅ Confirm"},
            {"id": "cancel_order",  "title": "❌ Cancel"},
        ],
        footer="Stock will be deducted on confirm"
    )
    _upsert_conversation(phone, customer.id, "awaiting_confirm")


def _finalise_order(phone: str, customer):
    po = _pending_orders.get(phone)
    if not po:
        return
    try:
        so_id = _create_order(
            customer_id=po["customer_id"],
            product_id=po["product_id"],
            quantity=po["qty"],
            sku=po["sku"],
        )
        total = po["qty"] * po["price"]
        msg   = (
            f"✅ *Order Confirmed!*\n\n"
            f"Order ID: *#{so_id}*\n"
            f"📦 {po['name']} × {po['qty']:.0f} pcs\n"
            f"💰 Total: *₹{total:.0f}*\n\n"
            f"Our team will process it shortly.\n"
            f"Type *2* to check status, or *menu* for options.\n"
            f"📞 +91 {BUSINESS_WHATSAPP_NUMBER[-10:]}"
        )
        wa_text(phone, msg)
        _log_wa(phone, "outbound", msg, "sales_order", so_id)
        _pending_orders.pop(phone, None)
        _upsert_conversation(phone, customer.id, "order_placed")

    except ValueError as e:
        wa_text(phone, f"Order could not be placed: {e}\nPlease call: +91 {BUSINESS_WHATSAPP_NUMBER[-10:]}")
    except Exception as e:
        print(f"[ORDER ERROR] {e}", flush=True)
        import traceback; traceback.print_exc()
        wa_text(phone, "Something went wrong. Please call: +91 " + BUSINESS_WHATSAPP_NUMBER[-10:])


def _send_recent_orders(phone: str, customer):
    orders = _get_recent_orders(customer.id, limit=5)
    if not orders:
        wa_text(phone,
            "You have no orders yet.\n\n"
            f"Browse stock: {STOCK_SITE_URL}\n"
            "Type *menu* for options."
        )
        _upsert_conversation(phone, customer.id, "no_orders")
        return

    lines = [f"📋 *{customer.name} — Last {len(orders)} orders:*\n"]
    for o in orders:
        em = STATUS_EMOJI.get(o["status"], "📋")
        lines.append(
            f"{em} *#{o['id']}* — {o['date']}\n"
            f"   {o['items']}\n"
            f"   ₹{o['total']:,.0f} | *{o['status'].upper()}*\n"
        )
    lines.append("\nType *2* + order ID for details, or *menu* to go back.")
    wa_text(phone, "\n".join(lines))
    _upsert_conversation(phone, customer.id, "order_history")


# ─── Notify endpoint (called by Streamlit ERP on status change) ───────────────

def notify_order_update(order_id: int, new_status: str):
    from db.models import SalesOrder
    db = _get_db()
    try:
        so = db.query(SalesOrder).filter(SalesOrder.id == order_id).first()
        if not so or not so.customer:
            return {"error": "order or customer not found"}
        c     = so.customer
        phone = (c.whatsapp_phone or c.phone or "").replace("+", "").replace(" ", "")
        if not phone:
            return {"error": "no phone"}
        if not phone.startswith("91"):
            phone = "91" + phone[-10:]

        msgs = {
            "confirmed":  f"✅ Order *#{order_id}* confirmed! We are preparing it.",
            "packed":     f"📦 Order *#{order_id}* packed! Dispatching soon.",
            "dispatched": f"🚚 Order *#{order_id}* dispatched! You should receive it in 1–2 days.",
            "delivered":  f"📬 Order *#{order_id}* delivered! Thank you 🙏\nJyoti Creative Cards",
            "cancelled":  f"❌ Order *#{order_id}* cancelled.\nCall: +91 {BUSINESS_WHATSAPP_NUMBER[-10:]}",
        }
        text = msgs.get(new_status, f"📋 Order *#{order_id}* status: *{new_status.upper()}*")
        wa_text(phone, text)
        _log_wa(phone, "outbound", text, "sales_order", order_id)
        return {"sent": True, "to": phone}
    finally:
        db.close()


# ─── WSGI app ─────────────────────────────────────────────────────────────────

def _read_body(environ) -> str:
    length = int(environ.get("CONTENT_LENGTH") or 0)
    return environ["wsgi.input"].read(length).decode("utf-8") if length > 0 else ""


def _json_resp(start_response, payload, status="200 OK"):
    body = json.dumps(payload, ensure_ascii=False).encode()
    start_response(status, [("Content-Type", "application/json"), ("Content-Length", str(len(body)))])
    return [body]


def _text_resp(start_response, text, status="200 OK"):
    body = text.encode()
    start_response(status, [("Content-Type", "text/plain"), ("Content-Length", str(len(body)))])
    return [body]


def _html_resp(start_response, html, status="200 OK"):
    body = html.encode()
    start_response(status, [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(body)))])
    return [body]


def _append_log(payload: dict):
    try:
        with WEBHOOK_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[LOG FILE ERROR] {e}", flush=True)


def application(environ, start_response):
    """WSGI entrypoint. Gunicorn will call this."""
    method = environ.get("REQUEST_METHOD", "GET")
    path   = environ.get("PATH_INFO", "/")
    query  = parse_qs(environ.get("QUERY_STRING", ""))

    if path in ("/health", "/"):
        return _json_resp(start_response, {"status": "ok", "service": "jyoti-cards-bot"})

    if path == "/privacy-policy":
        return _html_resp(start_response,
            "<html><body><h1>Privacy Policy — Jyoti Creative Cards</h1>"
            "<p>We collect contact and order data to process purchases and send WhatsApp notifications. "
            "Data is not sold. Contact: +91 76948 12345</p></body></html>"
        )

    if path == "/debug/webhooks":
        limit = int((query.get("limit") or ["20"])[0])
        rows  = []
        if WEBHOOK_LOG_PATH.exists():
            for line in WEBHOOK_LOG_PATH.read_text().splitlines()[-limit:]:
                try: rows.append(json.loads(line))
                except: rows.append({"raw": line})
        return _json_resp(start_response, {"rows": rows})

    if path == "/debug/whatsapp-logs":
        from db.models import WhatsAppLog
        limit = int((query.get("limit") or ["20"])[0])
        phone_filter = (query.get("phone") or [""])[0]
        db = _get_db()
        try:
            q = db.query(WhatsAppLog).order_by(WhatsAppLog.created_at.desc())
            if phone_filter:
                q = q.filter(WhatsAppLog.phone.like(f"%{phone_filter[-10:]}%"))
            rows = []
            for r in q.limit(limit).all():
                rows.append(
                    {
                        "id": r.id,
                        "phone": r.phone,
                        "direction": r.direction,
                        "message": r.message,
                        "status": r.status,
                        "related_type": r.related_type,
                        "related_id": r.related_id,
                        "created_at": r.created_at.isoformat() if r.created_at else None,
                    }
                )
            return _json_resp(start_response, {"rows": rows})
        finally:
            db.close()

    if path == "/notify/order-update" and method == "POST":
        try:
            data   = json.loads(_read_body(environ))
            result = notify_order_update(int(data["order_id"]), data["new_status"])
            return _json_resp(start_response, result)
        except Exception as e:
            return _json_resp(start_response, {"error": str(e)}, "400 Bad Request")

    if path != META_WEBHOOK_PATH:
        return _text_resp(start_response, "not found", "404 Not Found")

    # Webhook verify GET
    if method == "GET":
        mode      = (query.get("hub.mode") or [""])[0]
        token     = (query.get("hub.verify_token") or [""])[0]
        challenge = (query.get("hub.challenge") or [""])[0]
        if mode == "subscribe" and token == META_WEBHOOK_VERIFY_TOKEN:
            return _text_resp(start_response, challenge)
        return _text_resp(start_response, "forbidden", "403 Forbidden")

    # Incoming WhatsApp message POST
    if method == "POST":
        raw = _read_body(environ)
        try: body = json.loads(raw) if raw else {}
        except: body = {}

        _append_log({"received_at": datetime.now(timezone.utc).isoformat(), "event": body})

        try:
            for entry in body.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    for msg in value.get("messages", []):
                        phone  = msg.get("from", "")
                        mtype  = msg.get("type", "")
                        text   = ""
                        iid    = None
                        if mtype == "text":
                            text = msg.get("text", {}).get("body", "")
                        elif mtype == "interactive":
                            iv = msg.get("interactive", {})
                            it = iv.get("type", "")
                            if it == "button_reply":
                                iid  = iv["button_reply"]["id"]
                                text = iv["button_reply"]["title"]
                            elif it == "list_reply":
                                iid  = iv["list_reply"]["id"]
                                text = iv["list_reply"]["title"]
                        if phone:
                            handle_message(phone, text, iid)
        except Exception as e:
            print(f"[BOT ERROR] {e}", flush=True)
            import traceback; traceback.print_exc()

        return _json_resp(start_response, {"status": "received"})

    return _text_resp(start_response, "method not allowed", "405 Method Not Allowed")


# Backwards-compatible alias (some platforms look for `app`)
app = application


if __name__ == "__main__":
    # Dev fallback only — production uses gunicorn.
    # Run: gunicorn webhook_server:application --bind 0.0.0.0:$PORT --workers 1 --timeout 60
    import sys
    try:
        from gunicorn.app.base import BaseApplication

        class _StandaloneGunicorn(BaseApplication):
            def __init__(self, app, options):
                self.options = options
                self.application = app
                super().__init__()

            def load_config(self):
                for k, v in self.options.items():
                    self.cfg.set(k, v)

            def load(self):
                return self.application

        port = int(os.getenv("PORT", META_WEBHOOK_PORT))
        opts = {
            "bind": f"0.0.0.0:{port}",
            "workers": 1,
            "timeout": 60,
            "accesslog": "-",
            "errorlog": "-",
        }
        print(f"Bot (gunicorn) → http://0.0.0.0:{port}{META_WEBHOOK_PATH}", flush=True)
        _StandaloneGunicorn(application, opts).run()
    except ImportError:
        print("Gunicorn not installed — using wsgiref fallback (not for production).", file=sys.stderr)
        from wsgiref.simple_server import make_server
        port = int(os.getenv("PORT", META_WEBHOOK_PORT))
        print(f"Bot → http://0.0.0.0:{port}{META_WEBHOOK_PATH}")
        make_server("0.0.0.0", port, application).serve_forever()
