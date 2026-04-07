# Jyoti Cards ERP

Internal ERP with Streamlit UI and FastAPI webhook backend.

## Default Password

- `kiwigudda`

## Local Run

```bash
pip3 install -r requirements.txt
streamlit run app.py
uvicorn backend.main:app --host 0.0.0.0 --port 8015
```

## WhatsApp Live Setup

- Set `WHATSAPP_PROVIDER=meta`
- Set `META_ACCESS_TOKEN`
- Set `META_PHONE_NUMBER_ID`
- Set `META_VERIFY_TOKEN`
- Use office business number `9516789702`
- Internal reports and alerts go to `9754656565`

## Streamlit Cloud

- Add secrets using `.streamlit/secrets.toml.example`
- Deploy Streamlit UI with `app.py`
- Deploy backend separately using `render.yaml` or another public Python host
- Set webhook callback to:
  - `<PUBLIC_BACKEND_URL>/webhooks/whatsapp`

## Features

- WhatsApp customer ordering
- Vendor and customer WhatsApp notifications
- PDF order receipt on customer order confirmation
- PO lifecycle and 3-way match
- Vendor bill and goods receipt uploads
- Discounts and reports
- Daily internal summary automation

## Smoke Test

```bash
python3 smoke_test.py
```
