import os

APP_NAME     = "Jyoti Cards ERP"
APP_PASSWORD = os.getenv("APP_PASSWORD", "kiwigudda")

# Database — on Render this points to the persistent disk
DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(__file__), "ops.db"))

# WhatsApp Business
BUSINESS_WHATSAPP_NUMBER  = os.getenv("BUSINESS_WHATSAPP_NUMBER", "9516789702")
INTERNAL_ALERT_NUMBER     = os.getenv("INTERNAL_ALERT_NUMBER", "9754656565")
META_ACCESS_TOKEN         = os.getenv("META_ACCESS_TOKEN", "")
META_PHONE_NUMBER_ID      = os.getenv("META_PHONE_NUMBER_ID", "1052983514569869")
META_BUSINESS_ACCOUNT_ID  = os.getenv("META_BUSINESS_ACCOUNT_ID", "2163859664363077")
META_API_VERSION          = os.getenv("META_API_VERSION", "v25.0")
WHATSAPP_PROVIDER         = os.getenv("WHATSAPP_PROVIDER", "meta")
META_WEBHOOK_VERIFY_TOKEN = os.getenv("META_WEBHOOK_VERIFY_TOKEN", "jyoti_cards_wh_verify_2026")
META_WEBHOOK_PATH         = os.getenv("META_WEBHOOK_PATH", "/webhooks/whatsapp")
META_WEBHOOK_PORT         = int(os.getenv("META_WEBHOOK_PORT", os.getenv("PORT", "8080")))
META_DEFAULT_TEMPLATE_LANGUAGE = os.getenv("META_DEFAULT_TEMPLATE_LANGUAGE", "en")
CUSTOMER_WELCOME_TEMPLATE = os.getenv("CUSTOMER_WELCOME_TEMPLATE", "")

# Bot URLs
BOT_BASE_URL  = os.getenv("BOT_BASE_URL", "https://jyoti-cards-bot.onrender.com")
STOCK_SITE_URL = os.getenv("STOCK_SITE_URL", "https://jyoti-cards-stock.onrender.com")

# Azure OpenAI
AZURE_OPENAI_API_KEY          = os.getenv("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_ENDPOINT         = os.getenv("AZURE_OPENAI_ENDPOINT", "https://zeroque-intel.openai.azure.com/")
AZURE_OPENAI_API_VERSION      = os.getenv("AZURE_OPENAI_API_VERSION", "2024-06-01")
AZURE_OPENAI_LLM_DEPLOYMENT   = os.getenv("AZURE_OPENAI_LLM_DEPLOYMENT", "gpt-5-nano")

# Legacy alias used in backend/routes/webhooks.py
META_VERIFY_TOKEN = META_WEBHOOK_VERIFY_TOKEN
