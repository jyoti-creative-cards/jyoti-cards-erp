import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

import streamlit as st

from backend.services.whatsapp import business_number
from config import APP_PASSWORD
from db.database import SessionLocal, init_db

init_db()
st.set_page_config(page_title="Jyoti Cards", page_icon="📦", layout="wide")

# ── global theme ──────────────────────────────────────────────────────────────
st.markdown("""
<style>
:root{
  --sap-bg:#f5f7fa;
  --sap-surface:#ffffff;
  --sap-border:#d8dde6;
  --sap-title:#0a6ed1;
  --sap-text:#1f2d3d;
  --sap-muted:#6a778b;
}
html, body, [class*="css"] {color:var(--sap-text);}
.stApp {background:var(--sap-bg);}
/* ── sidebar ────────────────────────────────────────────────── */
section[data-testid="stSidebar"] {
    background:linear-gradient(180deg,#0b3c73 0%, #0a6ed1 100%);
}
section[data-testid="stSidebar"] * {color:#f7fbff !important;}
section[data-testid="stSidebar"] hr {border-color:rgba(255,255,255,0.25);}
section[data-testid="stSidebar"] .stRadio label:hover {background:rgba(255,255,255,0.12); border-radius:8px;}

/* ── metric cards ───────────────────────────────────────────── */
[data-testid="stMetric"] {
    background: var(--sap-surface);
    border: 1px solid var(--sap-border);
    border-radius: 8px;
    padding: 14px 18px;
    box-shadow:0 1px 2px rgba(10,30,60,.06);
}
[data-testid="stMetric"] label {font-size:.75rem !important;text-transform:uppercase;letter-spacing:.05em;color:var(--sap-muted) !important;}
[data-testid="stMetric"] [data-testid="stMetricValue"] {font-size:1.4rem !important;font-weight:700 !important;color:var(--sap-title) !important;}

/* ── dataframes ─────────────────────────────────────────────── */
[data-testid="stDataFrame"] {
    border-radius:8px;
    overflow:hidden;
    border:1px solid var(--sap-border);
    background:#fff;
}

/* ── buttons ────────────────────────────────────────────────── */
.stButton > button {
    border-radius:6px;
    font-weight:600;
    padding:0.45rem 1.2rem;
    border:1px solid #0a6ed1;
    background:#0a6ed1;
    color:#fff;
}
.stButton > button:hover {background:#0854a0; border-color:#0854a0;}

/* ── forms ──────────────────────────────────────────────────── */
[data-testid="stForm"] {
    border:1px solid var(--sap-border);
    border-radius:8px;
    padding:1rem;
    background:#fff;
}

/* ── status badges ──────────────────────────────────────────── */
.badge {display:inline-block;padding:2px 10px;border-radius:6px;font-size:.78rem;font-weight:600;letter-spacing:.02em;}
.badge-green {background:#dcfce7;color:#166534;}
.badge-yellow {background:#fef9c3;color:#854d0e;}
.badge-red {background:#fee2e2;color:#991b1b;}
.badge-blue {background:#dbeafe;color:#1e40af;}
.badge-gray {background:#f3f4f6;color:#374151;}

/* ── section divider ────────────────────────────────────────── */
.section-label {font-size:.72rem;text-transform:uppercase;letter-spacing:.06em;color:var(--sap-muted);margin:1rem 0 .35rem;font-weight:700;}

/* ── hide streamlit chrome ──────────────────────────────────── */
#MainMenu {visibility:hidden;}
footer {visibility:hidden;}
header {visibility:hidden;}
</style>
""", unsafe_allow_html=True)

# ── auth gate ─────────────────────────────────────────────────────────────────
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    col_l, col_m, col_r = st.columns([1, 1.2, 1])
    with col_m:
        st.markdown("### 📦 Jyoti Cards")
        st.caption("Business Management System")
        password = st.text_input("Enter password", type="password", label_visibility="collapsed", placeholder="Password")
        if st.button("Login", use_container_width=True):
            if password == APP_PASSWORD:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Wrong password")
    st.stop()

# ── sidebar nav ───────────────────────────────────────────────────────────────
st.sidebar.markdown("### 📦 Jyoti Cards")
st.sidebar.caption(f"WhatsApp: {business_number()}")
st.sidebar.markdown("---")

PAGES = {
    "🏠  Home": "Home",
    "📋  Items": "Items",
    "🏢  Vendors": "Vendors",
    "👥  Customers": "Customers",
    "📝  Orders": "Orders",
    "📥  Stock In": "Stock In",
    "📊  Inventory": "Inventory",
    "💬  WhatsApp": "WhatsApp",
}

page = st.sidebar.radio("", list(PAGES.keys()), label_visibility="collapsed")
selected = PAGES[page]

db = SessionLocal()
try:
    if selected == "Home":
        from ui.dashboard import render
    elif selected == "Items":
        from ui.products_page import render
    elif selected == "Vendors":
        from ui.vendors_page import render
    elif selected == "Customers":
        from ui.customers_page import render
    elif selected == "Orders":
        from ui.purchase_orders_page import render
    elif selected == "Stock In":
        from ui.stock_intake_page import render
    elif selected == "Inventory":
        from ui.inventory_page import render
    elif selected == "WhatsApp":
        from ui.whatsapp_page import render
    render(db)
finally:
    db.close()
