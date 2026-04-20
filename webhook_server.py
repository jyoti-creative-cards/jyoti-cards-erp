"""
WhatsApp webhook server — production version.
Uses the same SQLAlchemy models as the ERP.
Security: only phones registered in customers table can place orders.
Structured order format from stock site: ORDER|SKU:1234|QTY:10
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server

from config import (
    META_WEBHOOK_PATH,
    META_WEBHOOK_PORT,
    META_WEBHOOK_VERIFY_TOKEN,
    META_ACCESS_TOKEN,
    META_PHONE_NUMBER_ID,
    META_API_VERSION,
    BUSINESS_WHATSAPP_NUMBER,
)

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
WEBHOOK_LOG_PATH = LOG_DIR / "whatsapp_webhooks.jsonl"

# Stock check website URL — update after deploying stock app
STOCK_SITE_URL = "https://jyoti-cards-stock.onrender.com"


# ─── WhatsApp sender (no async needed in WSGI) ───────────────────────────────

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

def wa_text(to: str, text: str) -> dict:
    return _wa_post({
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {"body": text, "preview_url": False},
    })

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
    return _wa_post(msg)


# ─── DB helpers (use existing SQLAlchemy stack) ───────────────────────────────

def _get_db():
    from db.database import SessionLocal
    return SessionLocal()

def _normalise_phone(phone: str) -> str:
    """Strip +, spaces, leading 91 — return last 10 digits."""
    digits = re.sub(r"\D", "", phone)
    return digits[-10:]

def _get_customer(phone: str):
    """Return Customer or None. Matches on whatsapp_phone or phone (last 10 digits)."""
    from db.models import Customer
    local = _normalise_phone(phone)
    db = _get_db()
    try:
        # Try exact match first
        c = db.query(Customer).filter(Customer.whatsapp_phone == phone).first()
        if c:
            return c
        # Try last-10-digit match
        all_c = db.query(Customer).all()
        for cust in all_c:
            wp = _normalise_phone(cust.whatsapp_phone or "")
            ph = _normalise_phone(cust.phone or "")
            if wp == local or ph == local:
                return cust
        return None
    finally:
        db.close()

def _log_wa(phone: str, direction: str, message: str, related_type=None, related_id=None):
    from db.models import WhatsAppLog
    db = _get_db()
    try:
        db.add(WhatsAppLog(phone=phone, direction=direction, message=message[:2000],
                           related_type=related_type, related_id=related_id, status="sent"))
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
    """Create sales order, deduct stock, return SO id."""
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
            notes=f"WhatsApp order via stock site. SKU: {sku}",
        )
        return so.id
    finally:
        db.close()

def _get_recent_orders(customer_id: int) -> list:
    from db.models import SalesOrder, SalesOrderItem, Product
    db = _get_db()
    try:
        orders = (db.query(SalesOrder)
                  .filter(SalesOrder.customer_id == customer_id)
                  .order_by(SalesOrder.created_at.desc())
                  .limit(5).all())
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


# ─── Cart (in-memory, keyed by phone) ────────────────────────────────────────
# Format: {phone: {"product_id", "sku", "name", "qty", "price", "customer_id"}}
_pending_orders: dict = {}


# ─── Bot logic ────────────────────────────────────────────────────────────────

STATUS_EMOJI = {
    "created": "🆕", "pending": "⏳", "confirmed": "✅",
    "packed": "📦", "dispatched": "🚚", "delivered": "📬", "cancelled": "❌",
}

def _welcome_message(customer_name: str) -> str:
    return (
        f"Namaste *{customer_name}* ji! 🙏\n\n"
        f"*Jyoti Creative Cards* mein aapka swagat hai.\n\n"
        f"*Stock check karein:*\n"
        f"👉 {STOCK_SITE_URL}\n\n"
        f"*Options:*\n"
        f"1️⃣  Mera order status\n"
        f"2️⃣  Support chahiye\n\n"
        f"Product dekh kar *Order Now* dabayein — order apne aap yahan aayega!"
    )

def handle_message(phone: str, text: str, interactive_id: str = None):
    text = (text or "").strip()
    msg  = (interactive_id or text).lower().strip()

    _log_wa(phone, "inbound", text or interactive_id or "")

    # ── Security gate — registered customers only ─────────────────────────────
    customer = _get_customer(phone)
    if not customer:
        wa_text(phone,
            "Maaf karein, aapka number registered nahi hai. 🙏\n\n"
            "Order ke liye humse call karein:\n"
            f"📞 *+91 {BUSINESS_WHATSAPP_NUMBER[-10:]}*\n"
            "⏰ Mon–Sat, 10am–7pm"
        )
        _upsert_conversation(phone, None, "rejected_unregistered")
        return

    cid       = customer.id
    cname     = customer.name
    last      = _get_last_intent(phone)

    # ── Shortcuts ─────────────────────────────────────────────────────────────
    if msg in ("hi", "hello", "hii", "hey", "start", "menu", "namaste", "jai jinendra", "1️⃣", "home"):
        wa_text(phone, _welcome_message(cname))
        _upsert_conversation(phone, cid, "welcome")
        return

    if msg in ("1", "order status", "mera order"):
        _send_order_status(phone, customer)
        return

    if msg in ("2", "support", "help"):
        wa_text(phone,
            "Humari team jald call karegi. 😊\n"
            f"📞 Direct call: *+91 {BUSINESS_WHATSAPP_NUMBER[-10:]}*\n"
            "⏰ Mon–Sat, 10am–7pm"
        )
        _upsert_conversation(phone, cid, "support")
        return

    # ── Structured order from stock site: ORDER|SKU:1234|QTY:10 ──────────────
    order_match = re.match(r"ORDER\|SKU:([^\|]+)\|QTY:(\d+(?:\.\d+)?)", text, re.IGNORECASE)
    if order_match:
        sku = order_match.group(1).strip()
        qty = float(order_match.group(2))
        _handle_structured_order(phone, customer, sku, qty)
        return

    # ── Confirm / cancel pending order ────────────────────────────────────────
    if interactive_id == "confirm_order" or msg in ("confirm", "haan", "yes", "ok"):
        if phone in _pending_orders:
            _finalise_order(phone, customer)
        else:
            wa_text(phone, "Koi pending order nahi hai. Stock site par jayein:\n" + STOCK_SITE_URL)
        return

    if interactive_id == "cancel_order" or msg in ("cancel", "nahi", "no"):
        _pending_orders.pop(phone, None)
        wa_text(phone, "Order cancel kar diya. 😊\nKuch aur chahiye?\n\nStock check: " + STOCK_SITE_URL)
        _upsert_conversation(phone, cid, "cancelled")
        return

    if interactive_id == "order_status":
        _send_order_status(phone, customer)
        return

    # ── Fallback — send welcome ───────────────────────────────────────────────
    wa_text(phone, _welcome_message(cname))
    _upsert_conversation(phone, cid, "welcome")


def _handle_structured_order(phone: str, customer, sku: str, qty: float):
    product, stock = _get_product_by_sku(sku)

    if not product:
        wa_text(phone, f"SKU *{sku}* nahi mila. Kripya stock site par dobara check karein:\n{STOCK_SITE_URL}")
        return

    if stock <= 0:
        wa_text(phone, f"*{product.name}* (SKU: {sku}) abhi out of stock hai. 😔\nThoda intezaar karein ya aur products dekhein:\n{STOCK_SITE_URL}")
        return

    if qty > stock:
        wa_text(phone,
            f"*{product.name}* mein sirf *{stock:.0f} pcs* available hain.\n"
            f"Aapne *{qty:.0f} pcs* maange — kripya quantity kam karein."
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
            f"*Order Confirm Karein:*\n\n"
            f"📦 Product: *{product.name}*\n"
            f"🔢 SKU: {sku}\n"
            f"🔢 Quantity: *{qty:.0f} pcs*\n"
            f"💰 Price: ₹{product.selling_price:.0f}/pcs\n"
            f"💰 Total: *₹{total:.0f}*\n\n"
            f"Confirm karna chahte hain?"
        ),
        buttons=[
            {"id": "confirm_order", "title": "✅ Haan, Confirm"},
            {"id": "cancel_order",  "title": "❌ Cancel"},
        ],
        footer="Order confirm hone par stock automatically deduct hoga"
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
            f"Humari team jald process karegi.\n"
            f"Status check ke liye type karein: *order status*\n"
            f"📞 +91 {BUSINESS_WHATSAPP_NUMBER[-10:]}"
        )
        wa_text(phone, msg)
        _log_wa(phone, "outbound", msg, "sales_order", so_id)
        _pending_orders.pop(phone, None)
        _upsert_conversation(phone, customer.id, "order_placed")

    except ValueError as e:
        wa_text(phone, f"Order nahi ho saka: {e}\nCall karein: +91 {BUSINESS_WHATSAPP_NUMBER[-10:]}")
    except Exception as e:
        print(f"[ORDER ERROR] {e}", flush=True)
        wa_text(phone, "Kuch gadbad ho gayi. Kripya call karein: +91 " + BUSINESS_WHATSAPP_NUMBER[-10:])


def _send_order_status(phone: str, customer):
    orders = _get_recent_orders(customer.id)
    if not orders:
        wa_text(phone,
            "Abhi tak koi order nahi hai.\n\n"
            f"Stock check karein: {STOCK_SITE_URL}"
        )
        return

    lines = [f"📋 *{customer.name} ke Orders:*\n"]
    for o in orders:
        em = STATUS_EMOJI.get(o["status"], "📋")
        lines.append(
            f"{em} *Order #{o['id']}* — {o['date']}\n"
            f"   {o['items']}\n"
            f"   ₹{o['total']:,.0f} | *{o['status'].upper()}*\n"
        )
    wa_text(phone, "\n".join(lines))
    _upsert_conversation(phone, customer.id, "order_status")


# ─── Notify endpoint (called by Streamlit ERP on status change) ───────────────

def notify_order_update(order_id: int, new_status: str):
    from db.models import SalesOrder, Customer
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
            "confirmed":  f"✅ Order *#{order_id}* confirm ho gaya! Hum prepare kar rahe hain.",
            "packed":     f"📦 Order *#{order_id}* pack ho gaya! Jald dispatch hoga.",
            "dispatched": f"🚚 Order *#{order_id}* dispatch ho gaya! 1–2 din mein milega.",
            "delivered":  f"📬 Order *#{order_id}* deliver ho gaya! Shukriya 🙏\nJyoti Creative Cards",
            "cancelled":  f"❌ Order *#{order_id}* cancel ho gaya.\nCall karein: +91 {BUSINESS_WHATSAPP_NUMBER[-10:]}",
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
    with WEBHOOK_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def app(environ, start_response):
    method = environ.get("REQUEST_METHOD", "GET")
    path   = environ.get("PATH_INFO", "/")
    query  = parse_qs(environ.get("QUERY_STRING", ""))

    if path == "/health":
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

    # ── Order status notification (called by Streamlit ERP) ──────────────────
    if path == "/notify/order-update" and method == "POST":
        try:
            data   = json.loads(_read_body(environ))
            result = notify_order_update(int(data["order_id"]), data["new_status"])
            return _json_resp(start_response, result)
        except Exception as e:
            return _json_resp(start_response, {"error": str(e)}, "400 Bad Request")

    if path != META_WEBHOOK_PATH:
        return _text_resp(start_response, "not found", "404 Not Found")

    # ── Webhook verify GET ────────────────────────────────────────────────────
    if method == "GET":
        mode      = (query.get("hub.mode") or [""])[0]
        token     = (query.get("hub.verify_token") or [""])[0]
        challenge = (query.get("hub.challenge") or [""])[0]
        if mode == "subscribe" and token == META_WEBHOOK_VERIFY_TOKEN:
            return _text_resp(start_response, challenge)
        return _text_resp(start_response, "forbidden", "403 Forbidden")

    # ── Incoming WhatsApp message POST ────────────────────────────────────────
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


if __name__ == "__main__":
    print(f"Bot → http://0.0.0.0:{META_WEBHOOK_PORT}{META_WEBHOOK_PATH}")
    server = make_server("0.0.0.0", META_WEBHOOK_PORT, app)
    server.serve_forever()
