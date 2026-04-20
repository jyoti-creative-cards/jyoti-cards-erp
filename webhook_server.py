from __future__ import annotations

import json
import re
import sqlite3
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone, date
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
)

# ── DB path (mirrors db/database.py) ─────────────────────────────────────────
ROOT    = Path(__file__).resolve().parent
DB_PATH = ROOT / "ops.db"
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
WEBHOOK_LOG_PATH = LOG_DIR / "whatsapp_webhooks.jsonl"

# ── Azure OpenAI ──────────────────────────────────────────────────────────────
import os
AZURE_KEY        = os.getenv("AZURE_OPENAI_API_KEY", "")
AZURE_ENDPOINT   = os.getenv("AZURE_OPENAI_ENDPOINT", "https://zeroque-intel.openai.azure.com/")
AZURE_API_VER    = os.getenv("AZURE_OPENAI_API_VERSION", "2024-06-01")
AZURE_DEPLOY     = os.getenv("AZURE_OPENAI_LLM_DEPLOYMENT", "gpt-5-nano")

# In-memory carts  {phone: [{"product_id","name","qty","price","unit"}]}
_carts: dict = {}

MENU = (
    "Welcome to *Jyoti Creative Cards* 🎉\n\n"
    "1️⃣  Browse catalog\n"
    "2️⃣  Search product\n"
    "3️⃣  View my cart\n"
    "4️⃣  My orders\n"
    "5️⃣  Recommendations\n"
    "6️⃣  Support\n\n"
    "Reply with a number or just tell me what you need!"
)

# ─────────────────────────────────────────────────────────────────────────────
# DB helpers
# ─────────────────────────────────────────────────────────────────────────────

def _db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def _phone_local(phone: str) -> str:
    """Return last 10 digits for matching."""
    return re.sub(r"\D", "", phone)[-10:]

def get_customer(phone: str):
    local = _phone_local(phone)
    with _db() as c:
        row = c.execute(
            "SELECT * FROM customers WHERE phone LIKE ? OR whatsapp_phone LIKE ? LIMIT 1",
            (f"%{local}%", f"%{local}%")
        ).fetchone()
    return dict(row) if row else None

def create_customer(name: str, phone: str) -> int:
    with _db() as c:
        cur = c.execute(
            "INSERT INTO customers (name,phone,whatsapp_phone,customer_type,notifications_enabled,created_at) "
            "VALUES (?,?,?,'retail',1,?)",
            (name, phone, phone, datetime.now())
        )
        c.commit()
        return cur.lastrowid

def get_products(search: str = None) -> list:
    sql = """SELECT p.id,p.name,p.sku,p.category,p.selling_price,p.unit,
                    p.image_path,p.website_description,
                    COALESCE(i.quantity_available,0) AS stock
             FROM products p
             LEFT JOIN inventory i ON i.product_id=p.id
             WHERE p.active=1"""
    args = []
    if search:
        sql += " AND (p.name LIKE ? OR p.category LIKE ? OR p.sku LIKE ?)"
        like = f"%{search}%"
        args = [like, like, like]
    sql += " ORDER BY p.category,p.name LIMIT 30"
    with _db() as c:
        rows = c.execute(sql, args).fetchall()
    return [dict(r) for r in rows]

def get_product_by_id(pid: int):
    with _db() as c:
        row = c.execute(
            "SELECT p.*,COALESCE(i.quantity_available,0) AS stock FROM products p "
            "LEFT JOIN inventory i ON i.product_id=p.id WHERE p.id=?", (pid,)
        ).fetchone()
    return dict(row) if row else None

def create_order(customer_id: int, items: list) -> int:
    subtotal = sum(i["qty"] * i["price"] for i in items)
    with _db() as c:
        cur = c.execute(
            "INSERT INTO sales_orders (customer_id,status,order_date,channel,"
            "subtotal_amount,discount_percent,discount_amount,total_amount,notes,"
            "customer_notification_status,internal_notification_status,created_at) "
            "VALUES (?,?,?,?,?,0,0,?,?,'pending','pending',?)",
            (customer_id, "pending", date.today(), "whatsapp",
             subtotal, subtotal, "WhatsApp bot order", datetime.now())
        )
        oid = cur.lastrowid
        for it in items:
            c.execute(
                "INSERT INTO sales_order_items "
                "(order_id,product_id,quantity,unit_price,discount_percent,total_price) "
                "VALUES (?,?,?,?,0,?)",
                (oid, it["product_id"], it["qty"], it["price"], it["qty"]*it["price"])
            )
        c.commit()
    return oid

