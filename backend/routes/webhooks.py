from fastapi import APIRouter, Request, HTTPException

from config import META_VERIFY_TOKEN
from db.database import SessionLocal
from backend.services.parser import parse_customer_message
from backend.services.whatsapp import send_whatsapp_message, send_internal_alert, log_message
from services.sales import create_sales_order_from_names
from services.customers import get_or_create_customer_by_whatsapp
from services.products import search_products

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.get("/whatsapp")
def verify(mode: str = "", hub_verify_token: str = "", hub_challenge: str = ""):
    if mode == "subscribe" and hub_verify_token == META_VERIFY_TOKEN:
        return int(hub_challenge) if hub_challenge.isdigit() else hub_challenge
    raise HTTPException(status_code=403, detail="verification failed")


@router.post("/whatsapp")
async def receive_whatsapp(request: Request):
    payload = await request.json()
    db = SessionLocal()
    try:
        entries = payload.get("entry", [])
        for entry in entries:
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for message in value.get("messages", []):
                    phone = message.get("from", "")
                    text = message.get("text", {}).get("body", "")
                    log_message(db, phone, "in", text, status="received")
                    customer = get_or_create_customer_by_whatsapp(db, phone)
                    parsed = parse_customer_message(text)

                    if parsed["intent"] == "catalog_query":
                        matches = search_products(db, parsed["text"])[:5]
                        if matches:
                            reply = "Available products:\n" + "\n".join([f"{p.name} | {p.sku} | ₹{p.selling_price}" for p in matches])
                        else:
                            reply = "No matching products found."
                        send_whatsapp_message(db, phone, reply, "customer_query", customer.id)
                        send_internal_alert(db, f"Catalog query from {phone}: {text}", "customer_query", customer.id)
                    elif parsed["intent"] == "place_order":
                        so = create_sales_order_from_names(db, phone, parsed["items"], notes="WhatsApp order")
                        send_whatsapp_message(db, phone, f"Order received. SO#{so.id} total ₹{so.total_amount:,.0f}", "sales_order", so.id)
                        send_internal_alert(db, f"New WhatsApp order SO#{so.id} from {phone}", "sales_order", so.id)
                    else:
                        send_whatsapp_message(db, phone, "Send product name for price/stock, or send like: 10 Sugar, 5 Oil", "help", customer.id)
        return {"ok": True}
    finally:
        db.close()
