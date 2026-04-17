# Jyoti Cards Purchasing App

Streamlit admin app for vendor management, item catalog, purchase orders, stock intake, inventory, and WhatsApp communication through Meta WhatsApp API.

## Default Password

- `kiwigudda`

## Run

```bash
pip3 install -r requirements.txt
streamlit run app.py
```

## WhatsApp Setup

- Set `WHATSAPP_PROVIDER=meta`
- Set `META_ACCESS_TOKEN`
- Set `META_PHONE_NUMBER_ID`
- Set `META_WEBHOOK_VERIFY_TOKEN` (example: `jyoti_cards_wh_verify_2026`)
- Set `META_WEBHOOK_PORT` (default: `8080`)
- Run webhook receiver: `python3 webhook_server.py`
- Callback path: `/webhooks/whatsapp`
- Use business number `9516789702`
- Internal alerts go to `9754656565`

## Deployment

- Render blueprint file is `render.yaml`
- Dashboard service: `jyoti-cards-dashboard` (Streamlit)
- Webhook service: `jyoti-cards-whatsapp-webhook` (WSGI server)
- Set secret env vars on Render dashboard (`META_ACCESS_TOKEN`, IDs, password, phone numbers)
- After deploy, webhook callback URL is:
  - `https://<your-webhook-service>.onrender.com/webhooks/whatsapp`

## Main Flow

- Create vendors with owner name, firm name, mobile, and billing condition
- Create items with your own item ID plus vendor item ID for the selected vendor
- Maintain vendor price and billing percent on the same item flow
- Create purchase orders using your item ID while auto-loading vendor mapping
- Create new PO versions after vendor discussions
- Receive stock in batches against a PO
- Close PO with note and WhatsApp notification

## Main Screens

- Dashboard
- Our Items
- Vendors
- Purchase Orders
- Stock Intake
- Inventory
- WhatsApp