def get_recent_orders(customer_id: int) -> list:
    with _db() as c:
        rows = c.execute(
            "SELECT so.id,so.status,so.order_date,so.total_amount,"
            "GROUP_CONCAT(p.name||' x'||CAST(soi.quantity AS INT),', ') as items "
            "FROM sales_orders so "
            "JOIN sales_order_items soi ON soi.order_id=so.id "
            "JOIN products p ON p.id=soi.product_id "
            "WHERE so.customer_id=? GROUP BY so.id ORDER BY so.created_at DESC LIMIT 5",
            (customer_id,)
        ).fetchall()
    return [dict(r) for r in rows]

def log_wa(phone: str, direction: str, message: str, related_type=None, related_id=None):
    try:
        with _db() as c:
            c.execute(
                "INSERT INTO whatsapp_logs (phone,direction,message,related_type,related_id,status,created_at) "
                "VALUES (?,?,?,?,?,'sent',?)",
                (phone, direction, message, related_type, related_id, datetime.now())
            )
            c.commit()
    except Exception:
        pass

def get_or_create_conversation(phone: str, customer_id=None, intent: str = None):
    with _db() as c:
        row = c.execute("SELECT * FROM whatsapp_conversations WHERE phone=? LIMIT 1", (phone,)).fetchone()
        now = datetime.now()
        if row:
            c.execute(
                "UPDATE whatsapp_conversations SET last_message_at=?,last_intent=?,"
                "customer_id=COALESCE(?,customer_id) WHERE phone=?",
                (now, intent, customer_id, phone)
            )
        else:
            c.execute(
                "INSERT INTO whatsapp_conversations (phone,customer_id,last_message_at,last_intent,created_at) "
                "VALUES (?,?,?,?,?)",
                (phone, customer_id, now, intent, now)
            )
        c.commit()
        row2 = c.execute("SELECT * FROM whatsapp_conversations WHERE phone=? LIMIT 1", (phone,)).fetchone()
    return dict(row2) if row2 else {}

# ─────────────────────────────────────────────────────────────────────────────
# WhatsApp sender
# ─────────────────────────────────────────────────────────────────────────────

def _wa_post(payload: dict):
    url   = f"https://graph.facebook.com/{META_API_VERSION}/{META_PHONE_NUMBER_ID}/messages"
    data  = json.dumps(payload).encode()
    req   = urllib.request.Request(url, data=data, headers={
        "Authorization": f"Bearer {META_ACCESS_TOKEN}",
        "Content-Type":  "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"[WA ERROR] {e.code}: {body}", flush=True)
        return {"error": body}

def wa_text(to: str, text: str):
    return _wa_post({
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {"body": text, "preview_url": False},
    })

def wa_image(to: str, url: str, caption: str = ""):
    return _wa_post({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "image",
        "image": {"link": url, "caption": caption},
    })

def wa_buttons(to: str, body: str, buttons: list, header: str = None, footer: str = None):
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
        msg["interactive"]["header"] = {"type": "text", "text": header}
    if footer:
        msg["interactive"]["footer"] = {"text": footer}
    return _wa_post(msg)

# ─────────────────────────────────────────────────────────────────────────────
# Azure OpenAI
# ─────────────────────────────────────────────────────────────────────────────

def ai_intent(user_msg: str, catalog_text: str, customer_name: str = None) -> dict:
    name_ctx = f"Customer: {customer_name}" if customer_name else "Customer: new/unknown"
    system = (
        "You are a WhatsApp sales assistant for Jyoti Creative Cards, an Indian stationery/cards retailer.\n"
        "Respond ONLY with valid JSON:\n"
        '{"intent":"<greeting|browse|search|stock|order|status|recommend|confirm|cancel|unknown>",'
        '"reply":"<short WhatsApp reply>",'
        '"cart_items":[{"product_id":int,"qty":float}],'
        '"search_query":"<string or null>"}'
        "\ncart_items only when intent=order or confirm. reply must be under 300 chars."
    )
    user = f"{name_ctx}\nCatalog:\n{catalog_text}\nCustomer said: \"{user_msg}\"\nRespond with JSON only."

    url  = f"{AZURE_ENDPOINT.rstrip('/')}/openai/deployments/{AZURE_DEPLOY}/chat/completions?api-version={AZURE_API_VER}"
    body = json.dumps({
        "messages": [{"role":"system","content":system},{"role":"user","content":user}],
        "temperature": 0.2,
        "max_tokens": 400,
        "response_format": {"type": "json_object"},
    }).encode()
    req = urllib.request.Request(url, data=body, headers={
        "api-key": AZURE_KEY,
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read())
        content = resp["choices"][0]["message"]["content"]
        return json.loads(content)
    except Exception as e:
        print(f"[AI ERROR] {e}", flush=True)
        return {"intent": "unknown", "reply": "Sorry, one moment. Type *menu* for options.", "cart_items": [], "search_query": None}

def ai_recommend(catalog_text: str) -> str:
    url  = f"{AZURE_ENDPOINT.rstrip('/')}/openai/deployments/{AZURE_DEPLOY}/chat/completions?api-version={AZURE_API_VER}"
    body = json.dumps({
        "messages": [
            {"role":"system","content":"Recommend 2-3 products from this catalog for a retail stationery customer. Keep it under 200 chars, WhatsApp-friendly."},
            {"role":"user","content":f"Catalog:\n{catalog_text}"},
        ],
        "temperature": 0.5,
        "max_tokens": 150,
    }).encode()
    req = urllib.request.Request(url, data=body, headers={
        "api-key": AZURE_KEY,
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read())
        return resp["choices"][0]["message"]["content"].strip()
    except Exception:
        return ""

def catalog_summary(products: list) -> str:
    lines = []
    for p in products:
        stock = f"{p['stock']} {p.get('unit','')}" if p.get("stock",0) > 0 else "OUT OF STOCK"
        lines.append(f"ID:{p['id']} {p['name']} SKU:{p['sku']} ₹{p.get('selling_price','?')}/{p.get('unit','unit')} [{stock}]")
    return "\n".join(lines) or "No products available."

# ─────────────────────────────────────────────────────────────────────────────
# Bot logic
# ─────────────────────────────────────────────────────────────────────────────

def handle_message(phone: str, text: str, interactive_id: str = None):
    text = (text or "").strip()
    msg  = (interactive_id or text).lower().strip()

    log_wa(phone, "inbound", text)
    customer = get_customer(phone)
    conv     = get_or_create_conversation(phone, customer.get("id") if customer else None)
    last     = conv.get("last_intent", "")

    # ── Shortcut triggers ────────────────────────────────────────────────────
    if msg in ("menu","hi","hello","hii","hey","start","1","namaste","jai jinendra"):
        wa_text(phone, MENU)
        get_or_create_conversation(phone, customer.get("id") if customer else None, "menu")
        return

    if interactive_id == "confirm_order":
        _do_confirm(phone, customer)
        return

    if interactive_id == "cancel_order":
        _carts.pop(phone, None)
        wa_text(phone, "Order cancelled. Type *menu* anytime 😊")
        return

    if interactive_id == "add_more" or msg == "3":
        _show_cart(phone, customer)
        return

    if msg == "4":
        _show_orders(phone, customer)
        return

    if msg == "6":
        wa_text(phone, "Our team will call you back shortly.\n📞 +91 76948 12345\n⏰ Mon–Sat 10am–7pm")
        return

    # ── New customer name capture ────────────────────────────────────────────
    if last == "awaiting_name" and text:
        name = text.strip().title()
        cid  = create_customer(name, phone)
        wa_text(phone, f"Nice to meet you, *{name}*! 🎉\n\n{MENU}")
        get_or_create_conversation(phone, cid, "menu")
        return

    # ── AI intent ────────────────────────────────────────────────────────────
    products = get_products()
    cat_text = catalog_summary(products)
    result   = ai_intent(text, cat_text, customer.get("name") if customer else None)

    intent       = result.get("intent","unknown")
    reply        = result.get("reply","")
    cart_items   = result.get("cart_items") or []
    search_query = result.get("search_query")

    get_or_create_conversation(phone, customer.get("id") if customer else None, intent)

    if intent == "greeting":
        if not customer:
            wa_text(phone, "👋 Welcome to *Jyoti Creative Cards*!\nWhat's your name? (We'll save it for orders)")
            get_or_create_conversation(phone, None, "awaiting_name")
        else:
            wa_text(phone, f"Welcome back, *{customer['name']}*! 😊\n\n{MENU}")

    elif intent == "browse":
        _send_catalog(phone, products)

    elif intent in ("search","stock"):
        q       = search_query or text
        results = get_products(q)
        if results:
            wa_text(phone, f"Found *{len(results)}* result(s) for \"{q}\":")
            for p in results[:4]:
                _send_product_card(phone, p)
            wa_buttons(phone,
                body="Add any of these to your order?",
                buttons=[{"id":"menu","title":"Main Menu"}, {"id":"add_more","title":"View Cart"}],
                footer="Type product name + qty to order"
            )
        else:
            wa_text(phone, f"No products found for \"{q}\". Try another name or type *menu*.")

    elif intent in ("order","confirm") and cart_items:
        validated = []
        errors    = []
        for ci in cart_items:
            p = get_product_by_id(int(ci["product_id"]))
            if not p:
                errors.append(f"Product {ci['product_id']} not found")
                continue
            if p.get("stock",0) <= 0:
                errors.append(f"*{p['name']}* is out of stock")
                continue
            validated.append({
                "product_id": p["id"],
                "name":  p["name"],
                "qty":   float(ci.get("qty",1)),
                "price": float(p.get("selling_price",0)),
                "unit":  p.get("unit",""),
            })
        if errors:
            wa_text(phone, "\n".join(errors))
        if validated:
            _carts[phone] = (_carts.get(phone) or []) + validated
            _show_cart(phone, customer)

    elif intent == "status":
        _show_orders(phone, customer)

    elif intent == "recommend":
        reco = ai_recommend(cat_text)
        if reco:
            wa_text(phone, f"🌟 *You might love:*\n\n{reco}\n\nType a name to check stock!")
        else:
            _send_catalog(phone, products[:4])

    elif intent == "cancel":
        _carts.pop(phone, None)
        wa_text(phone, "Order cancelled. Type *menu* to start fresh.")

    else:
        if reply:
            wa_text(phone, reply)
        else:
            wa_text(phone, MENU)


def _send_product_card(phone: str, p: dict):
    stock_str = f"✅ {p['stock']} {p.get('unit','')} in stock" if p.get("stock",0) > 0 else "❌ Out of stock"
    price_str = f"₹{p['selling_price']:.0f}/{p.get('unit','unit')}" if p.get("selling_price") else "Price on request"
    caption   = f"*{p['name']}*\nSKU: {p['sku']}\n{price_str}\n{stock_str}"
    if p.get("website_description"):
        caption += f"\n{p['website_description']}"
    if p.get("image_path"):
        wa_image(phone, p["image_path"], caption)
    else:
        wa_text(phone, caption)


def _send_catalog(phone: str, products: list):
    if not products:
        wa_text(phone, "Catalog is being updated. Check back soon!")
        return
    by_cat: dict = {}
    for p in products:
        by_cat.setdefault(p.get("category") or "Other", []).append(p)
    wa_text(phone, f"🛍️ *Jyoti Creative Cards Catalog*\n{len(products)} products across {len(by_cat)} categories:")
    for cat, prods in by_cat.items():
        wa_text(phone, f"📂 *{cat}*")
        for p in prods[:6]:
            _send_product_card(phone, p)
    wa_buttons(phone,
        body="Anything you'd like to order? 😊",
        buttons=[{"id":"2","title":"Search Product"}, {"id":"menu","title":"Main Menu"}],
        footer="Type product name + quantity to order"
    )


def _show_cart(phone: str, customer: dict):
    cart = _carts.get(phone, [])
    if not cart:
        wa_text(phone, "Your cart is empty 🛒\nBrowse catalog or search a product.")
        return
    lines = ["🛒 *Your Cart:*\n"]
    total = 0.0
    for it in cart:
        sub    = it["qty"] * it["price"]
        total += sub
        lines.append(f"• {it['name']} — {it['qty']} {it.get('unit','')} × ₹{it['price']:.0f} = *₹{sub:.0f}*")
    lines.append(f"\n💰 *Total: ₹{total:.0f}*")
    if not customer:
        wa_text(phone, "\n".join(lines) + "\n\nWhat's your name to confirm this order?")
        get_or_create_conversation(phone, None, "awaiting_name")
    else:
        wa_buttons(phone,
            body="\n".join(lines),
            buttons=[
                {"id":"confirm_order","title":"✅ Confirm"},
                {"id":"cancel_order","title":"❌ Cancel"},
            ],
            header=f"Order for {customer['name']}",
            footer="We'll process this right away"
        )


def _do_confirm(phone: str, customer: dict):
    cart = _carts.get(phone, [])
    if not cart:
        wa_text(phone, "Cart is empty. Add items first.")
        return
    if not customer:
        wa_text(phone, "Tell us your name first:")
        get_or_create_conversation(phone, None, "awaiting_name")
        return
    oid   = create_order(customer["id"], cart)
    total = sum(i["qty"]*i["price"] for i in cart)
    lines = "\n".join(f"  • {i['name']} × {i['qty']} {i.get('unit','')} = ₹{i['qty']*i['price']:.0f}" for i in cart)
    msg   = (
        f"✅ *Order Confirmed!*\n\n"
        f"Order ID: *#{oid}*\n"
        f"{lines}\n\n"
        f"💰 Total: *₹{total:.0f}*\n\n"
        f"We'll call to confirm dispatch.\n📞 +91 76948 12345"
    )
    wa_text(phone, msg)
    log_wa(phone, "outbound", msg, "sales_order", oid)
    _carts.pop(phone, None)
    get_or_create_conversation(phone, customer["id"], "order_placed")


def _show_orders(phone: str, customer: dict):
    if not customer:
        wa_text(phone, "Couldn't find your account. What's your name?")
        get_or_create_conversation(phone, None, "awaiting_name")
        return
    orders = get_recent_orders(customer["id"])
    if not orders:
        wa_text(phone, "No orders yet. Browse the catalog to place your first order! 🛍️")
        return
    em = {"pending":"⏳","confirmed":"✅","dispatched":"🚚","delivered":"📬","cancelled":"❌"}
    lines = [f"📦 *Orders for {customer['name']}:*\n"]
    for o in orders:
        lines.append(
            f"{em.get(o['status'],'📋')} *#{o['id']}* {o['order_date']}\n"
            f"   {o['items']}\n"
            f"   ₹{o['total_amount']:.0f} — *{str(o['status']).upper()}*\n"
        )
    wa_text(phone, "\n".join(lines))

# ─────────────────────────────────────────────────────────────────────────────
# Notify endpoint — called by Streamlit when order status changes
# ─────────────────────────────────────────────────────────────────────────────

def notify_order(order_id: int, new_status: str):
    with _db() as c:
        row = c.execute(
            "SELECT so.id,so.total_amount,c.name,c.whatsapp_phone,c.phone "
            "FROM sales_orders so JOIN customers c ON c.id=so.customer_id WHERE so.id=?",
            (order_id,)
        ).fetchone()
    if not row:
        return {"error": "order not found"}
    phone  = (row["whatsapp_phone"] or row["phone"] or "").replace("+","").replace(" ","")
    if not phone.startswith("91"):
        phone = "91" + phone[-10:]
    msgs = {
        "confirmed":  f"✅ Order *#{order_id}* confirmed! We're preparing it.",
        "dispatched": f"🚚 Order *#{order_id}* dispatched! Arriving in 1–2 days.",
        "delivered":  f"📬 Order *#{order_id}* delivered! Thanks for shopping with Jyoti Cards 🎉",
        "cancelled":  f"❌ Order *#{order_id}* cancelled. Call +91 76948 12345 for help.",
    }
    msg = msgs.get(new_status, f"📋 Order *#{order_id}* updated to *{new_status.upper()}*.")
    wa_text(phone, msg)
    log_wa(phone, "outbound", msg, "sales_order", order_id)
    return {"sent": True}

# ─────────────────────────────────────────────────────────────────────────────
# WSGI app
# ─────────────────────────────────────────────────────────────────────────────

def _read_body(environ) -> str:
    length = int(environ.get("CONTENT_LENGTH") or 0)
    return environ["wsgi.input"].read(length).decode("utf-8") if length > 0 else ""

def _json_resp(start_response, payload, status="200 OK"):
    body = json.dumps(payload, ensure_ascii=False).encode()
    start_response(status, [("Content-Type","application/json"),("Content-Length",str(len(body)))])
    return [body]

def _text_resp(start_response, text, status="200 OK"):
    body = text.encode()
    start_response(status, [("Content-Type","text/plain"),("Content-Length",str(len(body)))])
    return [body]

def _html_resp(start_response, html, status="200 OK"):
    body = html.encode()
    start_response(status, [("Content-Type","text/html; charset=utf-8"),("Content-Length",str(len(body)))])
    return [body]

def _append_log(payload: dict):
    line = json.dumps(payload, ensure_ascii=False)
    with WEBHOOK_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(f"{line}\n")


def app(environ, start_response):
    method = environ.get("REQUEST_METHOD","GET")
    path   = environ.get("PATH_INFO","/")
    query  = parse_qs(environ.get("QUERY_STRING",""))

    if path == "/health":
        return _json_resp(start_response, {"status":"ok"})

    if path == "/privacy-policy":
        return _html_resp(start_response, """<!doctype html><html><head><title>Privacy Policy</title></head>
<body><h1>Privacy Policy — Jyoti Creative Cards</h1>
<p>We collect contact and order information to process your purchases and send notifications via WhatsApp.
We do not sell your data. Contact: +91 76948 12345</p></body></html>""")

    if path == "/debug/webhooks":
        limit = int((query.get("limit") or ["20"])[0])
        if WEBHOOK_LOG_PATH.exists():
            lines = WEBHOOK_LOG_PATH.read_text().splitlines()
            rows  = []
            for l in lines[-limit:]:
                try: rows.append(json.loads(l))
                except: rows.append({"raw":l})
        else:
            rows = []
        return _json_resp(start_response, {"rows": rows})

    # ── Notify endpoint (called by Streamlit) ─────────────────────────────────
    if path == "/notify/order-update" and method == "POST":
        raw = _read_body(environ)
        try:
            data   = json.loads(raw)
            result = notify_order(int(data["order_id"]), data["new_status"])
            return _json_resp(start_response, result)
        except Exception as e:
            return _json_resp(start_response, {"error": str(e)}, "400 Bad Request")

    if path != META_WEBHOOK_PATH:
        return _text_resp(start_response, "not found", "404 Not Found")

    # ── WhatsApp webhook verify (GET) ─────────────────────────────────────────
    if method == "GET":
        mode      = (query.get("hub.mode") or [""])[0]
        token     = (query.get("hub.verify_token") or [""])[0]
        challenge = (query.get("hub.challenge") or [""])[0]
        if mode == "subscribe" and token == META_WEBHOOK_VERIFY_TOKEN:
            return _text_resp(start_response, challenge)
        return _text_resp(start_response, "forbidden", "403 Forbidden")

    # ── Incoming WhatsApp message (POST) ──────────────────────────────────────
    if method == "POST":
        raw  = _read_body(environ)
        try: body = json.loads(raw) if raw else {}
        except: body = {}

        _append_log({"received_at": datetime.now(timezone.utc).isoformat(), "event": body})

        try:
            for entry in body.get("entry",[]):
                for change in entry.get("changes",[]):
                    value = change.get("value",{})
                    for msg in value.get("messages",[]):
                        phone    = msg.get("from","")
                        mtype    = msg.get("type","")
                        text     = ""
                        iid      = None
                        if mtype == "text":
                            text = msg.get("text",{}).get("body","")
                        elif mtype == "interactive":
                            iv   = msg.get("interactive",{})
                            it   = iv.get("type","")
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

        return _json_resp(start_response, {"status":"received"})

    return _text_resp(start_response, "method not allowed", "405 Method Not Allowed")


if __name__ == "__main__":
    print(f"Bot running → http://0.0.0.0:{META_WEBHOOK_PORT}{META_WEBHOOK_PATH}")
    print(f"Verify token: {META_WEBHOOK_VERIFY_TOKEN}")
    server = make_server("0.0.0.0", META_WEBHOOK_PORT, app)
    server.serve_forever()
