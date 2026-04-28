import os
import sys

# Streamlit Cloud uses repo root as cwd; local imports (db, gl, bill_pdf) live in this folder.
_DASH_DIR = os.path.dirname(os.path.abspath(__file__))
if _DASH_DIR not in sys.path:
    sys.path.insert(0, _DASH_DIR)

from collections import defaultdict
from typing import Any, Optional

import streamlit as st

# Local: load `Dashboard/.env` first. Then ``apply_streamlit_db_env`` overrides with ``st.secrets`` (Cloud).
import whatsapp_meta  # noqa: F401 — side effect: _load_env()

from streamlit_db_env import apply_streamlit_db_env

apply_streamlit_db_env()

from psycopg import errors as pg_errors

_PG_INTEGRITY = (
    pg_errors.UniqueViolation,
    pg_errors.ForeignKeyViolation,
    pg_errors.NotNullViolation,
    pg_errors.CheckViolation,
)
_PG_ALL = _PG_INTEGRITY + (pg_errors.OperationalError,)
_PG_INT_OR_VAL = _PG_INTEGRITY + (ValueError,)

from datetime import date, timedelta

from gl import journal_list, journal_lines, list_gl_accounts, pnl_to_date, trial_balance

from bill_pdf import build_billing_pdfs_for_co_record, build_billing_pdfs_for_record

from db import (
    compare_vendor_bill_three_way,
    create_customer_invoice_document,
    create_delivery_document,
    create_goods_receipt_document,
    create_purchase_order_document,
    create_sales_order_document,
    create_vendor_bill_document,
    delete_customer,
    delete_customer_order,
    delete_customer_order_billing,
    delete_product_image_rel,
    delete_po_billing,
    delete_vendor,
    delete_vendor_product,
    delete_purchase_order,
    delete_stock_receipt,
    ap_ledger_rows,
    ar_ledger_rows,
    delete_ap_payment,
    delete_ar_payment,
    get_ap_open_balance,
    get_ar_open_balance,
    get_customer,
    get_customer_order,
    get_customer_order_billing,
    get_customer_order_billing_by_order_id,
    get_dashboard_stats,
    get_document_dashboard_stats,
    get_document_history,
    get_goods_receipt_document,
    get_db_path,
    get_uploads_path,
    get_purchase_order_document,
    get_po_billing,
    get_purchase_order,
    get_sales_order_document,
    get_default_warehouse,
    get_vendor_bill_document,
    get_po_status_counts,
    get_stock_receipt,
    get_vendors_with_product_count,
    get_vendor,
    get_vendor_product,
    insert_customer,
    insert_customer_order,
    insert_customer_order_shipment,
    compute_po_billing_amounts,
    insert_customer_order_billing,
    insert_po_billing_for_po,
    insert_vendor,
    insert_vendor_product,
    insert_purchase_order,
    insert_ap_payment,
    insert_ar_payment,
    insert_stock_receipt,
    list_customers,
    list_ap_payments_log,
    list_ar_payments_log,
    list_customer_order_billings,
    list_customer_order_ids_eligible_new_billing,
    list_customer_order_shipments,
    list_customer_orders,
    list_customer_invoice_documents,
    list_delivery_documents,
    list_goods_receipt_documents,
    list_goods_receipt_lines,
    list_inventory_aggregated,
    list_stock_positions_v2,
    list_po_billings,
    list_po_ids_eligible_new_billing,
    list_portal_order_lines_detail,
    list_purchase_orders,
    list_purchase_order_documents,
    list_purchase_order_document_lines,
    list_sales_order_document_lines,
    list_sales_order_documents,
    sum_customer_order_shipment_qty,
    list_stock_receipts,
    list_vendor_bill_documents,
    list_vendor_bill_lines,
    list_vendor_products,
    list_vendor_products_by_vendor,
    list_vendors,
    list_catalog_stock_rows,
    set_product_alternatives,
    list_product_alternative_ids,
    list_sales_line_rows,
    top_categories_by_revenue,
    top_products_by_revenue,
    customers_who_bought_category,
    document_full_path,
    sales_revenue_series,
    product_image_rel_paths,
    product_image_src,
    product_on_hand,
    upload_customer_order_billing_pdf_to_bucket,
    upload_po_billing_pdf_to_bucket,
    save_customer_order_receipt,
    send_customer_order_payment_reminder_wa,
    save_product_uploads_streamlit,
    set_vendor_product_image_paths,
    sum_received_for_po,
    update_customer,
    update_customer_order,
    update_customer_order_billing_record,
    update_po_billing_record,
    update_purchase_order,
    update_stock_receipt,
    update_vendor,
    update_vendor_product,
    LOW_STOCK_THRESHOLD,
)

st.set_page_config(page_title="Business dashboard", layout="wide", initial_sidebar_state="expanded")


@st.cache_data(ttl=45, show_spinner=False)
def _cached_dashboard_stats():
    return get_dashboard_stats()

st.markdown(
    """
<style>
    :root {
        --erp-bg: #f5f7fb;
        --erp-surface: #ffffff;
        --erp-surface-alt: #eef3fb;
        --erp-border: #d9e2ef;
        --erp-text: #172433;
        --erp-muted: #5e7088;
        --erp-accent: #1f5eff;
        --erp-accent-soft: #eaf1ff;
        --erp-success: #0f7b4d;
        --erp-warn: #8c5a00;
    }
    .stApp { background: linear-gradient(180deg, #f8faff 0%, #f3f6fb 100%); color: var(--erp-text); }
    [data-testid="stSidebar"] {
        background: linear-gradient(185deg, #f4f6fb 0%, #eef2f9 100%);
        border-right: 1px solid var(--erp-border);
    }
    [data-testid="stSidebar"] .block-container { padding-top: 0.5rem; }
    .erp-hub-title {
        font-size: 0.72rem;
        font-weight: 700;
        letter-spacing: 0.06em;
        color: #5c6b8a;
        text-transform: uppercase;
        margin: 0.6rem 0 0.2rem 0;
    }
    .erp-shell {
        background: var(--erp-surface);
        border: 1px solid var(--erp-border);
        border-radius: 18px;
        padding: 1.1rem 1.2rem 0.9rem 1.2rem;
        box-shadow: 0 10px 28px rgba(17, 38, 75, 0.06);
        margin-bottom: 1rem;
    }
    .erp-shell h1, .erp-shell h2, .erp-shell h3, .erp-shell p { margin: 0; }
    .erp-kicker {
        font-size: 0.78rem;
        text-transform: uppercase;
        letter-spacing: 0.07em;
        font-weight: 700;
        color: var(--erp-accent);
        margin-bottom: 0.45rem;
    }
    .erp-hero {
        display: flex;
        justify-content: space-between;
        gap: 1rem;
        align-items: flex-start;
        margin-bottom: 0.85rem;
    }
    .erp-hero-title {
        font-size: 1.7rem;
        font-weight: 700;
        color: var(--erp-text);
        line-height: 1.15;
        margin-bottom: 0.2rem;
    }
    .erp-hero-sub {
        color: var(--erp-muted);
        font-size: 0.97rem;
        max-width: 58rem;
    }
    .erp-badges {
        display: flex;
        flex-wrap: wrap;
        gap: 0.45rem;
        margin-top: 0.8rem;
    }
    .erp-badge {
        display: inline-flex;
        align-items: center;
        gap: 0.25rem;
        border-radius: 999px;
        padding: 0.3rem 0.7rem;
        border: 1px solid var(--erp-border);
        background: var(--erp-surface-alt);
        color: var(--erp-text);
        font-size: 0.82rem;
        font-weight: 600;
    }
    .erp-badge-muted {
        background: #f8fafc;
        color: var(--erp-muted);
    }
    .erp-help {
        background: linear-gradient(180deg, #fbfcff 0%, #f3f7ff 100%);
        border: 1px dashed #c9d7ef;
        border-radius: 14px;
        padding: 0.8rem 0.95rem;
        min-width: 16rem;
    }
    .erp-help-label {
        font-size: 0.76rem;
        text-transform: uppercase;
        letter-spacing: 0.07em;
        color: var(--erp-muted);
        margin-bottom: 0.25rem;
        font-weight: 700;
    }
    .erp-help-body {
        font-size: 0.9rem;
        color: var(--erp-text);
        line-height: 1.45;
    }
    .erp-flow {
        margin-top: 0.7rem;
        color: var(--erp-muted);
        font-size: 0.88rem;
        font-weight: 600;
    }
    .erp-section-note {
        margin: 0.35rem 0 1rem 0;
        color: var(--erp-muted);
        font-size: 0.92rem;
    }
    div[data-testid="stMetric"] {
        background: var(--erp-surface);
        border: 1px solid var(--erp-border);
        border-radius: 16px;
        padding: 0.75rem 0.85rem;
        box-shadow: 0 8px 18px rgba(16, 36, 70, 0.04);
    }
    div[data-testid="stDataFrame"] {
        border: 1px solid var(--erp-border);
        border-radius: 14px;
        overflow: hidden;
        background: var(--erp-surface);
    }
</style>
""",
    unsafe_allow_html=True,
)

if st.session_state.get("pending_erp_menu"):
    st.session_state.erp_menu = st.session_state.pop("pending_erp_menu")

if "page" not in st.session_state:
    st.session_state.page = None
if "dash_mode" not in st.session_state:
    st.session_state.dash_mode = "home"
if "entity_sub" not in st.session_state:
    st.session_state.entity_sub = "Dashboard"
if "order_sub" not in st.session_state:
    st.session_state.order_sub = "Dashboard"
if "entity_edit_cust" not in st.session_state:
    st.session_state.entity_edit_cust = None
if "entity_edit_ven" not in st.session_state:
    st.session_state.entity_edit_ven = None
if "po_eid" not in st.session_state:
    st.session_state.po_eid = None
if "co_eid" not in st.session_state:
    st.session_state.co_eid = None
if "inv_main" not in st.session_state:
    st.session_state.inv_main = "status"
if "inv_receipt_mode" not in st.session_state:
    st.session_state.inv_receipt_mode = "po"
if "po_doc_draft_lines" not in st.session_state:
    st.session_state.po_doc_draft_lines = []
if "so_doc_draft_lines" not in st.session_state:
    st.session_state.so_doc_draft_lines = []
if "po_workspace_tab" not in st.session_state:
    st.session_state.po_workspace_tab = "Document workspace"
if "sales_workspace_tab" not in st.session_state:
    st.session_state.sales_workspace_tab = "Document workspace"

_DMODES = frozenset(
    {
        "home",
        "customer",
        "vendor",
        "product",
        "po",
        "po_mgmt",
        "inv",
        "cust_order",
        "co_billing",
        "billing",
        "ar",
        "ap",
        "gl",
        "journals",
        "pnl",
        "trial",
        "ops",
        "ai",
        "entity_dash",
        "order_dash",
        "acct_dash",
    }
)
_LIST_FIRST_AM = frozenset({"customer", "vendor", "po_mgmt", "cust_order"})

# --- sidebar: Dashboard · Entities · Order management · … · AI) ---
with st.sidebar:
    st.markdown('<p class="erp-hub-title">App</p>', unsafe_allow_html=True)
    if "inv_sub" not in st.session_state:
        st.session_state.inv_sub = "status"
    if "erp_bill_seg" not in st.session_state:
        st.session_state.erp_bill_seg = "Customer sales (PDFs)"
    _EM = {
        "Dashboard": "home",
        "Entities": {
            "Dashboard": "entity_dash",
            "Customers": "customer",
            "Vendors": "vendor",
        },
        "Order management": {
            "Dashboard": "order_dash",
            "Vendor orders": "po_mgmt",
            "Customer orders": "cust_order",
        },
    }
    erp_menu = st.radio(
        "Navigation",
        [
            "Dashboard",
            "Entities",
            "Order management",
            "Catalog (SKUs)",
            "Inventory",
            "Operations",
            "Accounts",
            "Billing",
            "AI Assistant",
        ],
        key="erp_menu",
    )
    dmode_res = "home"
    if erp_menu == "Dashboard":
        dmode_res = "home"
    elif erp_menu == "Entities":
        dmode_res = _EM["Entities"].get(
            st.session_state.get("entity_sub", "Dashboard"), "entity_dash"
        )
    elif erp_menu == "Order management":
        dmode_res = _EM["Order management"].get(
            st.session_state.get("order_sub", "Dashboard"), "order_dash"
        )
    elif erp_menu == "Catalog (SKUs)":
        dmode_res = "product"
    elif erp_menu == "Inventory":
        dmode_res = "inv"
    elif erp_menu == "Operations":
        dmode_res = "ops"
    elif erp_menu == "Accounts":
        _dmx = st.session_state.get("dash_mode", "home")
        dmode_res = _dmx if _dmx in (
            "ar",
            "ap",
            "gl",
            "journals",
            "pnl",
            "trial",
        ) else "acct_dash"
    elif erp_menu == "Billing":
        dmode_res = (
            "co_billing"
            if st.session_state.get("erp_bill_seg", "Customer sales (PDFs)")
            == "Customer sales (PDFs)"
            else "billing"
        )
    else:
        dmode_res = "ai"
    st.session_state.dash_mode = dmode_res
    inv_x = f"{st.session_state.get('inv_main', 'status')}_{st.session_state.get('inv_receipt_mode', 'po')}"
    esx = st.session_state.get("entity_sub", "Dashboard")
    osx = st.session_state.get("order_sub", "Dashboard")
    acct_x = st.session_state.get("app_acct", "")
    bill_x = st.session_state.get("erp_bill_seg", "")
    nav_sig = (erp_menu, dmode_res, inv_x, esx, osx, acct_x, bill_x)
    if nav_sig != st.session_state.get("_nav_sig"):
        st.session_state.page = None
        st.session_state._nav_sig = nav_sig
    if st.session_state.dash_mode not in _DMODES:
        st.session_state.dash_mode = "home"
    st.divider()
    if st.button(
        "Refresh app",
        use_container_width=True,
        help="Rerun; clears in-widget state.",
        key="erp_ref",
    ):
        st.rerun()
    st.caption(f"DB: `{get_db_path()}`")

dmode = st.session_state.dash_mode
page = st.session_state.page
SECTION_TITLE = {
    "entity_dash": "Entities · overview",
    "order_dash": "Order management · overview",
    "customer": "Entities · customers",
    "vendor": "Entities · vendors",
    "product": "Catalog (vendor offerings)",
    "po": "Vendor · new purchase order",
    "po_mgmt": "Vendor · purchase orders",
    "inv": "Inventory (stock)",
    "cust_order": "Customer · orders (portal sales)",
    "co_billing": "Customer · billing (sales PDFs)",
    "billing": "Purchase billing (vendor)",
    "ar": "Accounting · AR (receivable)",
    "ap": "Accounting · AP (payable)",
    "gl": "Accounting · GL accounts",
    "journals": "Accounting · Journal register",
    "pnl": "Accounting · P&L",
    "trial": "Accounting · Trial balance",
    "acct_dash": "Accounts",
    "ops": "Operations · queue",
    "ai": "AI assistant",
}
CO_STATUS_OPTS = {
    "placed": "Order booked",
    "confirmed": "Confirmed",
    "shipped": "Shipped",
    "delivered": "Delivered",
    "in_progress": "In progress (legacy)",
}
PO_STATUS_OPTS = {
    "open": "Open",
    "in_progress": "In progress",
    "closed": "Closed",
    "in_dispute": "In dispute (price or quantity)",
}

# --- HOME: full business dashboard; quick links to each section ---


def _crud_tiles(pfx: str) -> None:
    st.subheader("Actions")
    t1, t2, t3, t4 = st.columns(4)
    with t1:
        if st.button("View", use_container_width=True, key=f"{pfx}_v"):
            st.session_state.page = "view"
            st.rerun()
    with t2:
        if st.button("Add", use_container_width=True, key=f"{pfx}_a"):
            st.session_state.page = "add"
            st.rerun()
    with t3:
        if st.button("Modify", use_container_width=True, key=f"{pfx}_m"):
            st.session_state.page = "modify"
            st.rerun()
    with t4:
        if st.button("Delete", use_container_width=True, type="primary", key=f"{pfx}_d"):
            st.session_state.page = "delete"
            st.rerun()
    if st.button("Clear action", key=f"{pfx}_c"):
        st.session_state.page = None
        st.rerun()


def _render_section_intro(
    title: str,
    subtitle: str,
    *,
    kicker: str = "ERP workspace",
    flow: Optional[str] = None,
    badges: Optional[list[str]] = None,
    help_text: Optional[str] = None,
) -> None:
    badge_html = ""
    if badges:
        badge_html = '<div class="erp-badges">' + "".join(
            f'<span class="erp-badge">{b}</span>' for b in badges
        ) + "</div>"
    help_html = ""
    if help_text:
        help_html = (
            '<div class="erp-help">'
            '<div class="erp-help-label">Operator guidance</div>'
            f'<div class="erp-help-body">{help_text}</div>'
            "</div>"
        )
    flow_html = f'<div class="erp-flow">{flow}</div>' if flow else ""
    st.markdown(
        f"""
        <section class="erp-shell">
            <div class="erp-kicker">{kicker}</div>
            <div class="erp-hero">
                <div>
                    <div class="erp-hero-title">{title}</div>
                    <div class="erp-hero-sub">{subtitle}</div>
                    {badge_html}
                    {flow_html}
                </div>
                {help_html}
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def _action_dropdown(pfx: str) -> None:
    act_labs = [("View", "view"), ("Add", "add"), ("Modify", "modify"), ("Delete", "delete")]
    p = st.session_state.get("page")
    if p is None and st.session_state.get("dash_mode", "") not in _LIST_FIRST_AM:
        p = "view"
        st.session_state.page = "view"
    st.markdown(
        '<div class="erp-section-note">Choose one action for this module. The active step stays selected until you navigate away.</div>',
        unsafe_allow_html=True,
    )
    cols = st.columns([1, 1, 1, 1, 0.9])
    for idx, (label, val) in enumerate(act_labs):
        with cols[idx]:
            if st.button(
                label,
                key=f"actbtn_{pfx}_{val}_{st.session_state.dash_mode}",
                use_container_width=True,
                type="primary" if p == val else "secondary",
            ):
                st.session_state.page = val
                st.rerun()
    with cols[4]:
        if st.button(
            "Reset",
            key=f"actclr_{pfx}_{st.session_state.dash_mode}",
            use_container_width=True,
        ):
            st.session_state.page = "view" if st.session_state.get("dash_mode", "") not in _LIST_FIRST_AM else None
            st.rerun()


def _go(dmode: str) -> None:
    st.session_state.page = None
    st.session_state.entity_edit_cust = None
    st.session_state.entity_edit_ven = None
    st.session_state.po_eid = None
    st.session_state.co_eid = None
    st.session_state.dash_mode = dmode
    st.session_state.pending_erp_menu = {
        "home": "Dashboard",
        "entity_dash": "Entities",
        "customer": "Entities",
        "vendor": "Entities",
        "order_dash": "Order management",
        "po_mgmt": "Order management",
        "po": "Order management",
        "cust_order": "Order management",
        "product": "Catalog (SKUs)",
        "inv": "Inventory",
        "ops": "Operations",
        "ai": "AI Assistant",
        "ar": "Accounts",
        "ap": "Accounts",
        "gl": "Accounts",
        "journals": "Accounts",
        "pnl": "Accounts",
        "trial": "Accounts",
        "co_billing": "Billing",
        "billing": "Billing",
        "acct_dash": "Accounts",
    }.get(dmode, "Dashboard")
    st.session_state.entity_sub = {
        "entity_dash": "Dashboard",
        "customer": "Customers",
        "vendor": "Vendors",
    }.get(dmode, st.session_state.get("entity_sub", "Dashboard"))
    st.session_state.order_sub = {
        "order_dash": "Dashboard",
        "po_mgmt": "Vendor orders",
        "cust_order": "Customer orders",
    }.get(dmode, st.session_state.get("order_sub", "Dashboard"))
    if dmode == "co_billing":
        st.session_state.erp_bill_seg = "Customer sales (PDFs)"
    if dmode == "billing":
        st.session_state.erp_bill_seg = "Vendor purchase"
    if dmode in ("ar", "ap", "gl", "journals", "pnl", "trial"):
        st.session_state.app_acct = {
            "ar": "AR (receivable)",
            "ap": "AP (payable)",
            "gl": "GL accounts",
            "journals": "Journals",
            "pnl": "P&L",
            "trial": "Trial balance",
        }[dmode]
    st.rerun()


def _acct_main_tiles(cur: str) -> None:
    tiles = [
        ("ar", "AR (receivable)"),
        ("ap", "AP (payable)"),
        ("gl", "GL accounts"),
        ("journals", "Journals"),
        ("pnl", "P&L"),
        ("trial", "Trial balance"),
    ]
    c1, c2, c3 = st.columns(3)
    c4, c5, c6 = st.columns(3)
    for i, (dmd, lab) in enumerate(tiles):
        with (c1, c2, c3, c4, c5, c6)[i]:
            is_on = cur == dmd
            if st.button(
                lab,
                key=f"acc_tile_{dmd}",
                use_container_width=True,
                type="primary" if is_on else "secondary",
            ):
                if not is_on:
                    _go(dmd)


def _render_dashboard_sales() -> None:
    """Category filter + grouped portal order lines."""
    _DK: dict[str, str] = {
        "Customer": "customer_name",
        "Item (SKU)": "sku",
        "Rate band": "rate_band",
        "Category": "category",
    }
    rows = list_portal_order_lines_detail()
    if not rows:
        st.info("No portal orders yet — data will appear when customers place orders.")
        return

    st.markdown("##### Customer buying insight")
    cats = sorted({str(r["category"]) for r in rows})
    c1, c2 = st.columns(2)
    with c1:
        cat_f = st.selectbox(
            "Category focus",
            ["(all)"] + cats,
            key="dash_cat_f",
            help="Filter all tables below to one product category.",
        )
    with c2:
        st.caption("Check who bought the focused category (after you pick one).")

    filtered = rows if cat_f == "(all)" else [r for r in rows if str(r["category"]) == cat_f]

    if cat_f != "(all)":
        by_cust: dict[str, float] = defaultdict(float)
        by_cust_n: dict[str, int] = defaultdict(int)
        for r in filtered:
            by_cust[str(r["customer_name"])] += float(r["line_value"])
            by_cust_n[str(r["customer_name"])] += 1
        st.markdown(f"**Customers with orders in “{cat_f}”**")
        if by_cust:
            st.dataframe(
                [
                    {"Customer": k, "Orders": by_cust_n[k], "Line value ₹": round(by_cust[k], 2)}
                    for k in sorted(by_cust.keys(), key=str.lower)
                ],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("No rows in this category.")

    pri = st.selectbox(
        "Group by",
        ["Customer", "Item (SKU)", "Rate band"],
        key="dash_grp_pri",
    )
    sec_opts = ["—"] + [x for x in ["Category", "Item (SKU)", "Customer", "Rate band"] if x != pri]
    sec = st.selectbox("Sub-group", sec_opts, key="dash_grp_sec")

    k1 = _DK[pri]
    k2 = _DK[sec] if sec != "—" else None

    if k2 is None:
        agg: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"qty": 0.0, "value": 0.0, "lines": 0}
        )
        for r in filtered:
            key = str(r[k1])
            agg[key]["qty"] += float(r["quantity"])
            agg[key]["value"] += float(r["line_value"])
            agg[key]["lines"] += 1
        st.dataframe(
            [
                {
                    pri: k,
                    "Lines": v["lines"],
                    "Qty": round(v["qty"], 3),
                    "Value ₹": round(v["value"], 2),
                }
                for k, v in sorted(agg.items(), key=lambda x: (-x[1]["value"], x[0].lower()))
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        tree: dict[str, dict[str, dict[str, Any]]] = defaultdict(
            lambda: defaultdict(lambda: {"qty": 0.0, "value": 0.0, "lines": 0})
        )
        for r in filtered:
            a = str(r[k1])
            b = str(r[k2])
            tree[a][b]["qty"] += float(r["quantity"])
            tree[a][b]["value"] += float(r["line_value"])
            tree[a][b]["lines"] += 1
        for outer in sorted(tree.keys(), key=str.lower):
            with st.expander(f"{pri}: **{outer}**  ·  {len(tree[outer])} sub-groups", expanded=False):
                st.dataframe(
                    [
                        {
                            sec: inner,
                            "Lines": v["lines"],
                            "Qty": round(v["qty"], 3),
                            "Value ₹": round(v["value"], 2),
                        }
                        for inner, v in sorted(
                            tree[outer].items(), key=lambda x: (-x[1]["value"], x[0].lower())
                        )
                    ],
                    use_container_width=True,
                    hide_index=True,
                )


def _reset_po_doc_draft() -> None:
    st.session_state.po_doc_draft_lines = []


def _reset_so_doc_draft() -> None:
    st.session_state.so_doc_draft_lines = []


def _render_doc_table(title: str, rows: list[dict], columns: list[str]) -> None:
    st.markdown(f"##### {title}")
    if not rows:
        st.caption("No records yet.")
        return
    st.dataframe([{k: r.get(k) for k in columns} for r in rows], use_container_width=True, hide_index=True)


def _download_if_present(label: str, rel_path: Optional[str], filename: str, *, key: str) -> None:
    ap = document_full_path(rel_path)
    if not ap or not os.path.isfile(ap):
        st.caption("No file available.")
        return
    with open(ap, "rb") as f:
        data = f.read()
    mime = "application/pdf" if ap.lower().endswith(".pdf") else "application/octet-stream"
    st.download_button(label, data, file_name=filename, mime=mime, key=key, use_container_width=True)


def _render_po_document_workspace() -> None:
    docs = list_purchase_order_documents()
    receipts = list_goods_receipt_documents()
    bills = list_vendor_bill_documents()
    vlabels, _ = _vendor_labels()
    default_wh = get_default_warehouse()
    st.caption(f"Single warehouse: **{default_wh.name}**. Flow: create PO -> receive goods -> enter vendor bill -> review 3-way match.")

    top = st.radio(
        "Purchasing workspace",
        ["Overview", "New PO", "Receive goods", "Vendor bill", "History"],
        horizontal=True,
        key="po_doc_ws_mode",
        label_visibility="collapsed",
    )
    if top == "Overview":
        c1, c2, c3 = st.columns(3)
        c1.metric("PO documents", len(docs))
        c2.metric("Goods receipts", len(receipts))
        c3.metric("Vendor bills", len(bills))
        _render_doc_table(
            "Latest PO documents",
            [
                {
                    "PO no.": d.get("doc_no"),
                    "Vendor": d.get("vendor_name") or "—",
                    "Status": str(d.get("status") or "—").replace("_", " ").title(),
                    "Created": str(d.get("created_at") or "")[:10],
                }
                for d in docs[:15]
            ],
            ["PO no.", "Vendor", "Status", "Created"],
        )
        _render_doc_table(
            "Vendor bills and 3-way match",
            [
                {
                    "Bill no.": b.get("bill_no"),
                    "Vendor": b.get("vendor_name") or "—",
                    "PO": b.get("po_doc_no") or "—",
                    "Match": str(b.get("match_status") or "pending").replace("_", " ").title(),
                    "Summary": (b.get("match_summary") or "Pending review")[:90],
                }
                for b in bills[:15]
            ],
            ["Bill no.", "Vendor", "PO", "Match", "Summary"],
        )
        if docs:
            pick_map = {f"{d['doc_no']}  ·  {d.get('vendor_name') or '—'}": int(d["id"]) for d in docs}
            pick = st.selectbox("PO document details", list(pick_map.keys()), key="po_doc_detail_pick")
            doc = get_purchase_order_document(pick_map[pick])
            lines = list_purchase_order_document_lines(pick_map[pick])
            if doc:
                st.caption(f"Status: **{str(doc.get('status') or 'open').title()}**")
                st.dataframe(lines, use_container_width=True, hide_index=True)
                _download_if_present("Download PO PDF", doc.get("pdf_path"), f"{doc.get('doc_no') or 'po'}.pdf", key=f"po_pdf_dl_{doc['id']}")
        if bills:
            bill_map = {f"{b['bill_no']}  ·  {b.get('vendor_name') or '—'}": int(b["id"]) for b in bills}
            bpick = st.selectbox("Vendor bill details", list(bill_map.keys()), key="vb_detail_pick")
            bill = get_vendor_bill_document(bill_map[bpick])
            if bill:
                st.caption(f"3-way match: **{str(bill.get('match_status') or 'pending').replace('_', ' ').title()}**")
                st.write((bill.get("match_summary") or "Pending review").strip())
                st.dataframe(list_vendor_bill_lines(int(bill["id"])), use_container_width=True, hide_index=True)
                ap = document_full_path(bill.get("bill_image_path"))
                if ap and os.path.isfile(ap) and ap.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                    st.image(ap, width=320, caption="Vendor bill upload")
    elif top == "New PO":
        st.markdown("##### New purchase order")
        if not vlabels:
            st.warning("Add a vendor before creating a PO document.")
            return
        pv = st.selectbox("Vendor *", list(vlabels.keys()), key="po_doc_vendor_pick")
        vid = vlabels.get(pv)
        prods = list_vendor_products_by_vendor(int(vid)) if vid is not None else []
        if not prods:
            st.warning("This vendor has no products yet.")
            return
        prod_map = {f"{p.our_product_id} — {p.name}  [p{p.id}]": p for p in prods}
        with st.form("po_doc_add_line"):
            pl = st.selectbox("Product *", list(prod_map.keys()), key="po_doc_line_product")
            qty = st.number_input("Quantity *", min_value=0.001, value=1.0, step=1.0, format="%.3f")
            unit = st.number_input(
                "Unit cost base price (₹) *",
                min_value=0.0,
                value=float(prod_map[pl].cost_price or 0.0),
                step=0.01,
                format="%.2f",
            )
            note = st.text_input("Line note", value="")
            if st.form_submit_button("Add line", use_container_width=True):
                p = prod_map[pl]
                st.session_state.po_doc_draft_lines.append(
                    {
                        "product_id": int(p.id),
                        "sku": p.our_product_id,
                        "item_name": p.name,
                        "quantity": float(qty),
                        "unit_cost": float(unit),
                        "notes": note or None,
                    }
                )
                st.rerun()
        draft = st.session_state.po_doc_draft_lines
        if draft:
            st.dataframe(
                [
                    {
                        "SKU": x["sku"],
                        "Product": x["item_name"],
                        "Qty": x["quantity"],
                        "Unit cost": x["unit_cost"],
                        "Base": round(float(x["quantity"]) * float(x["unit_cost"]), 2),
                    }
                    for x in draft
                ],
                use_container_width=True,
                hide_index=True,
            )
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Clear draft lines", key="po_doc_clear", use_container_width=True):
                _reset_po_doc_draft()
                st.rerun()
        with c2:
            pass
        with st.form("po_doc_submit"):
            vend = get_vendor(int(vid)) if vid is not None else None
            pt = st.text_input("Payment terms (days)", value="" if not vend or vend.payment_terms is None else str(int(vend.payment_terms)))
            bl = st.text_input("Billing condition", value="" if not vend or vend.billing is None else str(int(vend.billing)))
            trn = st.text_input("Transport / courier name", value="")
            trno = st.text_input("Transport number", value="")
            notes = st.text_area("Document note", value="", height=80)
            if st.form_submit_button("Create PO document + PDF", type="primary", use_container_width=True):
                if not draft:
                    st.error("Add at least one line.")
                else:
                    pti, e1 = _opt_int(pt)
                    bli, e2 = _opt_int(bl)
                    if e1:
                        st.error(f"Payment terms: {e1}")
                    elif e2:
                        st.error(f"Billing condition: {e2}")
                    else:
                        try:
                            doc_id = create_purchase_order_document(
                                int(vid),
                                draft,
                                notes=notes or None,
                                payment_terms=pti,
                                billing=bli,
                                transport_name=trn or None,
                                transport_number=trno or None,
                            )
                            _reset_po_doc_draft()
                            st.success(f"PO document created: #{doc_id}")
                            st.rerun()
                        except Exception as e:
                            st.error(str(e)[:500])
    elif top == "Receive goods":
        if not docs:
            st.info("Create a PO document first.")
            return
        open_docs = {
            f"{d['doc_no']}  ·  {d.get('vendor_name') or '—'}  ·  {str(d.get('status') or '').title()}": int(d["id"])
            for d in docs
        }
        pick = st.selectbox("Purchase order *", list(open_docs.keys()), key="grn_doc_pick")
        doc_id = open_docs[pick]
        lines = list_purchase_order_document_lines(doc_id)
        with st.form("goods_receipt_doc_form"):
            receipt_ref = st.text_input("Vendor receipt ref", value="")
            grn = st.text_input("GRN / inward number", value="")
            up = st.file_uploader("Upload vendor receipt image", type=["png", "jpg", "jpeg", "webp", "pdf"], key="grn_upload")
            qty_map: dict[int, float] = {}
            for line in lines:
                qty_map[int(line["id"])] = st.number_input(
                    f"{line['sku']} — {line['item_name']} (ordered {float(line['quantity']):g})",
                    min_value=0.0,
                    value=0.0,
                    step=1.0,
                    format="%.3f",
                    key=f"grn_qty_{line['id']}",
                )
            notes = st.text_area("Receipt note", value="", height=64)
            if st.form_submit_button("Post goods receipt", type="primary", use_container_width=True):
                rec_lines = [{"po_line_id": lid, "quantity": qty} for lid, qty in qty_map.items() if float(qty) > 0.0001]
                if not rec_lines:
                    st.error("Enter at least one received quantity.")
                else:
                    try:
                        create_goods_receipt_document(
                            doc_id,
                            rec_lines,
                            vendor_receipt_ref=receipt_ref or None,
                            grn_number=grn or None,
                            notes=notes or None,
                            receipt_image_bytes=up.getvalue() if up is not None else None,
                            receipt_image_name=up.name if up is not None else "receipt.jpg",
                        )
                        st.success("Goods receipt posted.")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e)[:500])
    elif top == "Vendor bill":
        if not docs:
            st.info("Create a PO document first.")
            return
        pick_map = {f"{d['doc_no']}  ·  {d.get('vendor_name') or '—'}": int(d["id"]) for d in docs}
        pick = st.selectbox("PO to bill *", list(pick_map.keys()), key="vb_po_pick")
        doc_id = pick_map[pick]
        lines = list_purchase_order_document_lines(doc_id)
        rcpts = [r for r in receipts if int(r.get("po_doc_id") or 0) == int(doc_id)]
        rcpt_opts = {"(optional) Link to all receipts": None}
        rcpt_opts.update({f"{r['receipt_no']}  ·  {str(r.get('created_at') or '')[:10]}": int(r["id"]) for r in rcpts})
        with st.form("vendor_bill_doc_form"):
            rcpt_pick = st.selectbox("Goods receipt link", list(rcpt_opts.keys()), key="vb_rcpt_pick")
            inv_ref = st.text_input("Vendor invoice ref", value="")
            vendor_gst = st.text_input("Vendor GST number / ref", value="")
            up = st.file_uploader("Upload vendor bill image/PDF", type=["png", "jpg", "jpeg", "webp", "pdf"], key="vb_upload")
            line_payload = []
            for line in lines:
                qty = st.number_input(
                    f"Billed qty for {line['sku']} — {line['item_name']}",
                    min_value=0.0,
                    value=float(line["quantity"]),
                    step=1.0,
                    format="%.3f",
                    key=f"vb_qty_{line['id']}",
                )
                unit = st.number_input(
                    f"Billed unit cost for {line['sku']}",
                    min_value=0.0,
                    value=float(line["unit_cost"]),
                    step=0.01,
                    format="%.2f",
                    key=f"vb_cost_{line['id']}",
                )
                if qty > 0.0001:
                    line_payload.append({"po_line_id": int(line["id"]), "quantity": float(qty), "unit_cost": float(unit)})
            notes = st.text_area("Bill note", value="", height=64)
            if st.form_submit_button("Save vendor bill + run 3-way match", type="primary", use_container_width=True):
                try:
                    bid = create_vendor_bill_document(
                        doc_id,
                        line_payload,
                        goods_receipt_id=rcpt_opts[rcpt_pick],
                        vendor_invoice_ref=inv_ref or None,
                        vendor_gstin=vendor_gst or None,
                        notes=notes or None,
                        bill_image_bytes=up.getvalue() if up is not None else None,
                        bill_image_name=up.name if up is not None else "vendor_bill.jpg",
                    )
                    compare_vendor_bill_three_way(bid)
                    st.success("Vendor bill recorded.")
                    st.rerun()
                except Exception as e:
                    st.error(str(e)[:500])
    else:
        entity = st.radio("History view", ["Vendor", "Product"], horizontal=True, key="po_hist_entity")
        if entity == "Vendor":
            if not vlabels:
                st.info("No vendors yet.")
                return
            pick = st.selectbox("Vendor", list(vlabels.keys()), key="po_hist_vendor_pick")
            hist = get_document_history("vendor", int(vlabels[pick]))
        else:
            plabels, _ = _product_labels()
            if not plabels:
                st.info("No products yet.")
                return
            ppick = st.selectbox("Product", list(plabels.keys()), key="po_hist_product_pick")
            hist = get_document_history("product", int(plabels[ppick]))
        _render_doc_table("Purchase orders", hist["purchase_orders"], ["doc_no", "status", "created_at"])
        _render_doc_table("Goods receipts", hist["goods_receipts"], ["receipt_no", "grn_number", "created_at"])
        _render_doc_table("Vendor bills", hist["vendor_bills"], ["bill_no", "match_status", "created_at"])


def _render_sales_document_workspace() -> None:
    docs = list_sales_order_documents()
    deliveries = list_delivery_documents()
    invoices = list_customer_invoice_documents()
    clabels, _ = _customer_labels()
    default_wh = get_default_warehouse()
    st.caption(f"Single warehouse: **{default_wh.name}**. Flow: create sales order -> deliver stock -> issue customer invoice.")

    top = st.radio(
        "Sales workspace",
        ["Overview", "New sales order", "Delivery", "Invoice", "History"],
        horizontal=True,
        key="sales_doc_ws_mode",
        label_visibility="collapsed",
    )
    if top == "Overview":
        c1, c2, c3 = st.columns(3)
        c1.metric("Sales orders", len(docs))
        c2.metric("Deliveries", len(deliveries))
        c3.metric("Customer invoices", len(invoices))
        _render_doc_table(
            "Latest sales orders",
            [
                {
                    "Sales order": d.get("doc_no"),
                    "Customer": d.get("customer_name") or "—",
                    "Status": str(d.get("status") or "—").replace("_", " ").title(),
                    "Created": str(d.get("created_at") or "")[:10],
                }
                for d in docs[:15]
            ],
            ["Sales order", "Customer", "Status", "Created"],
        )
        _render_doc_table(
            "Latest invoices",
            [
                {
                    "Invoice": i.get("invoice_no"),
                    "Customer": i.get("customer_name") or "—",
                    "Sales order": i.get("sales_order_no") or "—",
                    "Amount": round(float(i.get("grand_total") or 0), 2),
                }
                for i in invoices[:15]
            ],
            ["Invoice", "Customer", "Sales order", "Amount"],
        )
        if docs:
            pick_map = {f"{d['doc_no']}  ·  {d.get('customer_name') or '—'}": int(d["id"]) for d in docs}
            pick = st.selectbox("Sales order details", list(pick_map.keys()), key="so_doc_detail_pick")
            doc = get_sales_order_document(pick_map[pick])
            lines = list_sales_order_document_lines(pick_map[pick])
            if doc:
                st.caption(f"Status: **{str(doc.get('status') or 'placed').replace('_', ' ').title()}**")
                st.dataframe(lines, use_container_width=True, hide_index=True)
        if invoices:
            inv_map = {f"{i['invoice_no']}  ·  {i.get('customer_name') or '—'}": int(i["id"]) for i in invoices}
            ipick = st.selectbox("Invoice details", list(inv_map.keys()), key="inv_doc_detail_pick")
            inv = next((x for x in invoices if int(x["id"]) == inv_map[ipick]), None)
            if inv:
                st.write(f"Taxable: ₹{float(inv.get('base_total') or 0):,.2f}  |  GST: ₹{float(inv.get('gst_total') or 0):,.2f}  |  Total: ₹{float(inv.get('grand_total') or 0):,.2f}")
                _download_if_present("Download invoice PDF", inv.get("pdf_path"), f"{inv.get('invoice_no') or 'invoice'}.pdf", key=f"inv_pdf_dl_{inv['id']}")
    elif top == "New sales order":
        if not clabels:
            st.warning("Add a customer first.")
            return
        pick = st.selectbox("Customer *", list(clabels.keys()), key="so_doc_customer_pick")
        cid = clabels[pick]
        plabels, _ = _product_labels()
        if not plabels:
            st.warning("Add products first.")
            return
        with st.form("so_doc_add_line"):
            ppick = st.selectbox("Product *", list(plabels.keys()), key="so_doc_line_product")
            qty = st.number_input("Quantity *", min_value=0.001, value=1.0, step=1.0, format="%.3f")
            price = st.number_input("Selling price incl. GST (₹) *", min_value=0.01, value=118.0, step=0.01, format="%.2f")
            note = st.text_input("Line note", value="")
            if st.form_submit_button("Add line", use_container_width=True):
                p_id = int(plabels[ppick])
                p = get_vendor_product(p_id)
                if p:
                    st.session_state.so_doc_draft_lines.append(
                        {
                            "product_id": p_id,
                            "sku": p.our_product_id,
                            "item_name": p.name,
                            "quantity": float(qty),
                            "unit_price_incl_gst": float(price),
                            "notes": note or None,
                        }
                    )
                    st.rerun()
        draft = st.session_state.so_doc_draft_lines
        if draft:
            st.dataframe(
                [
                    {
                        "SKU": x["sku"],
                        "Product": x["item_name"],
                        "Qty": x["quantity"],
                        "Selling price incl. GST": x["unit_price_incl_gst"],
                        "Base": round((x["unit_price_incl_gst"] / 1.18) * x["quantity"], 2),
                        "GST": round((x["unit_price_incl_gst"] - (x["unit_price_incl_gst"] / 1.18)) * x["quantity"], 2),
                        "Line total": round(x["unit_price_incl_gst"] * x["quantity"], 2),
                    }
                    for x in draft
                ],
                use_container_width=True,
                hide_index=True,
            )
        with st.form("so_doc_submit"):
            notes = st.text_area("Sales order note", value="", height=80)
            submitted = st.form_submit_button("Create sales order", type="primary", use_container_width=True)
            if submitted:
                if not draft:
                    st.error("Add at least one line.")
                else:
                    try:
                        create_sales_order_document(int(cid), draft, notes=notes or None)
                        _reset_so_doc_draft()
                        st.success("Sales order created.")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e)[:500])
        if st.button("Clear sales order draft", key="so_doc_clear", use_container_width=True):
            _reset_so_doc_draft()
            st.rerun()
    elif top == "Delivery":
        if not docs:
            st.info("Create a sales order first.")
            return
        pick_map = {f"{d['doc_no']}  ·  {d.get('customer_name') or '—'}": int(d["id"]) for d in docs}
        pick = st.selectbox("Sales order *", list(pick_map.keys()), key="delivery_doc_pick")
        so_id = pick_map[pick]
        lines = list_sales_order_document_lines(so_id)
        with st.form("delivery_doc_form"):
            rcpt = st.text_input("Delivery receipt number", value="")
            contact = st.text_input("Delivery contact", value="")
            up = st.file_uploader("Upload delivery proof image", type=["png", "jpg", "jpeg", "webp", "pdf"], key="delivery_upload")
            payload = []
            for line in lines:
                qty = st.number_input(
                    f"Deliver qty for {line['sku']} — {line['item_name']}",
                    min_value=0.0,
                    value=float(line["quantity"]),
                    step=1.0,
                    format="%.3f",
                    key=f"delivery_qty_{line['id']}",
                )
                if qty > 0.0001:
                    payload.append({"sales_order_line_id": int(line["id"]), "quantity": float(qty)})
            notes = st.text_area("Delivery note", value="", height=64)
            if st.form_submit_button("Post delivery", type="primary", use_container_width=True):
                try:
                    create_delivery_document(
                        so_id,
                        payload,
                        delivery_receipt_number=rcpt or None,
                        delivery_contact=contact or None,
                        notes=notes or None,
                        receipt_image_bytes=up.getvalue() if up is not None else None,
                        receipt_image_name=up.name if up is not None else "delivery.jpg",
                    )
                    st.success("Delivery posted.")
                    st.rerun()
                except Exception as e:
                    st.error(str(e)[:500])
    elif top == "Invoice":
        if not docs:
            st.info("Create a sales order first.")
            return
        shipped = [d for d in docs if str(d.get("status") or "").strip().lower() == "shipped"]
        if not shipped:
            st.info("Post a delivery first so the sales order becomes shipped.")
            return
        pick_map = {f"{d['doc_no']}  ·  {d.get('customer_name') or '—'}": int(d["id"]) for d in shipped}
        pick = st.selectbox("Shipped sales order *", list(pick_map.keys()), key="invoice_doc_pick")
        so_id = pick_map[pick]
        rel_del = [d for d in deliveries if int(d.get("sales_order_id") or 0) == int(so_id)]
        del_map = {"(optional) No explicit delivery link": None}
        del_map.update({f"{d['delivery_no']}  ·  {str(d.get('created_at') or '')[:10]}": int(d["id"]) for d in rel_del})
        with st.form("invoice_doc_form"):
            del_pick = st.selectbox("Delivery link", list(del_map.keys()), key="invoice_delivery_pick")
            notes = st.text_area("Invoice note", value="", height=64)
            if st.form_submit_button("Create invoice PDF", type="primary", use_container_width=True):
                try:
                    create_customer_invoice_document(so_id, delivery_doc_id=del_map[del_pick], notes=notes or None)
                    st.success("Customer invoice created.")
                    st.rerun()
                except Exception as e:
                    st.error(str(e)[:500])
    else:
        ent = st.radio("History view", ["Customer", "Product"], horizontal=True, key="sales_hist_entity")
        if ent == "Customer":
            pick = st.selectbox("Customer", list(clabels.keys()), key="sales_hist_customer_pick")
            hist = get_document_history("customer", int(clabels[pick]))
        else:
            plabels, _ = _product_labels()
            ppick = st.selectbox("Product", list(plabels.keys()), key="sales_hist_product_pick")
            hist = get_document_history("product", int(plabels[ppick]))
        _render_doc_table("Sales orders", hist["sales_orders"], ["doc_no", "status", "created_at"])
        _render_doc_table("Deliveries", hist["deliveries"], ["delivery_no", "delivery_receipt_number", "created_at"])
        _render_doc_table("Invoices", hist["customer_invoices"], ["invoice_no", "grand_total", "created_at"])

if dmode == "home":
    _render_section_intro(
        "Business dashboard",
        "A simple operator-first home screen for customers, vendors, orders, stock, billing, and accounting.",
        kicker="ERP overview",
        flow="Recommended daily flow: master data -> orders -> receipts / shipments -> billing -> collections / payments.",
        badges=["Customers", "Vendors", "Catalog", "Inventory", "Billing", "Accounts"],
        help_text="Use the module shortcuts below when you already know the task. Use the metrics and queues to spot what needs attention first.",
    )
    s = _cached_dashboard_stats()
    ds = get_document_dashboard_stats()
    st.markdown("##### At a glance")
    r1 = st.columns(4)
    r1[0].metric("Customers", s["n_customers"])
    r1[1].metric("Vendors", s["n_vendors"])
    r1[2].metric("Catalogue SKUs", s["n_products"])
    r1[3].metric("Purchase orders", s["n_purchase_orders"])
    r2 = st.columns(5)
    r2[0].metric("Low stock SKUs", s.get("n_sku_low_stock", 0))
    r2[1].metric("Out of stock SKUs", s.get("n_sku_out_of_stock", 0))
    r2[2].metric("Stock units (receipts)", f"{s.get('n_stock_units', 0):.1f}")
    r2[3].metric("Portal order lines", s.get("n_customer_orders", 0))
    r2[4].metric("Pipeline sales (30d) ₹", f"{s.get('pipeline_sales_30d', 0):,.0f}")
    st.markdown("##### Sales insight (order lines, pipeline statuses)")
    _do0 = date.today()
    t_end = _do0.isoformat()
    t_start: str = (_do0 - timedelta(days=6)).isoformat()
    csa, csb, csc = st.columns(3)
    with csa:
        rng = st.radio("Range", ("Today", "Last 7 days", "This month", "Custom"), key="h_sr")
    if rng == "Today":
        t_start = _do0.isoformat()
        t_end = t_start
    elif rng == "Last 7 days":
        t_start = (_do0 - timedelta(days=6)).isoformat()
        t_end = _do0.isoformat()
    elif rng == "This month":
        t_start = date(_do0.year, _do0.month, 1).isoformat()
        t_end = _do0.isoformat()
    else:
        with csb:
            a = st.date_input("From", value=_do0 - timedelta(days=30), key="h_df")
        with csc:
            b = st.date_input("To", value=_do0, key="h_dt")
        t_start = a.isoformat() if a is not None else t_start
        t_end = b.isoformat() if b is not None else t_end
    gsel = st.radio("Chart grain", ("day", "week", "month"), horizontal=True, key="h_sg")
    try:
        ser = sales_revenue_series(t_start, t_end, gsel)
    except (pg_errors.OperationalError, ValueError, TypeError) as e:
        ser = []
        st.caption(f"(Sales chart unavailable: {e})")
    if ser:
        st.bar_chart(ser, x="period", y="revenue", use_container_width=True)
    tcat = top_categories_by_revenue(t_start, t_end, 8)
    tpro = top_products_by_revenue(t_start, t_end, 8)
    k1, k2 = st.columns(2)
    with k1:
        st.caption("Top categories (₹, line value)")
        st.dataframe(tcat, use_container_width=True, hide_index=True)
    with k2:
        st.caption("Top products (₹)")
        st.dataframe(tpro, use_container_width=True, hide_index=True)
    cbf = (st.text_input("Who bought a category? (name contains)", key="h_catb") or "").strip()
    if cbf and st.button("List buyers in range", key="h_cat_btn"):
        rowsb = customers_who_bought_category(cbf, t_start, t_end)
        st.dataframe(rowsb, use_container_width=True, hide_index=True)
    st.divider()
    st.markdown("##### Purchase spend & payables (billed = AP below)")
    r3 = st.columns(5)
    r3[0].metric("PO value (commit)", f"₹{s.get('po_value_committed', 0):,.0f}")
    r3[1].metric("Purchase billed", f"₹{s.get('po_billed_raw_total', 0):,.0f}")
    r3[2].metric("AR outstanding", f"₹{s.get('ar_outstanding', 0):,.0f}")
    r3[3].metric("AP outstanding", f"₹{s.get('ap_outstanding', 0):,.0f}")
    r3[4].metric("Net (AR − AP)", f"₹{s.get('net_position', 0):,.0f}")

    st.divider()
    st.markdown("##### Document control")
    d1, d2, d3, d4, d5, d6 = st.columns(6)
    d1.metric("PO docs", ds.get("purchase_orders", 0))
    d2.metric("Goods receipts", ds.get("goods_receipts", 0))
    d3.metric("Vendor bills", ds.get("vendor_bills", 0))
    d4.metric("Sales orders", ds.get("sales_orders", 0))
    d5.metric("Customer invoices", ds.get("customer_invoices", 0))
    d6.metric("3-way disputes", ds.get("three_way_disputes", 0))

    vb_docs = list_vendor_bill_documents()
    if vb_docs:
        disputes = [
            {
                "Bill no.": x.get("bill_no"),
                "Vendor": x.get("vendor_name") or "—",
                "PO": x.get("po_doc_no") or "—",
                "Status": str(x.get("match_status") or "pending").replace("_", " ").title(),
                "Summary": (x.get("match_summary") or "Pending review")[:120],
            }
            for x in vb_docs
            if str(x.get("match_status") or "").strip().lower() in ("dispute", "variance", "pending")
        ]
        if disputes:
            st.caption("3-way match attention queue")
            st.dataframe(disputes, use_container_width=True, hide_index=True)

    stock_v2 = [r for r in list_stock_positions_v2() if r.get("reorder_recommended")]
    if stock_v2:
        st.caption("Reorder watchlist")
        st.dataframe(
            [
                {
                    "SKU": r.get("our_product_id"),
                    "Product": r.get("name"),
                    "On hand": round(float(r.get("on_hand") or 0), 3),
                    "Threshold": round(float(r.get("low_band") or 0), 3),
                    "State": str(r.get("stock_status") or "").replace("_", " ").title(),
                }
                for r in stock_v2[:20]
            ],
            use_container_width=True,
            hide_index=True,
        )

    st.divider()
    _render_dashboard_sales()

    st.divider()
    st.markdown("##### Catalogue by vendor")
    if not s["vendors"]:
        st.caption("Add a vendor under **Vendors → Directory**, then products.")
    else:
        st.dataframe(
            [
                {
                    "Vendor": v["person_name"],
                    "Company": v["company_name"],
                    "Products": v["n_products"],
                }
                for v in s["vendors"]
            ],
            use_container_width=True,
            hide_index=True,
        )

    st.divider()
    st.markdown("##### Shortcuts")
    sc1, sc2, sc3, sc4, sc5 = st.columns(5)
    with sc1:
        st.markdown("**Customer**")
        if st.button("Directory", use_container_width=True, key="sh_c_dir"):
            _go("customer")
        if st.button("Customer orders", use_container_width=True, key="sh_c_ord"):
            _go("cust_order")
        if st.button("Billing (sales)", use_container_width=True, key="sh_c_bill"):
            _go("co_billing")
    with sc2:
        st.markdown("**Product**")
        if st.button("Catalogue", use_container_width=True, key="sh_p_cat"):
            _go("product")
        if st.button("Inventory", use_container_width=True, key="sh_p_inv"):
            _go("inv")
    with sc3:
        st.markdown("**Vendor**")
        if st.button("Directory", use_container_width=True, key="sh_v_dir"):
            _go("vendor")
        if st.button("Purchase orders", use_container_width=True, key="sh_v_po"):
            _go("po_mgmt")
        if st.button("Ops queue", use_container_width=True, key="sh_v_ops"):
            _go("ops")
    with sc4:
        st.markdown("**Billing / AR / AP**")
        if st.button("Purchase billing", use_container_width=True, key="sh_v_pb"):
            _go("billing")
        if st.button("AR", use_container_width=True, key="sh_a_ar"):
            _go("ar")
        if st.button("AP", use_container_width=True, key="sh_a_ap"):
            _go("ap")
    with sc5:
        st.caption("**New PO** → **Order management** → **Vendor orders** in sidebar → **Add**.")
    st.stop()
else:
    if dmode in ("entity_dash", "customer", "vendor"):
        _render_section_intro(
            "Entities",
            "Maintain customer and vendor masters without leaving the main flow.",
            kicker="Master data",
            flow="Customer and vendor records feed orders, billing, and communication.",
            badges=["Customer master", "Vendor master"],
            help_text="Keep master records clean first. Most downstream issues in orders and billing start with incomplete entity data.",
        )
        st.radio(
            "View",
            ["Dashboard", "Customers", "Vendors"],
            key="entity_sub",
            horizontal=True,
            label_visibility="collapsed",
        )
    elif dmode in ("order_dash", "po_mgmt", "cust_order"):
        _render_section_intro(
            "Order management",
            "Run procurement and sales orders from one workspace with status-first visibility.",
            kicker="Transaction flow",
            flow="Vendor side: create PO -> receive stock -> bill vendor. Customer side: book -> confirm -> ship -> bill customer.",
            badges=["Purchase orders", "Customer orders", "Shipments"],
            help_text="Use dashboard view for queue visibility, then switch into vendor or customer orders for execution.",
        )
        st.radio(
            "View",
            ["Dashboard", "Vendor orders", "Customer orders"],
            key="order_sub",
            horizontal=True,
            label_visibility="collapsed",
        )
    elif dmode in ("co_billing", "billing"):
        _render_section_intro(
            "Billing",
            "Create and maintain purchase and sales bills while keeping AR, AP, and GL aligned.",
            kicker="Financial documents",
            flow="Billing is generated after physical movement is recorded: PO receipt first, customer shipment first.",
            badges=["Purchase bills", "Sales bills", "PDF export"],
            help_text="Bills are not auto-created here. Operators still choose the eligible PO or customer order and save the financial record deliberately.",
        )
        t_b1, t_b2 = st.columns(2)
        with t_b1:
            _bc = dmode == "co_billing"
            if st.button(
                "Customer sales (PDFs) — AR / sales",
                key="bill_tile_cust",
                use_container_width=True,
                **({"type": "primary"} if _bc else {}),
            ):
                if not _bc:
                    st.session_state.erp_bill_seg = "Customer sales (PDFs)"
                    st.session_state.dash_mode = "co_billing"
                    st.rerun()
        with t_b2:
            _bv = dmode == "billing"
            if st.button(
                "Vendor purchase — AP (PO receipts)",
                key="bill_tile_ven",
                use_container_width=True,
                **({"type": "primary"} if _bv else {}),
            ):
                if not _bv:
                    st.session_state.erp_bill_seg = "Vendor purchase"
                    st.session_state.dash_mode = "billing"
                    st.rerun()
        st.caption("Pick a tile, then use **View / Add / …** in the **Action** row below (same as other modules).")
    elif dmode == "inv":
        _render_section_intro(
            "Inventory",
            "Check stock health, receive goods, and manage substitute products without changing the stock model.",
            kicker="Stock control",
            flow="Create PO -> receive stock -> monitor on-hand -> use alternatives only when the base SKU is out of stock.",
            badges=["Stock status", "Receipts", "Alternatives"],
            help_text="Stock status is derived from receipts and open customer demand. Receipt entry remains the source of truth.",
        )
        t1, t2, t3 = st.columns(3)
        im0 = st.session_state.get("inv_main", "status")
        with t1:
            if st.button(
                "Stock status",
                use_container_width=True,
                type="primary" if im0 == "status" else "secondary",
                key="inv_tile_st",
            ):
                if im0 != "status":
                    st.session_state.inv_main = "status"
                    st.rerun()
        with t2:
            if st.button(
                "Add (receipt)",
                use_container_width=True,
                type="primary" if im0 == "receipt" else "secondary",
                key="inv_tile_add",
            ):
                if im0 != "receipt":
                    st.session_state.inv_main = "receipt"
                    st.rerun()
        with t3:
            if st.button(
                "Alternatives",
                use_container_width=True,
                type="primary" if im0 == "alternatives" else "secondary",
                key="inv_tile_alt",
            ):
                if im0 != "alternatives":
                    st.session_state.inv_main = "alternatives"
                    st.rerun()
        if im0 == "receipt":
            a1, a2 = st.columns(2)
            irm0 = st.session_state.get("inv_receipt_mode", "po")
            with a1:
                if st.button(
                    "From PO",
                    use_container_width=True,
                    type="primary" if irm0 == "po" else "secondary",
                    key="inv_sub_po",
                ):
                    st.session_state.inv_receipt_mode = "po"
                    st.rerun()
            with a2:
                if st.button(
                    "Manual",
                    use_container_width=True,
                    type="primary" if irm0 == "manual" else "secondary",
                    key="inv_sub_man",
                ):
                    st.session_state.inv_receipt_mode = "manual"
                    st.rerun()
        st.caption("**Stock status** = on-hand + filters. **Add** = receive. **Alternatives** = OOS portal substitutes.")
    elif dmode in (
        "acct_dash",
        "ar",
        "ap",
        "gl",
        "journals",
        "pnl",
        "trial",
    ):
        _render_section_intro(
            "Accounts",
            "Track open receivables, payables, journals, and reporting from the same operational data.",
            kicker="Accounting workspace",
            flow="Operational records create bills, bills drive AR / AP, and journals roll up into GL and reports.",
            badges=["AR", "AP", "GL", "P&L", "Trial balance"],
            help_text="Use AR and AP for day-to-day cash follow-up. Use journals, P&L, and trial balance for review and month-end checks.",
        )
        _acct_main_tiles(dmode)
        st.caption("Pick a tile, then work in the main area (same **Billing** pattern).")
    else:
        _render_section_intro(
            SECTION_TITLE.get(dmode, "Section"),
            "This screen keeps the existing transaction flow intact while surfacing the most common actions more clearly.",
            help_text="Start with the action bar below, then use filters and forms in the main content area.",
        )
    g = _cached_dashboard_stats()
    nvp = get_vendors_with_product_count()
    if dmode == "entity_dash":
        e1, e2, e3 = st.columns(3)
        e1.metric("Customers", g["n_customers"])
        e2.metric("Vendors", g["n_vendors"])
        e3.metric("Catalogue SKUs", g["n_products"])
        st.caption("Open **Customers** or **Vendors** above, or go to **Catalog (SKUs)** in the sidebar.")
    elif dmode == "order_dash":
        cts: dict[str, int] = {}
        for o in list_customer_orders():
            s0 = (o.status or "placed").strip()
            cts[s0] = cts.get(s0, 0) + 1
        pocs = get_po_status_counts()
        o1, o2, o3, o4, o5 = st.columns(5)
        o1.metric("Customer orders (all)", g.get("n_customer_orders", 0))
        o2.metric("PO lines (all)", g["n_purchase_orders"])
        o3.metric("PO open", pocs.get("open", 0))
        o4.metric("Booked (placed)", cts.get("placed", 0))
        o5.metric("Shipped", cts.get("shipped", 0) + cts.get("in_progress", 0))
        st.caption("Use **Vendor orders** or **Customer orders** above to work the pipeline.")
    elif dmode == "customer":
        a1, a2 = st.columns(2)
        a1.metric("Total customers", g["n_customers"])
        a2.caption("Customer phone + password are used for the **ordering** portal login.")
    elif dmode == "vendor":
        u1, u2, u3 = st.columns(3)
        u1.metric("Vendors", g["n_vendors"])
        u2.metric("Products (all vendors)", g["n_products"])
        u3.metric("Vendors with ≥1 product", nvp)
    elif dmode == "product":
        p1, p2, p3 = st.columns(3)
        p1.metric("Products in catalog", g["n_products"])
        p2.metric("Vendors", g["n_vendors"])
        p3.metric("Vendors offering products", nvp)
    elif dmode == "po":
        o1, o2, o3 = st.columns(3)
        o1.metric("Total POs", g["n_purchase_orders"])
        o2.metric("Vendors", g["n_vendors"])
        o3.metric("Products in catalog", g["n_products"])
    elif dmode == "po_mgmt":
        cts = get_po_status_counts()
        x1, x2, x3, x4, x5 = st.columns(5)
        x1.metric("Open", cts.get("open", 0))
        x2.metric("In progress", cts.get("in_progress", 0))
        x3.metric("Closed", cts.get("closed", 0))
        x4.metric("In dispute", cts.get("in_dispute", 0))
        x5.metric("All POs", g["n_purchase_orders"])
        st.caption("Change **status** and **transport** on a PO; use **View** to see line vs received.")
    elif dmode == "inv":
        u1, u2, u3, u4, u5, u6 = st.columns(6)
        u1.metric("SKUs in stock (distinct)", g.get("n_stock_sku", 0))
        u2.metric("Receipt units", f"{g.get('n_stock_units', 0):.2f}")
        u3.metric("Catalogue SKUs", g["n_products"])
        u4.metric("Open POs", get_po_status_counts().get("open", 0))
        u5.metric("Low stock SKUs", g.get("n_sku_low_stock", 0))
        u6.metric("Out of stock SKUs", g.get("n_sku_out_of_stock", 0))
    elif dmode == "cust_order":
        z1, z2, z3 = st.columns(3)
        z1.metric("Customer orders", g.get("n_customer_orders", 0))
        z2.metric("Customer bills", g.get("n_customer_order_billings", 0))
        z3.metric("Customers", g["n_customers"])
        st.caption("Flow: **booked → confirmed → shipped** (WhatsApp on confirm + ship), then **bills**.")
    elif dmode == "co_billing":
        y1, y2, y3 = st.columns(3)
        y1.metric("Sales bill records", g.get("n_customer_order_billings", 0))
        y2.metric("Portal orders", g.get("n_customer_orders", 0))
        y3.metric("Customers", g["n_customers"])
        st.caption("Customer **bill** PDFs — same single-amount logic as purchase billing.")
    elif dmode == "billing":
        b1, b2, b3 = st.columns(3)
        b1.metric("Billing records", g.get("n_po_billings", 0))
        b2.metric("Purchase orders", g["n_purchase_orders"])
        b3.metric("Vendors", g["n_vendors"])
        st.caption("**Bills:** one row per line — economic amount = qty × unit × (billing % / 100). **AR/AP** and **GL** use this.")
    elif dmode == "ar":
        t1, t2, t3, t4 = st.columns(4)
        t1.metric("Billed to customers", f"₹{g.get('co_billed_raw_total', 0):,.0f}")
        t2.metric("Collected (AR pay)", f"₹{g.get('ar_paid_total', 0):,.0f}")
        t3.metric("AR open", f"₹{g.get('ar_outstanding', 0):,.0f}")
        t4.metric("Bills (rows)", g.get("n_customer_order_billings", 0))
    elif dmode == "ap":
        t1, t2, t3, t4 = st.columns(4)
        t1.metric("Billed to us", f"₹{g.get('po_billed_raw_total', 0):,.0f}")
        t2.metric("Paid to vendors (AP pay)", f"₹{g.get('ap_paid_total', 0):,.0f}")
        t3.metric("AP open", f"₹{g.get('ap_outstanding', 0):,.0f}")
        t4.metric("Bills (rows)", g.get("n_po_billings", 0))
    elif dmode == "acct_dash":
        st.caption("Tile picks **AR, AP, GL, journals, P&L, trial**.")
    elif dmode in ("gl", "journals", "pnl", "trial"):
        st.caption("**GL** is double-entry: every journal balances (debits = credits). P&L uses revenue & expense accounts only.")
    elif dmode == "ops":
        pos_q = [p for p in list_purchase_orders() if (getattr(p, "status", None) or "open").strip() in ("open", "in_progress", "in_dispute")]
        act_co = [
            o
            for o in list_customer_orders()
            if (getattr(o, "status", None) or "").strip() in ("placed", "confirmed", "in_progress")
        ]
        agx = list_inventory_aggregated() or []
        lowct = sum(
            1
            for r in agx
            if float(r.get("on_hand") or 0) < LOW_STOCK_THRESHOLD
        )
        q1, q2, q3, q4 = st.columns(4)
        q1.metric("Active purchase lines", len(pos_q))
        q2.metric("Orders (booked / in progress)", len(act_co))
        q3.metric("SKUs under stock band", lowct)
        cts0 = get_po_status_counts()
        q4.metric("PO open (status)", cts0.get("open", 0))
        st.caption("Drill into **Order management** and **Inventory** from the left.")
    elif dmode == "ai":
        st.caption("Planned: chat, alerts, and document help over this app’s data.")
    _no_crud = dmode in (
        "ar",
        "ap",
        "gl",
        "journals",
        "pnl",
        "trial",
        "home",
        "entity_dash",
        "order_dash",
        "cust_order",
        "co_billing",
        "ops",
        "ai",
        "acct_dash",
    )
    _inv_alts = dmode == "inv" and st.session_state.get("inv_main", "status") == "alternatives"
    if not _no_crud and dmode not in _LIST_FIRST_AM and not _inv_alts:
        _action_dropdown("sec_" + dmode)
    st.divider()
    if not _no_crud and not st.session_state.get("page") and dmode not in _LIST_FIRST_AM and not _inv_alts:
        st.stop()


def _customer_labels():
    cs = list_customers()
    return {f"{c.name}  ·  {c.phone}  [id {c.id}]": c.id for c in cs}, cs


def _vendor_labels():
    vs = list_vendors()
    return {
        f"{v.person_name}  ·  {v.company_name or '—'}  ·  {v.primary_phone}  [id {v.id}]": v.id
        for v in vs
    }, vs


def _product_labels():
    prods = list_vendor_products()
    vs = list_vendors()
    vmap = {v.id: v for v in vs}
    m = {
        f"{p.our_product_id}  ·  {p.name}  ·  {vmap.get(p.vendor_id).person_name if vmap.get(p.vendor_id) else '?'}  [id {p.id}]": p.id
        for p in prods
    }
    return m, prods


def _po_labels():
    pos = list_purchase_orders()
    vmap = {v.id: v for v in list_vendors()}
    pmap = {p.id: p for p in list_vendor_products()}
    m = {}
    for o in pos:
        v = vmap.get(o.vendor_id)
        pr = pmap.get(o.product_id)
        vlabel = (v.person_name or "?") if v else "?"
        plab = f"{pr.our_product_id} / {pr.name}" if pr else f"product #{o.product_id}"
        st0 = (getattr(o, "status", None) or "open").strip()
        m[
            f"PO #{o.id}  [{st0}]  ·  {vlabel}  ·  {plab}"
        ] = o.id
    return m, pos


def _po_labels_receiving():
    """POs you can still receive against (excludes **closed**)."""
    vmap = {v.id: v for v in list_vendors()}
    pmap = {p.id: p for p in list_vendor_products()}
    pos2 = [
        o
        for o in list_purchase_orders()
        if (getattr(o, "status", None) or "open").strip() != "closed"
    ]
    m = {}
    for o in pos2:
        v = vmap.get(o.vendor_id)
        pr = pmap.get(o.product_id)
        vlabel = (v.person_name or "?") if v else "?"
        plab = f"{pr.our_product_id} / {pr.name}" if pr else f"product #{o.product_id}"
        st0 = (getattr(o, "status", None) or "open").strip()
        m[f"PO #{o.id}  [{st0}]  ·  {vlabel}  ·  {plab}"] = o.id
    return m, pos2


def _stock_receipt_labels():
    recs = list_stock_receipts()
    prods = {p.id: p for p in list_vendor_products()}
    m: dict = {}
    for r in recs:
        pr = prods.get(r.product_id)
        plab = f"{pr.our_product_id} / {pr.name}" if pr else f"p{r.product_id}"
        pox = f"PO {r.po_id}" if r.po_id is not None else "—"
        g = (r.grn_number or "—")[:32]
        m[f"R#{r.id}  {plab}  {pox}  qty {r.quantity}  {g}"] = r.id
    return m, recs


def _po_billing_labels():
    rows = list_po_billings()
    m: dict = {}
    for b in rows:
        po = get_purchase_order(b.po_id)
        v = get_vendor(b.vendor_id)
        m[
            f"B#{b.id}  PO {b.po_id}  ·  {v.person_name if v else '?'}  ·  ₹{b.raw_line_total:.2f}"
        ] = b.id
    return m, rows


def _co_order_labels():
    orders = list_customer_orders()
    cmap = {c.id: c for c in list_customers()}
    pmap = {p.id: p for p in list_vendor_products()}
    m: dict = {}
    for o in orders:
        cust = cmap.get(o.customer_id)
        pr = pmap.get(o.product_id)
        cl = cust.name if cust else "?"
        pl = f"{pr.our_product_id} / {pr.name}" if pr else f"p{o.product_id}"
        st0 = (o.status or "placed").strip()
        st_lab = CO_STATUS_OPTS.get(st0, st0)
        m[
            f"Order #{o.id}  [{st_lab}]  ·  {cl}  ·  {pl}  ·  qty {o.quantity:g}"
        ] = o.id
    return m, orders


def _eligible_co_labels_for_billing() -> dict:
    m: dict = {}
    cmap = {c.id: c for c in list_customers()}
    pmap = {p.id: p for p in list_vendor_products()}
    for oid in list_customer_order_ids_eligible_new_billing():
        o = get_customer_order(oid)
        if not o:
            continue
        cust = cmap.get(o.customer_id)
        pr = pmap.get(o.product_id)
        cl = cust.name if cust else "?"
        pl = f"{pr.our_product_id} / {pr.name}" if pr else f"p{o.product_id}"
        m[f"Order #{oid}  ·  {cl}  ·  {pl}  ·  shipped"] = oid
    return m


def _co_billing_labels():
    rows = list_customer_order_billings()
    cmap = {c.id: c for c in list_customers()}
    m: dict = {}
    for b in rows:
        c = cmap.get(b.customer_id)
        m[
            f"COB#{b.id}  Order {b.customer_order_id}  ·  {c.name if c else '?'}  ·  "
            f"₹{b.raw_line_total:.2f}"
        ] = b.id
    return m, rows


def _eligible_po_labels_for_billing() -> dict:
    m: dict = {}
    for pid in list_po_ids_eligible_new_billing():
        o = get_purchase_order(pid)
        if not o:
            continue
        v = get_vendor(o.vendor_id)
        pr = get_vendor_product(o.product_id)
        vlabel = v.person_name if v else "?"
        plab = f"{pr.our_product_id} / {pr.name}" if pr else f"p{o.product_id}"
        m[f"PO #{pid}  ·  {vlabel}  ·  {plab}  ·  received {sum_received_for_po(pid):.3f}"] = pid
    return m


def _render_billing_tabs_and_pdf(b, rid: int) -> None:
    """Previews + edit form stored on `po_billings` only (vendor master unchanged)."""
    tab_over, tab_raw, tab_edit = st.tabs(
        ["Overview", "View bill", "Edit bill & export PDF"]
    )
    sku = (b.snap_item_sku or "").strip() or "—"
    title = (b.snap_item_name or "").strip() or "—"
    vname = (b.snap_vendor_person or "").strip() or "—"
    vco = (b.snap_vendor_company or "").strip()
    vph = (b.snap_vendor_phone or "").strip()
    bp = b.billing_pct
    bp_disp = f"{bp}%" if bp is not None else "100% (default)"
    poid = b.po_id

    with tab_over:
        st.markdown("##### Record summary")
        st.write("**PO #**", poid, "· **Vendor (on bill):**", vname)
        if vco:
            st.caption(vco)
        st.caption(f"**Product:** {sku} — {title}")
        st.write(
            "**Billing %:**",
            bp_disp,
            "· **Qty × unit:**",
            f"{b.quantity} × Rs. {b.unit_cost:,.2f}",
        )
        st.metric("**Bill (economic)**", f"Rs. {b.raw_line_total:,.2f}")
        st.caption("**Vendor invoice ref:** " + ((b.vendor_invoice_raw or "—").strip() or "—"))
        st.write("**Notes:**", (b.notes or "—").strip() or "—")
        st.caption(f"Saved {b.created_at}" + (f" · updated {b.updated_at}" if b.updated_at else ""))

    with tab_raw:
        st.markdown("##### Bill (preview)")
        st.caption("Economic line amount — same as PDF.")
        st.markdown(
            f"**Vendor:** {vname}"
            + (f" · {vco}" if vco else "")
            + (f" · {vph}" if vph else "")
        )
        st.dataframe(
            [
                {
                    "Description": title,
                    "Our SKU": sku,
                    "Qty": b.quantity,
                    "Unit rate (Rs.)": round(b.unit_cost, 2),
                    "Line total (Rs.)": round(b.raw_line_total, 2),
                }
            ],
            hide_index=True,
            use_container_width=True,
        )
        st.info(f"**Document total:** Rs. {b.raw_line_total:,.2f}")

    with tab_edit:
        st.caption(
            "All fields are stored on **this billing row** only. "
            "Changing vendor master is separate (**Vendors → Modify**)."
        )
        with st.form(f"bill_edit_{rid}"):
            st.markdown("##### Vendor on bill")
            c1, c2 = st.columns(2)
            with c1:
                sv_p = st.text_input("Vendor contact name", value=b.snap_vendor_person or "")
                sv_c = st.text_input("Vendor company", value=b.snap_vendor_company or "")
            with c2:
                sv_ph = st.text_input("Vendor phone", value=b.snap_vendor_phone or "")
            st.markdown("##### Our business on bill")
            c3, c4 = st.columns(2)
            with c3:
                is_ln = st.text_input("Our legal name", value=b.snap_issuer_legal_name or "")
                is_ad = st.text_input("Our address", value=b.snap_issuer_address or "")
                is_cp = st.text_input("City / PIN", value=b.snap_issuer_city_pin or "")
            with c4:
                is_gst = st.text_input("Our reg. / ID (optional)", value=b.snap_issuer_gstin or "")
                is_ph = st.text_input("Our phone", value=b.snap_issuer_phone or "")
                is_em = st.text_input("Our email", value=b.snap_issuer_email or "")
            st.markdown("##### Line item (description on PDF)")
            c5, c6 = st.columns(2)
            with c5:
                it_sk = st.text_input("Our product ID (SKU)", value=b.snap_item_sku or "")
            with c6:
                it_nm = st.text_input("Product name", value=b.snap_item_name or "")
            st.markdown("##### Amounts")
            c7, c8 = st.columns(2)
            with c7:
                qty_in = st.number_input("Quantity", min_value=0.001, value=float(b.quantity), step=0.5, format="%.3f")
                uc_in = st.number_input("Unit price (Rs., full rate)", min_value=0.0, value=float(b.unit_cost), step=0.01, format="%.2f")
            with c8:
                bp_in = st.number_input(
                    "Billing % (of line: qty × unit; billable = line × this % / 100)",
                    min_value=0,
                    max_value=100,
                    value=int(b.billing_pct) if b.billing_pct is not None else 100,
                    step=1,
                )
            st.markdown("##### References")
            ir = st.text_input("Vendor invoice #", value=b.vendor_invoice_raw or "")
            nt = st.text_area("Notes", value=b.notes or "", height=72)
            save = st.form_submit_button("Save bill record", type="primary", use_container_width=True)
        if save:
            try:
                update_po_billing_record(
                    b.id,
                    snap_vendor_person=sv_p,
                    snap_vendor_company=sv_c or None,
                    snap_vendor_phone=sv_ph or None,
                    snap_issuer_legal_name=is_ln or None,
                    snap_issuer_address=is_ad or None,
                    snap_issuer_city_pin=is_cp or None,
                    snap_issuer_gstin=is_gst or None,
                    snap_issuer_phone=is_ph or None,
                    snap_issuer_email=is_em or None,
                    snap_item_sku=it_sk,
                    snap_item_name=it_nm,
                    quantity=float(qty_in),
                    unit_cost=float(uc_in),
                    billing_pct=int(bp_in),
                    gst_rate_pct=None,
                    vendor_invoice_raw=ir or None,
                    vendor_invoice_gst=None,
                    notes=nt,
                )
                st.success("Billing record saved. Totals recalculated.")
                st.rerun()
            except Exception as e:
                st.error(str(e)[:500])

        st.divider()
        st.markdown("##### Export PDF (from saved record)")
        bf = get_po_billing(rid)
        if bf:
            try:
                raw_pdf, _ = build_billing_pdfs_for_record(bf)
                st.download_button(
                    "Download bill (PDF)",
                    raw_pdf,
                    file_name=f"PO{poid}_bill_B{bf.id}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                    key=f"dl_raw_{rid}",
                )
                if st.button(
                    "Upload bill PDF to cloud (vendor_bills)",
                    key=f"s3_po_{rid}",
                    use_container_width=True,
                ):
                    try:
                        upload_po_billing_pdf_to_bucket(int(poid))
                        st.success(f"Uploaded vendor_bills/{int(poid)}.pdf")
                    except Exception as e:
                        st.error(str(e)[:500])
            except Exception as e:
                st.warning(f"Could not build PDF: {e}")


def _render_co_billing_tabs_and_pdf(b, rid: int) -> None:
    """Previews + edit form on `customer_order_billings` only (customer master unchanged)."""
    tab_over, tab_raw, tab_edit = st.tabs(
        ["Overview", "View bill", "Edit bill & export PDF"]
    )
    sku = (b.snap_item_sku or "").strip() or "—"
    title = (b.snap_item_name or "").strip() or "—"
    cname = (b.snap_customer_name or "").strip() or "—"
    cco = (b.snap_customer_company or "").strip()
    cph = (b.snap_customer_phone or "").strip()
    cad = (b.snap_customer_address or "").strip()
    bp = b.billing_pct
    bp_disp = f"{bp}%" if bp is not None else "100% (default)"
    coid = b.customer_order_id

    with tab_over:
        st.markdown("##### Record summary")
        st.write("**Order #**", coid, "· **Customer (on bill):**", cname)
        if cco:
            st.caption(cco)
        st.caption(f"**Product:** {sku} — {title}")
        st.write(
            "**Billing %:**",
            bp_disp,
            "· **Qty × unit:**",
            f"{b.quantity} × Rs. {b.unit_cost:,.2f}",
        )
        st.metric("**Bill (economic)**", f"Rs. {b.raw_line_total:,.2f}")
        st.caption("**Invoice ref:** " + ((b.vendor_invoice_raw or "—").strip() or "—"))
        st.write("**Notes:**", (b.notes or "—").strip() or "—")
        st.caption(f"Saved {b.created_at}" + (f" · updated {b.updated_at}" if b.updated_at else ""))

    with tab_raw:
        st.markdown("##### Bill (preview)")
        st.markdown(
            f"**Customer:** {cname}"
            + (f" · {cco}" if cco else "")
            + (f" · {cph}" if cph else "")
        )
        st.dataframe(
            [
                {
                    "Description": title,
                    "Our SKU": sku,
                    "Qty": b.quantity,
                    "Unit rate (Rs.)": round(b.unit_cost, 2),
                    "Line total (Rs.)": round(b.raw_line_total, 2),
                }
            ],
            hide_index=True,
            use_container_width=True,
        )
        st.info(f"**Document total:** Rs. {b.raw_line_total:,.2f}")

    with tab_edit:
        st.caption(
            "All fields are stored on **this billing row** only. "
            "Change the customer master under **Customers → Modify** separately."
        )
        with st.form(f"cobill_edit_{rid}"):
            st.markdown("##### Customer on bill")
            c1, c2 = st.columns(2)
            with c1:
                sc_n = st.text_input("Customer name", value=b.snap_customer_name or "")
                sc_c = st.text_input("Company", value=b.snap_customer_company or "")
            with c2:
                sc_ph = st.text_input("Phone", value=b.snap_customer_phone or "")
                sc_ad = st.text_input("Address", value=b.snap_customer_address or "")
            st.markdown("##### Our business on bill")
            c3, c4 = st.columns(2)
            with c3:
                is_ln = st.text_input("Our legal name", value=b.snap_issuer_legal_name or "")
                is_ad = st.text_input("Our address", value=b.snap_issuer_address or "")
                is_cp = st.text_input("City / PIN", value=b.snap_issuer_city_pin or "")
            with c4:
                is_gst = st.text_input("Our reg. / ID (optional)", value=b.snap_issuer_gstin or "")
                is_ph = st.text_input("Our phone", value=b.snap_issuer_phone or "")
                is_em = st.text_input("Our email", value=b.snap_issuer_email or "")
            st.markdown("##### Line item")
            c5, c6 = st.columns(2)
            with c5:
                it_sk = st.text_input("Our product ID (SKU)", value=b.snap_item_sku or "")
            with c6:
                it_nm = st.text_input("Product name", value=b.snap_item_name or "")
            st.markdown("##### Amounts")
            c7, c8 = st.columns(2)
            with c7:
                qty_in = st.number_input(
                    "Quantity", min_value=0.001, value=float(b.quantity), step=0.5, format="%.3f"
                )
                uc_in = st.number_input(
                    "Unit price (Rs., full rate)",
                    min_value=0.0,
                    value=float(b.unit_cost),
                    step=0.01,
                    format="%.2f",
                )
            with c8:
                bp_in = st.number_input(
                    "Billing % (of line: qty × unit; billable = line × this % / 100)",
                    min_value=0,
                    max_value=100,
                    value=int(b.billing_pct) if b.billing_pct is not None else 100,
                    step=1,
                )
            st.markdown("##### References")
            ir = st.text_input("Invoice #", value=b.vendor_invoice_raw or "")
            nt = st.text_area("Notes", value=b.notes or "", height=72)
            save = st.form_submit_button("Save bill record", type="primary", use_container_width=True)
        if save:
            try:
                update_customer_order_billing_record(
                    b.id,
                    snap_customer_name=sc_n,
                    snap_customer_company=sc_c or None,
                    snap_customer_phone=sc_ph or None,
                    snap_customer_address=sc_ad or None,
                    snap_issuer_legal_name=is_ln or None,
                    snap_issuer_address=is_ad or None,
                    snap_issuer_city_pin=is_cp or None,
                    snap_issuer_gstin=is_gst or None,
                    snap_issuer_phone=is_ph or None,
                    snap_issuer_email=is_em or None,
                    snap_item_sku=it_sk,
                    snap_item_name=it_nm,
                    quantity=float(qty_in),
                    unit_cost=float(uc_in),
                    billing_pct=int(bp_in),
                    gst_rate_pct=None,
                    vendor_invoice_raw=ir or None,
                    vendor_invoice_gst=None,
                    notes=nt,
                )
                st.success("Billing record saved. Totals recalculated.")
                st.rerun()
            except Exception as e:
                st.error(str(e)[:500])

        st.divider()
        st.markdown("##### Export PDF (from saved record)")
        bf = get_customer_order_billing(rid)
        if bf:
            try:
                raw_pdf, _ = build_billing_pdfs_for_co_record(bf)
                st.download_button(
                    "Download bill (PDF)",
                    raw_pdf,
                    file_name=f"CO{coid}_bill_COB{bf.id}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                    key=f"dl_co_raw_{rid}",
                )
                if st.button(
                    "Upload bill PDF to cloud (customer_bills)",
                    key=f"s3_co_{rid}",
                    use_container_width=True,
                ):
                    try:
                        upload_customer_order_billing_pdf_to_bucket(int(coid))
                        st.success(f"Uploaded customer_bills/{int(coid)}.pdf")
                    except Exception as e:
                        st.error(str(e)[:500])
            except Exception as e:
                st.warning(f"Could not build PDF: {e}")


def _opt_int(s: str) -> tuple[Optional[int], str]:
    t = (s or "").strip()
    if not t:
        return (None, "")
    try:
        n = int(t, 10)
    except ValueError:
        return (None, "Use a whole number, or leave empty")
    if n < 0:
        return (None, "Use 0 or positive, or leave empty")
    return (n, "")


def _opt_float(s: str) -> tuple[Optional[float], str]:
    t = (s or "").strip()
    if not t:
        return (None, "")
    try:
        f = float(t)
    except ValueError:
        return (None, "Use a number, or leave empty")
    if f < 0:
        return (None, "Use 0 or higher, or leave empty")
    return (f, "")


# --- ENTITIES: combined dashboard (tables) ---
if dmode == "entity_dash":
    c_rows = list_customers()
    st.subheader("All customers")
    st.dataframe(
        [
            {
                "id": c.id,
                "name": c.name,
                "company": c.company_name or "—",
                "phone": c.phone,
                "since": c.created_at,
            }
            for c in c_rows
        ],
        use_container_width=True,
        hide_index=True,
    )
    vrows = list_vendors()
    st.subheader("All vendors")
    st.dataframe(
        [
            {
                "id": v.id,
                "person": v.person_name,
                "company": v.company_name or "—",
                "primary": v.primary_phone,
                "since": v.created_at,
            }
            for v in vrows
        ],
        use_container_width=True,
        hide_index=True,
    )
    st.stop()
elif dmode == "order_dash":
    cos3 = list_customer_orders()
    cos3.sort(key=lambda x: int(x.id), reverse=True)
    cmap3 = {c.id: c for c in list_customers()}
    pmap3 = {p.id: p for p in list_vendor_products()}
    st.subheader("Latest customer order lines (up to 50)")
    st.dataframe(
        [
            {
                "Order#": o.id,
                "Customer": (cmap3.get(o.customer_id).name if cmap3.get(o.customer_id) else o.customer_id),
                "Product": (f"{pmap3.get(o.product_id).our_product_id} / {pmap3.get(o.product_id).name}" if pmap3.get(o.product_id) else o.product_id),
                "Status": CO_STATUS_OPTS.get((o.status or "placed").strip(), o.status or ""),
                "Placed": o.created_at,
            }
            for o in cos3[:50]
        ],
        use_container_width=True,
        hide_index=True,
    )
    prs2 = list_purchase_orders()
    prs2.sort(key=lambda x: int(x.id), reverse=True)
    vmap3 = {v.id: v for v in list_vendors()}
    pmap4 = {p.id: p for p in list_vendor_products()}
    st.subheader("Latest purchase order lines (up to 50)")
    st.dataframe(
        [
            {
                "PO#": p.id,
                "Status": PO_STATUS_OPTS.get((getattr(p, "status", None) or "open").strip(), ""),
                "Vendor": (vmap3.get(p.vendor_id).person_name or "—") if vmap3.get(p.vendor_id) else "—",
                "Product": (f"{pmap4.get(p.product_id).our_product_id} / {pmap4.get(p.product_id).name}" if pmap4.get(p.product_id) else p.product_id),
                "Qty": p.quantity,
                "Created": getattr(p, "created_at", "—"),
            }
            for p in prs2[:50]
        ],
        use_container_width=True,
        hide_index=True,
    )
    st.stop()
# --- CUSTOMER: list + Add / modify ---
elif dmode == "customer":
    st.subheader("Directory")
    labels, rows = _customer_labels()
    c_edit = st.session_state.entity_edit_cust

    if page == "add":
        st.caption("New B2B login uses **phone** + **password**.")
        if st.button("← Back to list", key="c_bk_a"):
            st.session_state.page = None
            st.rerun()
        with st.form("add_c"):
            name = st.text_input("Name *", "")
            company = st.text_input("Company name", "")
            phone = st.text_input("Phone *", "", help="10 digits; used for customer login")
            alt = st.text_input("Alternate phone", "")
            address = st.text_area("Address", height=100)
            pw1 = st.text_input("Password * (for customer login)", type="password")
            pw2 = st.text_input("Confirm password *", type="password")
            if st.form_submit_button("Save", type="primary", use_container_width=True):
                if not name.strip() or not phone.strip():
                    st.error("Name and phone are required")
                elif not pw1 or pw1 != pw2:
                    st.error("Passwords must match")
                else:
                    insert_customer(name, company, phone, alt, address, pw1)
                    st.success("Customer created. They can log in with this phone and password.")
                    st.session_state.page = None
                    st.rerun()
    elif page == "c_pick":
        if not labels:
            st.warning("No customers to modify.")
        else:
            st.caption("Search, then open one customer for **Save** / **Delete** on the next screen.")
            if st.button("← Back to list", key="c_bk_p2"):
                st.session_state.page = None
                st.rerun()
            cq = (st.text_input("Search to narrow (name, company, phone — contains)", key="c_fsp") or "").lower().strip()
            opts = {k: v for k, v in labels.items() if not cq or cq in k.lower()}
            if not opts:
                st.warning("No match — change search.")
            else:
                psel = st.selectbox("Select customer to edit", list(opts.keys()), key="c_psel")
                if st.button("Open for edit", type="primary", key="c_open"):
                    st.session_state.entity_edit_cust = int(opts[psel])
                    st.session_state.page = "modify"
                    st.rerun()
    elif page == "modify" and c_edit is not None:
        rid = int(c_edit)
        c = get_customer(rid)
        st.subheader(f"Edit customer  ·  id {rid}")
        if st.button("← Back to list", key="c_bk_m"):
            st.session_state.entity_edit_cust = None
            st.session_state.page = None
            st.rerun()
        if c:
            with st.form("mod_c"):
                name = st.text_input("Name *", value=c.name)
                company = st.text_input("Company name", value=c.company_name or "")
                phone = st.text_input("Phone *", value=c.phone)
                alt = st.text_input("Alternate phone", value=c.alternate_phone or "")
                address = st.text_area("Address", value=c.address or "", height=100)
                st.caption("Leave new password fields empty to keep the current password.")
                npw1 = st.text_input("New password (optional)", type="password", value="")
                npw2 = st.text_input("Confirm new password", type="password", value="")
                if st.form_submit_button("Save", type="primary", use_container_width=True):
                    if not name.strip() or not phone.strip():
                        st.error("Name and phone are required")
                    elif (npw1 or npw2) and npw1 != npw2:
                        st.error("Passwords do not match")
                    else:
                        new_pw = npw1.strip() if (npw1 and npw1 == npw2) else None
                        update_customer(c.id, name, company, phone, alt, address, new_pw)
                        st.success("Saved.")
                        st.session_state.entity_edit_cust = None
                        st.session_state.page = None
                        st.rerun()
            st.divider()
            if st.button("Delete this customer…", type="primary", key="c_to_del"):
                st.session_state.page = "c_del"
                st.rerun()
    elif page == "c_del" and c_edit is not None and get_customer(int(c_edit)) is not None:
        c = get_customer(int(c_edit))
        st.subheader("Delete customer")
        if c:
            st.write(f"**{c.name}** — {c.phone}")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Confirm delete", type="primary", key="c_del2"):
                    delete_customer(c.id)
                    st.session_state.entity_edit_cust = None
                    st.session_state.page = None
                    st.rerun()
            with c2:
                if st.button("Cancel", key="c_cdel"):
                    st.session_state.page = "modify"
                    st.rerun()
    elif page in (None, "list", ""):
        if not rows:
            st.info("No customers yet — use **Add** below (or go back to **Entities · Dashboard**).")
        else:
            c_search = (st.text_input("Search (name, company, phone — contains)", key="c_tsf2") or "").lower().strip()
            tbl: list[dict] = []
            for r0 in rows:
                blob = f"{r0.name} {r0.company_name or ''} {r0.phone} {r0.alternate_phone or ''}".lower()
                if c_search and c_search not in blob:
                    continue
                tbl.append(
                    {
                        "id": r0.id,
                        "name": r0.name,
                        "company": r0.company_name or "—",
                        "phone": r0.phone,
                    }
                )
            st.dataframe(tbl, use_container_width=True, hide_index=True)
        st.divider()
        a1, a2, a3 = st.columns([1, 1, 2])
        with a1:
            c_am = st.selectbox("Add / modify", ["—", "Add", "Modify"], key="c_amx", label_visibility="visible")
        with a2:
            st.write("")
            st.write("")
            go_c = st.button("Go", type="primary", key="c_gox", use_container_width=True)
        if go_c and c_am == "Add":
            st.session_state.page = "add"
            st.rerun()
        if go_c and c_am == "Modify":
            st.session_state.entity_edit_cust = None
            st.session_state.page = "c_pick"
            st.rerun()

# --- VENDOR: list + Add / modify ---
elif dmode == "vendor":
    st.subheader("Directory")
    labels, rows = _vendor_labels()
    v_edit = st.session_state.entity_edit_ven

    if page == "add":
        st.subheader("Add vendor")
        if st.button("← Back to list", key="v_bk_a"):
            st.session_state.page = None
            st.rerun()
        with st.form("add_v"):
            person = st.text_input("Person name *", "")
            comp = st.text_input("Company name", "")
            p1 = st.text_input("Primary contact number *", "")
            p2 = st.text_input("Secondary contact number", "")
            a1, a2 = st.columns(2)
            with a1:
                st.caption("Common: 30, 60, 90 — optional")
                ptn = st.text_input("Payment terms (days)", value="")
            with a2:
                st.caption("Common: 50, 100 — optional")
                bln = st.text_input("Billing (e.g. %)", value="")
            notes = st.text_area("Notes", height=100, help="Optional")
            st.markdown("**Your business on purchase bills (optional)** — defaults copied into **billing** rows; edit per bill later.")
            v1, v2 = st.columns(2)
            with v1:
                iln = st.text_input("Our legal name", value="", key="av_iln")
                iad = st.text_input("Our address", value="", key="av_iad")
                icp = st.text_input("City / PIN", value="", key="av_icp")
            with v2:
                igs = st.text_input("Our reg. / ID (optional)", value="", key="av_igs")
                iph = st.text_input("Our phone", value="", key="av_iph")
                iem = st.text_input("Our email", value="", key="av_iem")
            if st.form_submit_button("Save", type="primary", use_container_width=True):
                if not person.strip() or not p1.strip():
                    st.error("Person name and primary contact are required")
                else:
                    pt, e1 = _opt_int(ptn)
                    br, e2 = _opt_int(bln)
                    if e1:
                        st.error(f"Payment terms: {e1}")
                    elif e2:
                        st.error(f"Billing: {e2}")
                    else:
                        insert_vendor(
                            person,
                            comp,
                            p1,
                            p2,
                            pt,
                            br,
                            notes,
                            iln or None,
                            iad or None,
                            icp or None,
                            igs or None,
                            iph or None,
                            iem or None,
                        )
                        st.success("Vendor created.")
                        st.session_state.page = None
                        st.rerun()

    elif page == "v_pick":
        if not labels:
            st.warning("No vendors to modify.")
        else:
            st.caption("Search, then open one vendor for **Update** / **Delete** on the next screen.")
            if st.button("← Back to list", key="v_bk_p"):
                st.session_state.page = None
                st.rerun()
            vq = (st.text_input("Search to narrow (person, company, phone — contains)", key="v_fsp") or "").lower().strip()
            vopts = {k: v for k, v in labels.items() if not vq or vq in k.lower()}
            if not vopts:
                st.warning("No match — change search.")
            else:
                pselv = st.selectbox("Select vendor to edit", list(vopts.keys()), key="v_psel")
                if st.button("Open for edit", type="primary", key="v_open"):
                    st.session_state.entity_edit_ven = int(vopts[pselv])
                    st.session_state.page = "modify"
                    st.rerun()
    elif page == "modify" and v_edit is not None:
        rid = int(v_edit)
        v = get_vendor(rid)
        st.subheader(f"Edit vendor  ·  id {rid}")
        if st.button("← Back to list", key="v_bk_m"):
            st.session_state.entity_edit_ven = None
            st.session_state.page = None
            st.rerun()
        if v:
            pt0 = "" if v.payment_terms is None else str(int(v.payment_terms))
            bl0 = "" if v.billing is None else str(int(v.billing))
            with st.form("mod_v"):
                person = st.text_input("Person name *", value=v.person_name)
                comp = st.text_input("Company name", value=v.company_name or "")
                p1 = st.text_input("Primary contact *", value=v.primary_phone)
                p2 = st.text_input("Secondary contact", value=v.secondary_phone or "")
                a1, a2 = st.columns(2)
                with a1:
                    st.caption("Common: 30, 60, 90 — optional")
                    p_t2 = st.text_input("Payment terms (days)", value=pt0, key="m_pv")
                with a2:
                    st.caption("Common: 50, 100 — optional")
                    b_t2 = st.text_input("Billing (e.g. %)", value=bl0, key="m_bv")
                n2 = st.text_area("Notes", value=v.notes or "", height=100, key="m_n")
                st.markdown("**Your business on purchase bills (optional)**")
                mv1, mv2 = st.columns(2)
                with mv1:
                    miln = st.text_input("Our legal name", value=v.issuer_legal_name or "", key="mv_iln")
                    miad = st.text_input("Our address", value=v.issuer_address or "", key="mv_iad")
                    micp = st.text_input("City / PIN", value=v.issuer_city_pin or "", key="mv_icp")
                with mv2:
                    migs = st.text_input("Our reg. / ID (optional)", value=v.issuer_gstin or "", key="mv_igs")
                    miph = st.text_input("Our phone", value=v.issuer_phone or "", key="mv_iph")
                    miem = st.text_input("Our email", value=v.issuer_email or "", key="mv_iem")
                if st.form_submit_button("Save", type="primary", use_container_width=True):
                    if not person.strip() or not p1.strip():
                        st.error("Person and primary contact are required")
                    else:
                        pt, e1 = _opt_int(p_t2)
                        br, e2 = _opt_int(b_t2)
                        if e1:
                            st.error(f"Payment terms: {e1}")
                        elif e2:
                            st.error(f"Billing: {e2}")
                        else:
                            update_vendor(
                                v.id,
                                person,
                                comp,
                                p1,
                                p2,
                                pt,
                                br,
                                n2,
                                miln or None,
                                miad or None,
                                micp or None,
                                migs or None,
                                miph or None,
                                miem or None,
                            )
                            st.success("Saved.")
                            st.session_state.entity_edit_ven = None
                            st.session_state.page = None
                            st.rerun()
            st.divider()
            if st.button("Delete this vendor…", type="primary", key="v_to_del"):
                st.session_state.page = "v_del"
                st.rerun()
    elif page == "v_del" and v_edit is not None and get_vendor(int(v_edit)) is not None:
        v = get_vendor(int(v_edit))
        st.subheader("Delete vendor")
        if v:
            st.write(f"**{v.person_name}** — {v.company_name or '—'} — {v.primary_phone}")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Confirm delete", type="primary", key="v_del2"):
                    delete_vendor(v.id)
                    st.session_state.entity_edit_ven = None
                    st.session_state.page = None
                    st.rerun()
            with c2:
                if st.button("Cancel", key="v_cdel"):
                    st.session_state.page = "modify"
                    st.rerun()
    elif page in (None, "list", ""):
        if not rows:
            st.info("No vendors yet — use **Add** below (or go back to **Entities · Dashboard**).")
        else:
            v_search = (st.text_input("Search (person, company, phone — contains)", key="v_tsf2") or "").lower().strip()
            vtbl: list[dict] = []
            for r0 in rows:
                blob = f"{r0.person_name} {r0.company_name or ''} {r0.primary_phone} {r0.secondary_phone or ''}".lower()
                if v_search and v_search not in blob:
                    continue
                vtbl.append(
                    {
                        "id": r0.id,
                        "person": r0.person_name,
                        "company": r0.company_name or "—",
                        "phone": r0.primary_phone,
                    }
                )
            st.dataframe(vtbl, use_container_width=True, hide_index=True)
        st.divider()
        v1, v2, v3 = st.columns([1, 1, 2])
        with v1:
            v_am = st.selectbox("Add / modify", ["—", "Add", "Modify"], key="v_amx", label_visibility="visible")
        with v2:
            st.write("")
            st.write("")
            go_v = st.button("Go", type="primary", key="v_gox", use_container_width=True)
        if go_v and v_am == "Add":
            st.session_state.page = "add"
            st.rerun()
        if go_v and v_am == "Modify":
            st.session_state.entity_edit_ven = None
            st.session_state.page = "v_pick"
            st.rerun()

# --- PRODUCT (vendor offering) flows ---
elif dmode == "product":
    vlabels, vrows = _vendor_labels()
    plabels, prows = _product_labels()

    if page in ("view", "modify", "delete") and not plabels:
        st.warning("No products yet. Use **Add** (or add a **Vendor** first).")
        st.stop()

    rid = None
    if page in ("view", "modify", "delete"):
        pickp = st.selectbox("Select product", list(plabels.keys()), key="pick_product")
        rid = plabels.get(pickp)

    if page == "add":
        st.subheader("Add product (vendor offering)")
        if not vlabels:
            st.error("Add at least one **Vendor** before products.")
        else:
            with st.form("add_pro"):
                pv = st.selectbox("Vendor *", list(vlabels.keys()), key="addp_v")
                vpid = st.text_input("Vendor’s product id *", "")
                ouid = st.text_input("Our product id *", help="Internal SKU; must be unique in the system.")
                pname = st.text_input("Name *", "")
                pcat = st.text_input("Category (optional)", "")
                cst = st.text_input("Cost price (optional)", value="", help="Reference unit cost; used for COGS.")
                ths = st.text_input(
                    "Low-stock threshold (optional, units on hand)",
                    value="",
                    help="Alert when on-hand (after orders) is **below** this. Empty = use global default (5.0).",
                )
                imgs = st.file_uploader(
                    "Images",
                    accept_multiple_files=True,
                    type=["png", "jpg", "jpeg", "gif", "webp", "bmp"],
                )
                if st.form_submit_button("Save", type="primary", use_container_width=True):
                    vid = vlabels.get(pv)
                    if vid is None or not (vpid or "").strip() or not (ouid or "").strip() or not (pname or "").strip():
                        st.error("Vendor, both product ids, and name are required.")
                    else:
                        cpx, e_c = _opt_float(cst)
                        tpx, e_t = _opt_float(ths)
                        if e_c:
                            st.error(f"Cost: {e_c}")
                        elif e_t:
                            st.error(f"Threshold: {e_t}")
                        else:
                            try:
                                pid = insert_vendor_product(
                                    int(vid),
                                    vpid.strip(),
                                    ouid.strip(),
                                    pname.strip(),
                                    pcat,
                                    cpx,
                                    None,
                                    None,
                                    low_stock_threshold=tpx,
                                )
                                npaths = save_product_uploads_streamlit(
                                    pid, list(imgs) if imgs else []
                                )
                                if npaths:
                                    set_vendor_product_image_paths(pid, npaths)
                                st.success("Product created.")
                                st.session_state.page = None
                                st.rerun()
                            except _PG_INTEGRITY as e:
                                st.error(
                                    "Duplicate: vendor+vendor id or our id already used. "
                                    + str(e)[:200]
                                )

    elif page == "view" and rid is not None:
        p = get_vendor_product(rid)
        st.subheader("View product")
        if p:
            v = get_vendor(p.vendor_id)
            thv = getattr(p, "low_stock_threshold", None)
            oh = product_on_hand(int(rid))
            st.dataframe(
                [
                    {
                        "Our product id": p.our_product_id,
                        "Vendor name": (v.person_name if v else "—"),
                        "Qty on hand": round(float(oh), 3),
                        "Cost price": "—" if p.cost_price is None else float(p.cost_price),
                        "Low threshold": "—" if thv is None else float(thv),
                    }
                ],
                use_container_width=True,
                hide_index=True,
            )
            st.caption(
                f"**Name:** {p.name} · **Category:** {(p.category or '').strip() or '—'} · "
                f"**Vendor’s product id:** {p.vendor_product_id}"
            )
            rels = product_image_rel_paths(p.image_paths)
            st.write("**Images:**", len(rels) if rels else "—")
            if rels:
                cimg = st.columns(min(3, len(rels)))
                for i, r in enumerate(rels):
                    ap = product_image_src(r)
                    if ap:
                        cimg[i % 3].image(ap, use_container_width=True)
            st.caption(f"Uploads folder: `{get_uploads_path()}`")
            st.write("**Since:**", p.created_at)

    elif page == "modify" and rid is not None:
        p = get_vendor_product(rid)
        st.subheader("Modify product")
        if p and vlabels:
            vkeys = list(vlabels.keys())
            v_label_cur = next(
                (
                    k
                    for k, vid in vlabels.items()
                    if int(vid) == int(p.vendor_id)
                ),
                vkeys[0] if vkeys else "",
            )
            ex_paths = product_image_rel_paths(p.image_paths)
            with st.form("mod_pro"):
                pv2 = st.selectbox("Vendor *", vkeys, index=vkeys.index(v_label_cur) if v_label_cur in vkeys else 0, key="m_pv")
                vpid2 = st.text_input("Vendor’s product id *", value=p.vendor_product_id)
                ouid2 = st.text_input("Our product id *", value=p.our_product_id, key="m_ouid")
                pname2 = st.text_input("Name *", value=p.name, key="m_pnm")
                pcat2 = st.text_input("Category (optional)", value=p.category or "", key="m_pcat")
                c2st = st.text_input(
                    "Cost price (optional)", value="" if p.cost_price is None else str(p.cost_price), key="m_cst"
                )
                th2 = st.text_input(
                    "Low-stock threshold (optional, units on hand)",
                    value="" if getattr(p, "low_stock_threshold", None) is None else str(p.low_stock_threshold),
                    key="m_lth",
                )
                if ex_paths:
                    st.caption("Uncheck an image in **Keep** to remove it (file deleted on save).")
                keep = st.multiselect(
                    "Keep these images",
                    options=ex_paths,
                    default=ex_paths,
                    key="m_keepp",
                )
                add_imgs = st.file_uploader(
                    "Add more images",
                    accept_multiple_files=True,
                    type=["png", "jpg", "jpeg", "gif", "webp", "bmp"],
                    key="m_addi",
                )
                if st.form_submit_button("Update", type="primary", use_container_width=True):
                    vid2 = vlabels.get(pv2)
                    if (
                        vid2 is None
                        or not (vpid2 or "").strip()
                        or not (ouid2 or "").strip()
                        or not (pname2 or "").strip()
                    ):
                        st.error("Vendor, both product ids, and name are required.")
                    else:
                        cpx, e_c = _opt_float(c2st)
                        tpx, e_t = _opt_float(th2)
                        if e_c:
                            st.error(f"Cost: {e_c}")
                        elif e_t:
                            st.error(f"Threshold: {e_t}")
                        else:
                            keep_s = set(keep)
                            removed = [r for r in ex_paths if r not in keep_s]
                            if removed:
                                for rel in removed:
                                    delete_product_image_rel(rel)
                            kept = [r for r in ex_paths if r in keep_s]
                            try:
                                npaths = save_product_uploads_streamlit(
                                    p.id, list(add_imgs) if add_imgs else []
                                )
                            except (OSError, TypeError) as e:
                                st.error(str(e))
                            else:
                                all_paths = kept + npaths
                                try:
                                    update_vendor_product(
                                        p.id,
                                        int(vid2),
                                        vpid2.strip(),
                                        ouid2.strip(),
                                        pname2.strip(),
                                        pcat2,
                                        cpx,
                                        None,
                                        None,
                                        all_paths,
                                        low_stock_threshold=tpx,
                                    )
                                except _PG_INTEGRITY as e:
                                    st.error("Duplicate id. " + str(e)[:200])
                                else:
                                    st.success("Updated.")
                                    st.session_state.page = None
                                    st.rerun()
        elif p and not vlabels:
            st.error("No vendors found — add a vendor first.")

    elif page == "delete" and rid is not None:
        p = get_vendor_product(rid)
        st.subheader("Delete product")
        if p:
            st.write(
                f"**{p.our_product_id}** — {p.name}  ·  vendor product id: {p.vendor_product_id}"
            )
            if st.button("Confirm delete (cannot be undone)", type="primary", key="delp"):
                try:
                    delete_vendor_product(p.id)
                except ValueError as e:
                    st.error(str(e))
                else:
                    st.success("Product deleted.")
                    st.session_state.page = None
                    st.rerun()

# --- PURCHASE ORDER flows (also **PO management** shares same data) ---
elif dmode in ("po", "po_mgmt"):
    pom = dmode == "po_mgmt"
    if dmode == "po" and page is None:
        st.session_state.dash_mode = "po_mgmt"
        st.session_state.pending_erp_menu = "Order management"
        st.session_state.order_sub = "Vendor orders"
        st.session_state.page = "add"
        st.rerun()
    st.markdown(
        '<div class="erp-section-note">Purchase documents are now the primary workflow. The older line-based flow is kept below only as a fallback during transition.</div>',
        unsafe_allow_html=True,
    )
    _render_po_document_workspace()
    st.divider()
    show_po_legacy = st.toggle("Show legacy purchase line flow", value=False, key="show_po_legacy")
    if not show_po_legacy:
        st.stop()
    st.caption("Legacy purchase line flow is shown below only as a fallback.")
    vlabels, _vrows = _vendor_labels()
    polabels, porows = _po_labels()
    vmap = {v.id: v for v in list_vendors()}
    pmap = {p.id: p for p in list_vendor_products()}
    rid: Optional[int] = None
    if st.session_state.get("po_eid") is not None:
        try:
            rid = int(st.session_state.po_eid)
        except (TypeError, ValueError):
            rid = None

    if dmode == "po_mgmt" and page in (None, "list", ""):
        st.subheader("All purchase orders (lines)")
        pf = (st.text_input("Search (PO #, vendor, company, product, phone — contains)", key="po_tsf2") or "").lower().strip()
        f_stat_p = st.multiselect(
            "Status",
            list(PO_STATUS_OPTS.keys()),
            default=list(PO_STATUS_OPTS.keys()),
            format_func=lambda k: PO_STATUS_OPTS.get(k, k),
            key="po_fst2",
        )

        def _row_ok_p(o) -> bool:
            st0 = (getattr(o, "status", None) or "open").strip()
            if f_stat_p and st0 not in f_stat_p:
                return False
            if not pf:
                return True
            v = vmap.get(o.vendor_id)
            pr = pmap.get(o.product_id)
            blob = " ".join(
                [
                    str(o.id),
                    (v.person_name or "") if v else "",
                    (v.company_name or "") if v else "",
                    (v.primary_phone or "") if v else "",
                    (pr.our_product_id or "") if pr else "",
                    (pr.name or "") if pr else "",
                ]
            ).lower()
            return pf in blob

        por_f = [o for o in porows if _row_ok_p(o)]
        po_tbl: list[dict] = []
        for o in por_f:
            v = vmap.get(o.vendor_id)
            pr = pmap.get(o.product_id)
            stx = (getattr(o, "status", None) or "open").strip()
            recv = sum_received_for_po(o.id)
            po_tbl.append(
                {
                    "PO#": o.id,
                    "Status": PO_STATUS_OPTS.get(stx, stx),
                    "Vendor": (v.person_name or "—") if v else "—",
                    "Company": (v.company_name or "—") if v else "—",
                    "Phone": (v.primary_phone or "—") if v else "—",
                    "Product": f"{pr.our_product_id} / {pr.name}" if pr else f"id {o.product_id}",
                    "Ordered": float(o.quantity),
                    "Received": round(recv, 3),
                    "Left": max(0.0, float(o.quantity) - recv),
                }
            )
        if not polabels:
            st.info("No purchase orders — use **Add** below. You need at least one **vendor** and a **product** in **Catalog (SKUs)** first.")
        else:
            st.dataframe(po_tbl, use_container_width=True, hide_index=True)
        st.divider()
        pa1, pa2, pa3 = st.columns([1, 1, 2])
        with pa1:
            po_am = st.selectbox("Add / modify", ["—", "Add", "Modify"], key="po_am2")
        with pa2:
            st.write("")
            st.write("")
            go_p = st.button("Go", type="primary", key="po_gox2", use_container_width=True)
        if go_p and po_am == "Add":
            st.session_state.page = "add"
            st.session_state.po_eid = None
            st.rerun()
        if go_p and po_am == "Modify":
            st.session_state.page = "po_pick"
            st.session_state.po_eid = None
            st.rerun()
        st.stop()
    if dmode == "po_mgmt" and page == "po_pick" and not polabels:
        st.warning("No purchase orders in the system.")
        if st.button("Back to list", key="po_bk_empty"):
            st.session_state.page = None
            st.rerun()
    elif dmode == "po_mgmt" and page == "po_pick":
        st.subheader("Select a PO line to edit or delete")
        if st.button("← Back to list", key="po_bk_p"):
            st.session_state.page = None
            st.rerun()
        pfp = (st.text_input("Search (PO #, vendor, company, product, phone — contains)", key="po_tfp") or "").lower().strip()
        fopts = {k: v for k, v in polabels.items() if not pfp or pfp in k.lower()}
        if not fopts:
            st.info("No matches — try another search or clear the filter above.")
        else:
            psel1 = st.selectbox("PO line to open", list(fopts.keys()), key="po_psel1")
            if st.button("Open for edit", type="primary", key="po_op1"):
                st.session_state.po_eid = int(fopts[psel1])
                st.session_state.page = "modify"
                st.rerun()
        st.stop()
    if page == "add" and dmode in ("po", "po_mgmt"):
        st.subheader("Create purchase order")
        if st.button("← Back to list", key="po_ba"):
            st.session_state.page = None
            st.session_state.po_eid = None
            st.rerun()
        if not vlabels:
            st.error("Add a **vendor** and at least one **product** (under that vendor) first.")
        else:
            with st.form("add_po"):
                pv0 = st.selectbox("Vendor *", list(vlabels.keys()), key="pov0")
                vid0 = vlabels.get(pv0)
                prods = list_vendor_products_by_vendor(int(vid0)) if vid0 is not None else []
                pkeys = {f"{pr.our_product_id} — {pr.name}  [p{pr.id}]": pr for pr in prods}
                if not pkeys:
                    st.warning("This vendor has no products yet. Add a **Product** for them first.")
                    pr0 = None
                else:
                    pr_choice = st.selectbox(
                        "Product (from this vendor) *", list(pkeys.keys()), key="pox_p"
                    )
                    pr0 = pkeys[pr_choice]
                st.markdown("**Terms for this order** — pre-filled from vendor and product; change as needed for this PO.")
                v0 = get_vendor(int(vid0)) if vid0 is not None else None
                pt0 = st.text_input(
                    "Payment terms (days)",
                    value=""
                    if not v0 or v0.payment_terms is None
                    else str(int(v0.payment_terms)),
                )
                bl0 = st.text_input(
                    "Billing (e.g. % on invoice)",
                    value="" if not v0 or v0.billing is None else str(int(v0.billing)),
                )
                qty0 = st.number_input("Quantity", min_value=0.001, value=1.0, step=0.5, format="%.3f")
                udef = 0.0
                if pr0 and pr0.cost_price is not None:
                    udef = float(pr0.cost_price)
                uc0 = st.number_input("Unit cost", min_value=0.0, value=udef, step=0.01, format="%.2f")
                tname0 = st.text_input("Transport / courier name (optional)", value="", key="po_tn")
                tno0 = st.text_input("Tracking or vehicle number (optional)", value="", key="po_tno")
                note0 = st.text_area("Notes (optional)", height=64)
                if st.form_submit_button("Save PO", type="primary", use_container_width=True):
                    if not pr0 or not vid0 or not pkeys:
                        st.error("Select vendor and a product for that vendor.")
                    else:
                        pti, e1 = _opt_int(pt0)
                        bsi, e2 = _opt_int(bl0)
                        if e1:
                            st.error(f"Payment: {e1}")
                        elif e2:
                            st.error(f"Billing: {e2}")
                        else:
                            try:
                                insert_purchase_order(
                                    int(vid0),
                                    int(pr0.id),
                                    float(qty0),
                                    float(uc0),
                                    pti,
                                    bsi,
                                    None,
                                    None,
                                    note0,
                                    tname0 or None,
                                    tno0 or None,
                                )
                                st.success("PO created.")
                                st.session_state.page = None
                                st.session_state.po_eid = None
                                st.rerun()
                            except _PG_ALL as e:
                                st.error(str(e)[:400])

    elif page == "modify" and rid is not None:
        o = get_purchase_order(rid)
        if st.button("← Back to list", key="po_bk_mod"):
            st.session_state.page = None
            st.session_state.po_eid = None
            st.rerun()
        st.subheader("PO line" + (f"  ·  #{o.id}" if o else ""))
        if o:
            st0 = (getattr(o, "status", None) or "open").strip()
            recv = sum_received_for_po(o.id)
            v = get_vendor(o.vendor_id)
            pr = get_vendor_product(o.product_id)
            st.write("**Status:**", PO_STATUS_OPTS.get(st0, st0))
            tnparts = [
                s
                for s in [
                    (getattr(o, "transport_name", None) or "").strip() or None,
                    (getattr(o, "transport_number", None) or "").strip() or None,
                ]
                if s
            ]
            st.write("**Transport:**", "  ·  ".join(tnparts) if tnparts else "—")
            st.write("**Received vs ordered:**", f"{recv:.3f} / {float(o.quantity):.3f}")
            st.write("**Vendor:**", v.person_name if v else "—")
            st.write("**Product:**", f"{pr.our_product_id} — {pr.name}" if pr else f"id {o.product_id}")
            st.write("**Quantity / unit cost:**", f"{o.quantity:g}  ·  ₹{float(o.unit_cost):,.2f}/unit")
            st.caption("Line = qty × unit = " + f"{(o.quantity * o.unit_cost):.2f}")
            st.write("**Payment terms (days):**", "—" if o.payment_terms is None else o.payment_terms)
            st.write("**Billing %:**", "—" if o.billing is None else o.billing)
            st.caption("After goods are in, use **Billing** → **Vendor purchase** for the bill amount.")
            st.write("**Notes:**", (o.notes or "").strip() or "—")
            st.write("**Created:**", o.created_at)
            st.divider()
            leftq = max(0.0, float(o.quantity) - recv)
            stx_b = (getattr(o, "status", None) or "open").strip()
            if pr and leftq > 0.0001 and stx_b != "closed":
                with st.expander("Receive for this PO (stock receipt)", expanded=True):
                    st.caption("Also under **Product → Inventory**. Updates received qty and PO status.")
                    with st.form(f"recv_inline_{o.id}"):
                        ship_ = st.text_input("Shipment id (optional)", key=f"rsh_{o.id}")
                        grn_ = st.text_input("GRN", key=f"rgr_{o.id}")
                        qty_r = st.number_input(
                            "Quantity *",
                            min_value=0.001,
                            max_value=float(leftq),
                            value=float(min(1.0, leftq)),
                            step=0.5,
                            format="%.3f",
                            key=f"rqty_{o.id}",
                        )
                        sp_r = st.number_input(
                            "Selling price (this lot, opt.)", min_value=0.0, value=0.0, key=f"rsp_{o.id}"
                        )
                        n_r = st.text_area("Notes", height=40, key=f"rn_{o.id}")
                        if st.form_submit_button("Save stock receipt", type="primary", use_container_width=True):
                            if float(qty_r) > leftq + 0.0001:
                                st.error("Qty is more than left to receive on this line.")
                            else:
                                try:
                                    insert_stock_receipt(
                                        int(o.product_id),
                                        int(o.id),
                                        float(qty_r),
                                        ship_ or None,
                                        grn_ or None,
                                        float(sp_r) if sp_r > 0.0001 else None,
                                        n_r or None,
                                    )
                                    st.success("Received.")
                                    st.rerun()
                                except _PG_ALL as e:
                                    st.error(str(e)[:500])
            elif pr and (leftq < 0.0001 or stx_b == "closed"):
                st.caption("Line is **fully received** or **closed** — use **Inventory** to edit a receipt if needed.")
        st.subheader("Edit this line (save)")

        if o and vlabels:
            st0_cur = (getattr(o, "status", None) or "open").strip()
            _kstat = list(PO_STATUS_OPTS.keys())
            st_cur_idx = _kstat.index(st0_cur) if st0_cur in _kstat else 0
            vkey_list = list(vlabels.keys())
            v_cur = next(
                (k for k, v in vlabels.items() if int(v) == o.vendor_id), vkey_list[0] if vkey_list else None
            )
            prods_m = list_vendor_products_by_vendor(o.vendor_id) if o.vendor_id else []
            pkeys = {f"{p.our_product_id} — {p.name}  [p{p.id}]": p for p in prods_m}
            pr_cur_key = next(
                (k for k, p in pkeys.items() if p.id == o.product_id),
                (list(pkeys.keys())[0] if pkeys else None),
            )
            with st.form("mod_po"):
                st_sel = st.selectbox(
                    "Status *",
                    _kstat,
                    index=st_cur_idx,
                    format_func=lambda k: PO_STATUS_OPTS[k],
                    key="mp_st",
                )
                trname = st.text_input(
                    "Transport / courier name",
                    value=(getattr(o, "transport_name", None) or "") or "",
                    key="m_trn",
                )
                trno = st.text_input(
                    "Transport number (tracking, vehicle, …)",
                    value=(getattr(o, "transport_number", None) or "") or "",
                    key="m_tr2",
                )
                st.caption("Receipts still update **In progress** / **Closed** unless you set **In dispute** (then system leaves status alone).")
                pv1 = st.selectbox("Vendor *", vkey_list, index=vkey_list.index(v_cur) if v_cur in vkey_list else 0, key="mp_v")
                v1 = vlabels.get(pv1)
                pkeys2 = {
                    f"{p.our_product_id} — {p.name}  [p{p.id}]": p
                    for p in (list_vendor_products_by_vendor(int(v1)) if v1 else [])
                }
                pk2k = list(pkeys2.keys()) if pkeys2 else [""]
                pr1s = st.selectbox(
                    "Product *", pk2k, index=pk2k.index(pr_cur_key) if pr_cur_key in pk2k else 0, key="mp_p"
                )
                pr1 = pkeys2.get(pr1s)
                ptm = st.text_input(
                    "Payment terms (days)",
                    value="" if o.payment_terms is None else str(int(o.payment_terms)),
                )
                blm = st.text_input(
                    "Billing (e.g. % on invoice)", value="" if o.billing is None else str(int(o.billing))
                )
                qtym = st.number_input("Quantity", min_value=0.001, value=float(o.quantity), step=0.5, key="m_qt")
                ucm = st.number_input(
                    "Unit cost", min_value=0.0, value=float(o.unit_cost), step=0.01, format="%.2f", key="m_uc"
                )
                nm1 = st.text_area("Notes", value=o.notes or "", key="m_pn")
                if st.form_submit_button("Update", type="primary", use_container_width=True):
                    if v1 is None or pr1 is None:
                        st.error("Vendor and product are required.")
                    else:
                        pta, e1 = _opt_int(ptm)
                        bsa, e2 = _opt_int(blm)
                        if e1:
                            st.error(f"Payment: {e1}")
                        elif e2:
                            st.error(f"Billing: {e2}")
                        else:
                            try:
                                update_purchase_order(
                                    o.id,
                                    int(v1),
                                    int(pr1.id),
                                    float(qtym),
                                    float(ucm),
                                    pta,
                                    bsa,
                                    None,
                                    None,
                                    nm1,
                                    st_sel,
                                    trname or None,
                                    trno or None,
                                )
                                st.success("Updated.")
                                st.session_state.page = None
                                st.session_state.po_eid = None
                                st.rerun()
                            except _PG_ALL as e:
                                st.error(str(e)[:400])
            st.divider()
            if o and st.button("Delete this PO line…", type="primary", key="po_todel1"):
                st.session_state.page = "delete"
                st.rerun()
        elif o and not vlabels:
            st.error("No vendors.")
        elif not o:
            st.error("Purchase order not found (refresh the list).")

    elif page == "delete" and rid is not None:
        o = get_purchase_order(rid)
        st.subheader("Delete purchase order")
        cdb, cde = st.columns(2)
        with cdb:
            if st.button("← Back (cancel delete)", key="po_bk_del"):
                st.session_state.page = "modify"
                st.rerun()
        if o:
            prx = get_vendor_product(o.product_id)
            st.write("**PO #**", o.id, "·", (prx.our_product_id if prx else "?") + f"  qty {o.quantity}")
            with cde:
                if st.button("Confirm delete PO (cannot be undone)", type="primary", key="delpo"):
                    try:
                        delete_purchase_order(o.id)
                    except ValueError as e:
                        st.error(str(e))
                    else:
                        st.success("PO deleted.")
                        st.session_state.page = None
                        st.session_state.po_eid = None
                        st.rerun()

# --- INVENTORY: stock receipt CRUD; optional PO; GRN, shipment, sell price ---
elif dmode == "inv":
    page = st.session_state.get("page")
    im = st.session_state.get("inv_main", "status")
    plab_all, prows = _product_labels()
    polr, _porcv = _po_labels_receiving()
    srlabels, srrows = _stock_receipt_labels()
    irm0 = st.session_state.get("inv_receipt_mode", "po")
    if im == "status":
        inv_sub = "status"
    elif im == "receipt":
        inv_sub = "po" if irm0 == "po" else "manual"
    else:
        inv_sub = "status"
    if im == "alternatives":
        st.subheader("Product alternatives (portal — when base is out of stock)")
        st.caption("Pick a **base** SKU, choose **alternative** products, **Save**. In-stock subs show to customers when the base has no on-hand available.")
        if not plab_all:
            st.warning("Add **Catalog** products first.")
        else:
            vopts: list[tuple[str, Optional[int]]] = [("(any vendor)", None)]
            for v in list_vendors():
                vopts.append((v.person_name or f"id {v.id}", v.id))
            c1, c2 = st.columns(2)
            with c1:
                base_p = st.selectbox("Base product *", list(plab_all.keys()), key="palt_bpick")
            with c2:
                fven = st.selectbox(
                    "Filter alt list (vendor)",
                    vopts,
                    format_func=lambda x: x[0],
                    key="palt_fv",
                )
            bid0 = int(plab_all[base_p])
            cur = list_product_alternative_ids(bid0)
            alt_choices: list[str] = []
            for k, v in plab_all.items():
                if v == bid0:
                    continue
                if fven[1] is not None:
                    pr0 = get_vendor_product(int(v))
                    if not pr0 or int(pr0.vendor_id) != int(fven[1]):
                        continue
                alt_choices.append(k)
            dflt = [k for k in alt_choices if plab_all[k] in set(cur)]
            with st.form("form_palt"):
                msel = st.multiselect(
                    "Alternatives (same or other vendors; portal shows only in-stock alts when base is OOS)",
                    options=alt_choices,
                    default=[x for x in dflt if x in alt_choices],
                    key="palt_msel",
                )
                if st.form_submit_button("Save alternatives", type="primary", use_container_width=True):
                    try:
                        set_product_alternatives(
                            bid0, [plab_all[k] for k in msel if k in plab_all]
                        )
                    except _PG_INT_OR_VAL as e:
                        st.error(str(e)[:500])
                    else:
                        st.success("Saved.")
                        st.rerun()
    else:
        st.caption("Use the tiles: **Stock status** for tables & filters, **Add (receipt)** for **From PO / Manual**.")
        if page in ("modify", "delete") and not srlabels:
            st.warning("No stock receipts yet. Use **Add (receipt)** to receive (with or without a PO).")
            st.stop()

    rid2: Optional[int] = None
    if im != "alternatives":
        if im == "status" and page == "view":
            f_nm = (st.text_input("Filter: name / our SKU (contains)", key="inv_f_nm") or "").strip()
            f_stat = st.multiselect(
                "Stock state",
                ["in_stock", "low_stock", "out_of_stock"],
                default=["in_stock", "low_stock", "out_of_stock"],
                key="inv_f_st",
            )
            v2o = {f"{v.person_name}  [id {v.id}]": v.id for v in list_vendors()}
            vf = st.selectbox("Vendor (optional)", ["(all)"] + list(v2o.keys()), key="inv_f_vn")
            vid0 = None if vf == "(all)" else v2o.get(vf)
            sf2 = set(f_stat) if f_stat else {"in_stock", "low_stock", "out_of_stock"}
            prows2 = list_catalog_stock_rows(
                f_nm, vid0, None if len(sf2) == 3 else sf2
            )
            st.subheader("By SKU (all catalog) — on hand & health")
            st.caption("**on_hand** = received − open orders pipeline. **low_band** = product threshold (or default 5.0).")
            st.dataframe(prows2, use_container_width=True, hide_index=True)
            st.divider()
            st.subheader("Receipt-aggregated products (gross in)")
            ag = list_inventory_aggregated()
            st.dataframe(ag if ag else [], use_container_width=True, hide_index=True)
            st.divider()
            st.subheader("All stock receipt lines")
            if srrows:
                pmap = {p.id: p for p in list_vendor_products()}
                vrows2: list[dict] = []
                for r in srrows:
                    pr = pmap.get(r.product_id)
                    vrows2.append(
                        {
                            "R#": r.id,
                            "PO": r.po_id,
                            "Product": f"{pr.our_product_id} / {pr.name}" if pr else r.product_id,
                            "Qty": r.quantity,
                            "Shipment": r.shipment_id or "—",
                            "GRN": r.grn_number or "—",
                            "Sell @": r.selling_price,
                            "Notes": (r.notes or "—")[:40],
                        }
                    )
                st.dataframe(vrows2, use_container_width=True, hide_index=True)
            else:
                st.caption("No receipt lines.")
        if page in ("modify", "delete") and srlabels:
            psk = st.selectbox("Select receipt", list(srlabels.keys()), key="pick_sr")
            rid2 = srlabels.get(psk)

    if im == "receipt" and page == "add":
        st.subheader("Receive stock (receipt; PO **open → in progress → closed** from received qty)")
        if not prows:
            st.error("Add a **Product** in the catalog first.")
        else:
            if inv_sub == "po":
                mode = "From purchase order (partial shipment allowed)"
            else:
                mode = "Manual (no PO)"
            with st.form("add_sr"):
                poid0: Optional[int] = None
                pr0: Optional[object] = None
                pchoice = ""
                if mode.startswith("From"):
                    if not polr:
                        st.warning("No non-closed POs. Create a PO or use **Manual**.")
                    pickp = st.selectbox("PO *", list(polr.keys()), key="s_po", disabled=not polr) if polr else None
                    poid0 = polr.get(pickp) if pickp and polr else None
                    if poid0 is not None:
                        poo = get_purchase_order(poid0)
                        if poo:
                            pr0 = get_vendor_product(poo.product_id)
                            srecv = sum_received_for_po(poid0)
                            pnm = f"{pr0.our_product_id} / {pr0.name}" if pr0 else "?"
                            st.caption(
                                f"**Line:** {pnm}  |  **Ordered:** {poo.quantity}  |  **Received so far:** {srecv:.3f}  |  **Left ~** {max(0.0, float(poo.quantity) - srecv):.3f}"
                            )
                else:
                    pchoice = st.selectbox("Product *", list(plab_all.keys()), key="s_pr")
                    _pid = plab_all.get(pchoice)
                    if _pid is not None:
                        pr0 = get_vendor_product(int(_pid))
                ship = st.text_input("Shipment id (optional, e.g. 2nd truck)", value="")
                grn = st.text_input("GRN (goods receipt #)", value="")
                qty0 = st.number_input("Quantity received *", min_value=0.001, value=1.0, step=0.5, format="%.3f")
                sp0 = st.number_input("Selling price (optional, this lot)", min_value=0.0, value=0.0, step=0.01, format="%.2f")
                n0 = st.text_area("Notes (optional)", height=48, key="sn0")
                if st.form_submit_button("Save receipt", type="primary", use_container_width=True):
                    pida: Optional[int] = None
                    poid_s: Optional[int] = None
                    if mode.startswith("From"):
                        if not polr or not poid0:
                            st.error("Select a purchase order, or use **Manual**.")
                        else:
                            poo2 = get_purchase_order(poid0)
                            if not poo2:
                                st.error("PO not found.")
                            else:
                                pida = int(poo2.product_id)
                                poid_s = poid0
                    else:
                        pida = int(plab_all[pchoice] if pchoice in plab_all else 0) or None
                        poid_s = None
                    if pida and (mode.startswith("Manual") or poid_s is not None):
                        try:
                            insert_stock_receipt(
                                pida,
                                poid_s,
                                float(qty0),
                                ship,
                                grn,
                                float(sp0) if sp0 > 0.0001 else None,
                                n0,
                            )
                            st.success("Stock receipt saved.")
                            st.session_state.page = None
                            st.rerun()
                        except _PG_ALL as e:
                            st.error(str(e)[:500])

    elif im != "alternatives" and page == "modify" and rid2 is not None:
        o = get_stock_receipt(int(rid2))
        st.subheader("Edit stock receipt")
        if o and plab_all:
            polr2, _ = _po_labels_receiving()
            po_labels = list(plab_all.keys())
            pidx = max(0, list(plab_all.values()).index(o.product_id) if o.product_id in plab_all.values() else 0)
            po_opts: list[tuple[str, Optional[int]]] = [("—  No PO", None)]
            for _pl, _pid in polr2.items():
                po_opts.append((_pl, _pid))
            ppo_idx = 0
            for i, _t in enumerate(po_opts):
                if _t[1] == o.po_id:
                    ppo_idx = i
                    break
            with st.form("mod_sr"):
                pr1k = st.selectbox("Product *", po_labels, index=pidx, key="msr_p")
                st.caption("Link to another PO to move this line; leave **No PO** for manual stock.")
                po_lab = st.selectbox(
                    "PO (optional)", [p[0] for p in po_opts], index=ppo_idx, key="msr_po2"
                )
                new_poid: Optional[int] = next((p[1] for p in po_opts if p[0] == po_lab), None)
                shipm = st.text_input("Shipment id", value=(o.shipment_id or ""), key="msr_sh")
                grnm = st.text_input("GRN", value=(o.grn_number or ""), key="msr_g")
                qtm = st.number_input("Quantity", min_value=0.001, value=float(o.quantity), key="msr_q", format="%.3f")
                spm = st.number_input(
                    "Selling price", min_value=0.0, value=float(o.selling_price or 0.0), step=0.01, format="%.2f", key="msr_sp"
                )
                n1 = st.text_area("Notes", value=o.notes or "", key="msr_n")
                if st.form_submit_button("Update receipt", type="primary", use_container_width=True):
                    pnew = int(plab_all[pr1k])
                    try:
                        update_stock_receipt(
                            o.id,
                            pnew,
                            new_poid,
                            float(qtm),
                            shipm,
                            grnm,
                            float(spm) if spm > 0.0001 else None,
                            n1,
                        )
                        st.success("Updated.")
                        st.session_state.page = None
                        st.rerun()
                    except _PG_ALL as e:
                        st.error(str(e)[:500])
        elif o and not plab_all:
            st.error("No products.")

    elif im != "alternatives" and page == "delete" and rid2 is not None:
        o = get_stock_receipt(int(rid2))
        st.subheader("Delete stock receipt")
        if o:
            st.write("Receipt", o.id, "· product", o.product_id, "· qty", o.quantity)
            if st.button("Confirm delete (cannot be undone)", type="primary", key="delsr"):
                try:
                    delete_stock_receipt(o.id)
                except Exception as e:
                    st.error(str(e)[:400])
                else:
                    st.success("Deleted.")
                    st.session_state.page = None
                    st.rerun()

# --- BILLING MANAGEMENT (single line amount; invoice refs) ---
elif dmode == "billing":
    st.caption("Document-based vendor bills are the preferred billing record. The older purchase-bill rows remain visible for compatibility.")
    blabels, brows = _po_billing_labels()
    vb_docs = list_vendor_bill_documents()

    if page in ("view", "modify", "delete") and not blabels:
        st.warning(
            "No purchase-bill records yet. After **stock receipt** on a PO, use **Action → Add** to create the first bill "
            "(not automatic on PO close)."
        )
        if page != "add":
            st.stop()

    rid: Optional[int] = None
    if page in ("view", "modify", "delete") and blabels:
        pickb = st.selectbox("Select billing record", list(blabels.keys()), key="pick_bill")
        rid = blabels.get(pickb)

    if page == "view" and blabels and rid is not None:
        b = get_po_billing(rid)
        st.subheader("Billing — view bills & export PDF")
        if b:
            po = get_purchase_order(b.po_id)
            v = get_vendor(b.vendor_id)
            pr = get_vendor_product(po.product_id) if po else None
            if po and v:
                _render_billing_tabs_and_pdf(b, rid)
            else:
                st.error("Missing purchase order or vendor for this billing record.")

    if page == "view" and blabels:
        st.divider()
        st.subheader("All billing records")
        pmap = {p.id: p for p in list_vendor_products()}
        tbl: list[dict] = []
        for x in brows:
            po = get_purchase_order(x.po_id)
            pr = pmap.get(po.product_id) if po else None
            vn = get_vendor(x.vendor_id)
            tbl.append(
                {
                    "B#": x.id,
                    "PO": x.po_id,
                    "Vendor": vn.person_name if vn else "—",
                    "Product": f"{pr.our_product_id} / {pr.name}" if pr else "—",
                    "Billing %": x.billing_pct,
                    "Bill ₹": round(x.raw_line_total, 2),
                    "Inv ref": (x.vendor_invoice_raw or "—")[:24],
                }
            )
        st.dataframe(tbl, use_container_width=True, hide_index=True)
    if page == "view":
        st.divider()
        st.subheader("Vendor bill documents")
        if not vb_docs:
            st.caption("No document-based vendor bills yet.")
        else:
            st.dataframe(
                [
                    {
                        "Bill no.": b.get("bill_no"),
                        "Vendor": b.get("vendor_name") or "—",
                        "PO doc": b.get("po_doc_no") or "—",
                        "Grand total ₹": round(float(b.get("grand_total") or 0), 2),
                        "3-way match": str(b.get("match_status") or "pending").replace("_", " ").title(),
                        "Summary": (b.get("match_summary") or "Pending review")[:80],
                    }
                    for b in vb_docs
                ],
                use_container_width=True,
                hide_index=True,
            )

    if page == "add":
        st.subheader("Record billing for a received PO")
        elig = _eligible_po_labels_for_billing()
        if not elig:
            st.info(
                "**Bills are not auto-created when the PO is closed.** A PO shows here only after you **receive stock** "
                "(at least one receipt on that PO) and you have **not** already saved a purchase bill for it. "
                "PO status can still be *open* or *in progress*. "
                "Flow: receive on the PO (or Inventory) → **Billing** (this tile) → **Add** in the **Action** row above → pick the PO → **Save billing record**."
            )
        else:
            st.caption("**Bill amount** = qty × unit × (billing % / 100). Drives **AP** and **GL** (same numbers on **Save**).")
            with st.form("add_bill"):
                pick = st.selectbox("Purchase order *", list(elig.keys()), key="bill_new_po")
                poid = elig[pick]
                po = get_purchase_order(poid)
                q0, uc0, bp0, raw_l = 0.0, 0.0, 100, 0.0
                vraw, gst_in, n0 = "", "", ""
                if po:
                    q0 = st.number_input(
                        "Quantity *",
                        min_value=0.001,
                        value=float(po.quantity),
                        step=0.5,
                        format="%.3f",
                        key=f"abq_{poid}",
                    )
                    uc0 = st.number_input(
                        "Unit cost (₹) *",
                        min_value=0.0,
                        value=float(po.unit_cost),
                        step=0.01,
                        format="%.2f",
                        key=f"abu_{poid}",
                    )
                    _bdef = int(po.billing) if po.billing is not None else 100
                    bp0 = st.number_input(
                        "Billing % (of qty × cost line)",
                        min_value=0,
                        max_value=100,
                        value=_bdef,
                        step=1,
                        key=f"abbp_{poid}",
                    )
                    vraw = st.text_input("Vendor invoice # (optional)", value="", key=f"abv_{poid}")
                    gst_in = st.text_input("Vendor GSTIN / ref (optional)", value="", key=f"abg_{poid}")
                    n0 = st.text_area("Notes (optional)", value="", height=64, key=f"abn_{poid}")
                    raw_l, _a, _b, _c = compute_po_billing_amounts(q0, uc0, int(bp0), None)
                    st.write("**Economic line (₹):**", f"{raw_l:,.2f}")
                if st.form_submit_button("Save billing record", type="primary", use_container_width=True):
                    if not po:
                        st.error("No purchase order on file.")
                    else:
                        try:
                            insert_po_billing_for_po(
                                poid,
                                quantity=float(q0),
                                unit_cost=float(uc0),
                                billing_pct=int(bp0),
                                notes=(n0 or None),
                                vendor_invoice_raw=(vraw or None),
                                vendor_invoice_gst=(gst_in or None),
                            )
                            st.success("Saved. You can still edit the row under **Modify**.")
                            st.session_state.page = None
                            st.rerun()
                        except ValueError as e:
                            st.error(str(e))

    elif page == "modify" and rid is not None:
        b = get_po_billing(rid)
        st.subheader("Billing — same as View (edit & PDF here)")
        if b:
            po = get_purchase_order(b.po_id)
            v = get_vendor(b.vendor_id) if b.vendor_id else None
            if po and v:
                _render_billing_tabs_and_pdf(b, rid)
            elif not po:
                st.error("Purchase order missing for this billing record.")

    elif page == "delete" and rid is not None:
        b = get_po_billing(rid)
        st.subheader("Delete billing record")
        if b:
            st.write("Billing **B#", b.id, "** for **PO", b.po_id, "**")
            if st.button("Confirm delete (PO unchanged)", type="primary", key="delbill"):
                delete_po_billing(b.id)
                st.success("Deleted.")
                st.session_state.page = None
                st.rerun()

# --- SALES BILLING (customer_order_billings only) ---
elif dmode == "co_billing":
    _action_dropdown("cobill")
    st.caption("Document-based customer invoices are the preferred billing record. The older sales-bill rows remain visible for compatibility.")
    cob_labels, cob_rows = _co_billing_labels()
    inv_docs = list_customer_invoice_documents()

    if page in ("view", "modify", "delete") and not cob_labels:
        st.warning("No customer sales bills yet. Create one from **Portal orders** or **Add** here.")
        if page != "add":
            st.stop()

    rid: Optional[int] = None
    if page in ("view", "modify", "delete") and cob_labels:
        pickb = st.selectbox("Select sales bill", list(cob_labels.keys()), key="pick_cob")
        rid = cob_labels.get(pickb)

    if page == "view" and cob_labels and rid is not None:
        b = get_customer_order_billing(rid)
        st.subheader("Sales bill — view & export")
        if b:
            co = get_customer_order(b.customer_order_id)
            if co:
                _render_co_billing_tabs_and_pdf(b, rid)
            else:
                st.error("Linked customer order missing.")

    if page == "view" and cob_labels:
        st.divider()
        st.subheader("All sales bills")
        cmap = {c.id: c for c in list_customers()}
        tbl2: list[dict] = []
        for x in cob_rows:
            c0 = cmap.get(x.customer_id)
            tbl2.append(
                {
                    "COB#": x.id,
                    "Order": x.customer_order_id,
                    "Customer": c0.name if c0 else x.customer_id,
                    "Billing %": x.billing_pct,
                    "Bill ₹": round(x.raw_line_total, 2),
                    "Inv ref": (x.vendor_invoice_raw or "—")[:24],
                }
            )
        st.dataframe(tbl2, use_container_width=True, hide_index=True)
    if page == "view":
        st.divider()
        st.subheader("Customer invoice documents")
        if not inv_docs:
            st.caption("No document-based customer invoices yet.")
        else:
            st.dataframe(
                [
                    {
                        "Invoice": i.get("invoice_no"),
                        "Customer": i.get("customer_name") or "—",
                        "Sales order": i.get("sales_order_no") or "—",
                        "Taxable ₹": round(float(i.get("base_total") or 0), 2),
                        "GST ₹": round(float(i.get("gst_total") or 0), 2),
                        "Grand total ₹": round(float(i.get("grand_total") or 0), 2),
                    }
                    for i in inv_docs
                ],
                use_container_width=True,
                hide_index=True,
            )

    if page == "add":
        st.subheader("New sales bill (order must be **shipped**, no bill yet)")
        elig = _eligible_co_labels_for_billing()
        if not elig:
            st.info("Need a **shipped** portal order with **no billing row** yet.")
        else:
            st.caption("**Bill amount** = qty × price × (billing % / 100). Drives **AR** and **GL** (same on **Save**).")
            with st.form("add_cob"):
                pick = st.selectbox("Customer order *", list(elig.keys()), key="cob_add_pick")
                coid = elig[pick]
                co = get_customer_order(coid)
                q0, uc0, bp0, raw_l = 0.0, 0.0, 100, 0.0
                iraw, igs, n0 = "", "", ""
                if co:
                    q0 = st.number_input(
                        "Quantity *",
                        min_value=0.001,
                        value=float(co.quantity),
                        step=0.5,
                        format="%.3f",
                        key=f"cbq_{coid}",
                    )
                    uc0 = st.number_input(
                        "Unit price (₹) *",
                        min_value=0.0,
                        value=float(co.unit_price),
                        step=0.01,
                        format="%.2f",
                        key=f"cbu_{coid}",
                    )
                    _cbdef = int(co.billing_pct) if co.billing_pct is not None else 100
                    bp0 = st.number_input(
                        "Billing % (of line)",
                        min_value=0,
                        max_value=100,
                        value=_cbdef,
                        step=1,
                        key=f"cbbp_{coid}",
                    )
                    iraw = st.text_input("Your invoice / ref (optional)", value="", key=f"cbi_{coid}")
                    igs = st.text_input("Customer GSTIN / ref (optional)", value="", key=f"cbg_{coid}")
                    n0 = st.text_area("Notes (optional)", value="", height=64, key=f"cbn_{coid}")
                    raw_l, _a, _b, _c = compute_po_billing_amounts(
                        q0, uc0, int(bp0), None
                    )
                    st.write("**Economic line (₹):**", f"{raw_l:,.2f}")
                if st.form_submit_button("Save sales bill", type="primary", use_container_width=True):
                    if not co:
                        st.error("No customer order on file.")
                    else:
                        try:
                            insert_customer_order_billing(
                                coid,
                                quantity=float(q0),
                                unit_cost=float(uc0),
                                billing_pct=int(bp0),
                                notes=(n0 or None),
                                vendor_invoice_raw=(iraw or None),
                                vendor_invoice_gst=(igs or None),
                            )
                            st.success("Saved. **View** / **Modify** for full PDF + snapshot fields.")
                            st.session_state.page = None
                            st.rerun()
                        except ValueError as e:
                            st.error(str(e))

    elif page == "modify" and rid is not None:
        b = get_customer_order_billing(rid)
        st.subheader("Sales bill — edit & PDF")
        if b:
            co = get_customer_order(b.customer_order_id)
            if co:
                _render_co_billing_tabs_and_pdf(b, rid)
            else:
                st.error("Customer order missing.")

    elif page == "delete" and rid is not None:
        b = get_customer_order_billing(rid)
        st.subheader("Delete sales bill")
        if b:
            st.write("COB **#", b.id, "** for **order", b.customer_order_id, "**")
            if st.button("Confirm delete (order unchanged)", type="primary", key="delcob"):
                delete_customer_order_billing(b.id)
                st.success("Deleted.")
                st.session_state.page = None
                st.rerun()

# --- CUSTOMER ORDERS (portal + manual, shipments, one notes field) ---
elif dmode == "cust_order":
    st.caption("Summary counts are on **Order management → Dashboard**.")
    st.markdown(
        '<div class="erp-section-note">Same database everywhere — sales documents vs order lines are different panels only.</div>',
        unsafe_allow_html=True,
    )
    _render_sales_document_workspace()
    st.divider()
    st.subheader("Customer order lines")
    st.caption(
        "Customer portal and manual adds use **`customer_orders`**. Filter and open a line to change status, ship, or bill."
    )
    plabels, _pall = _product_labels()
    all_rows = list_customer_orders()
    colabels, corows = _co_order_labels()
    cmap = {c.id: c for c in list_customers()}
    pmap = {p.id: p for p in list_vendor_products()}
    rid: Optional[int] = None
    if st.session_state.get("co_eid") is not None:
        try:
            rid = int(st.session_state.co_eid)
        except (TypeError, ValueError):
            rid = None

    if page in (None, "list", ""):
        f_name = (st.text_input("Filter: customer name contains", key="co_fn") or "").strip()
        f_stat = st.multiselect(
            "Filter: status",
            list(CO_STATUS_OPTS.keys()),
            default=list(CO_STATUS_OPTS.keys()),
            format_func=lambda k: CO_STATUS_OPTS.get(k, k),
            key="co_fstat",
        )

        def _co_filt(o: object) -> bool:
            c0 = cmap.get(o.customer_id)
            nm = (c0.name or "").lower() if c0 else ""
            if f_name and f_name.lower() not in nm:
                return False
            xs = (o.status or "placed").strip()
            return xs in f_stat

        frows = [o for o in all_rows if _co_filt(o)]
        st.caption("Filtered list" if f_name or len(f_stat) < len(CO_STATUS_OPTS) else "All orders in this table")
        if frows:
            trows: list[dict] = []
            for x in frows:
                c0 = cmap.get(x.customer_id)
                pr = pmap.get(x.product_id)
                xs = (x.status or "placed").strip()
                trows.append(
                    {
                        "#": x.id,
                        "Customer": c0.name if c0 else x.customer_id,
                        "Product": f"{pr.our_product_id} / {pr.name}" if pr else x.product_id,
                        "Qty": x.quantity,
                        "₹ unit": round(x.unit_price, 2),
                        "Status": CO_STATUS_OPTS.get(xs, xs),
                        "Notes": (x.notes or "—")[:64],
                        "Bill": "yes" if get_customer_order_billing_by_order_id(x.id) else "—",
                    }
                )
            st.dataframe(trows, use_container_width=True, hide_index=True)
        else:
            st.caption("No rows match the filter. Clear filters to see all.")
        st.divider()
        cox1, cox2, cox3 = st.columns([1, 1, 2])
        with cox1:
            co_s = st.selectbox("Add / modify", ["—", "Add", "Modify"], key="co_smode")
        with cox2:
            st.write("")
            st.write("")
            go_o = st.button("Go", type="primary", key="co_sgo", use_container_width=True)
        if go_o and co_s == "Add":
            st.session_state.page = "add"
            st.session_state.co_eid = None
            st.rerun()
        if go_o and co_s == "Modify":
            st.session_state.co_eid = None
            st.session_state.page = "co_pick"
            st.rerun()
        st.stop()
    if page == "co_pick" and not colabels:
        st.warning("No customer orders in the system. Place via **portal** or use **Add** (manual).")
    elif page == "co_pick":
        if st.button("← Back to list", key="co_bk_p"):
            st.session_state.page = None
            st.rerun()
        cqs = (st.text_input("Search to narrow (order #, product, name — in label text)", key="co_qs") or "").lower().strip()
        copt = {k: v for k, v in colabels.items() if not cqs or cqs in k.lower()}
        if not copt:
            st.info("No match — try another search.")
        else:
            cps = st.selectbox("Select an order line to work on", list(copt.keys()), key="co_selp")
            if st.button("Open (edit / status / ship)", type="primary", key="co_op1"):
                st.session_state.co_eid = int(copt[cps])
                st.session_state.page = "modify"
                st.rerun()
        st.stop()
    if page in ("modify", "delete") and not colabels and page != "add":
        st.warning("No customer orders to change.")
        st.stop()

    if page == "add":
        st.subheader("Add order manually (on behalf of customer)")
        if st.button("← Back to list", key="co_ba"):
            st.session_state.page = None
            st.session_state.co_eid = None
            st.rerun()
        c_lab, _crows = _customer_labels()
        if not plabels or not c_lab:
            st.error("Need at least one **customer** and one **product** (Catalog).")
        else:
            with st.form("co_add_manual"):
                csel = st.selectbox("Customer *", list(c_lab.keys()), key="mco_c")
                psel = st.selectbox("Product *", list(plabels.keys()), key="mco_p")
                qty = st.number_input("Quantity *", min_value=0.001, value=1.0, key="mco_q")
                up0 = st.number_input("Unit price (₹) *", min_value=0.01, value=1.0, step=0.5, key="mco_pu")
                nt0 = st.text_area("Notes (shared with customer & in WhatsApp)", key="mco_n")
                if st.form_submit_button("Create order", type="primary", use_container_width=True):
                    cid = c_lab.get(csel)
                    pid = plabels.get(psel)
                    if not cid or not pid:
                        st.error("Select customer and product")
                    else:
                        try:
                            insert_customer_order(
                                int(cid),
                                int(pid),
                                float(qty),
                                unit_price=float(up0),
                                notes=nt0 or None,
                            )
                            st.success("Order created. Customer gets an **order placed** WhatsApp if config is on.")
                            st.session_state.page = None
                            st.session_state.co_eid = None
                            st.rerun()
                        except Exception as e:
                            st.error(str(e)[:500])
    elif page == "modify" and rid is not None:
        o = get_customer_order(rid)
        if st.button("← Back to list", key="co_bk_m"):
            st.session_state.page = None
            st.session_state.co_eid = None
            st.rerun()
        st.subheader("Order line")
        if o:
            cust = get_customer(o.customer_id)
            pr = get_vendor_product(o.product_id)
            s0 = (o.status or "placed").strip()
            st.write("**Customer:**", cust.name if cust else o.customer_id, "· **Status:**", CO_STATUS_OPTS.get(s0, o.status))
            st.write("**Product:**", f"{pr.our_product_id} / {pr.name}" if pr else o.product_id)
            st.write("**Ordered qty · unit ₹:**", f"{o.quantity:g} · {o.unit_price:,.2f}")
            st.write("**Notes (customer & WA):**", (o.notes or "—").strip() or "—")
            left0 = max(0.0, float(o.quantity) - sum_customer_order_shipment_qty(o.id))
            st.caption("**Remaining qty to ship:** " + f"{left0:.3f}")
            ships = list_customer_order_shipments(o.id)
            if ships:
                for s in ships:
                    st.write(
                        f"  · {s.created_at} — **qty** {s.quantity:g} @ ₹{s.unit_price:,.2f} — "
                        f"receipt {s.delivery_receipt_number or '—'} — **contact** {s.delivery_contact or '—'}"
                    )
        st.subheader("Update order")
        if o:
            cust = get_customer(o.customer_id)
            pr = get_vendor_product(o.product_id)
            st.caption(f"**Line #{o.id}**  ·  {cust.name if cust else ''} — {pr.our_product_id if pr else ''} / {pr.name if pr else ''}")
            s0 = (o.status or "placed").strip()
            idx2 = list(CO_STATUS_OPTS.keys()).index(s0) if s0 in CO_STATUS_OPTS else 0
            with st.form(f"co_up_{rid}"):
                st_sel = st.selectbox("Status", list(CO_STATUS_OPTS.keys()), index=idx2, format_func=lambda k: CO_STATUS_OPTS.get(k, k))
                nt = st.text_area("Notes (portal + all WhatsApp for this line)", value=o.notes or "", key=f"co_n_{rid}")
                ship_rcpt = st.text_input(
                    "Receipt number (for shipped update)",
                    value=o.delivery_receipt_number or "",
                    key=f"co_ship_receipt_{rid}",
                    help="Sent to customer when status is set to Shipped.",
                )
                ship_contact = st.text_input(
                    "Carrier / transport phone",
                    value=o.delivery_contact or "",
                    key=f"co_ship_contact_{rid}",
                    help="Sent to customer when status is set to Shipped.",
                )
                ship_note = st.text_area(
                    "Shipment note",
                    value=o.delivery_notes or "",
                    key=f"co_ship_note_{rid}",
                    height=60,
                )
                if st.form_submit_button("Save status & notes", type="primary", use_container_width=True):
                    try:
                        update_customer_order(
                            o.id,
                            status=st_sel,
                            notes=nt or None,
                            shipment_id="",
                            transport_name="",
                            transport_number="",
                            delivery_receipt_number=ship_rcpt or None,
                            delivery_contact=ship_contact or None,
                            delivery_notes=ship_note or None,
                        )
                        st.success("Saved. Status updates can notify the customer with the delivery details.")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e)[:500])
            left1 = max(0.0, float(o.quantity) - sum_customer_order_shipment_qty(o.id))
            st.divider()
            st.markdown("**Ship in parts (each part sends a delivery WhatsApp)**")
            st.caption(f"Remaining unshipped qty: **{left1:.3f}** (sum of shipments may not exceed order line qty).")
            # Streamlit requires min <= value <= max; remaining can be < 0.001 or exactly 0.
            _rem = float(left1)
            if _rem > 0:
                _min_q = min(0.001, _rem)
                _max_q = max(_min_q, _rem)
                _def_q = min(1.0, _max_q)
            else:
                _min_q = 0.001
                _max_q = 0.001
                _def_q = 0.001
            _step_q = 0.001 if _max_q >= 0.001 else max(_max_q / 10.0, 1e-9)
            with st.form(f"co_sh_{rid}"):
                qsh = st.number_input(
                    "This shipment quantity *",
                    min_value=_min_q,
                    max_value=_max_q,
                    value=_def_q,
                    step=_step_q,
                    format="%.6f",
                    key=f"qsh_{rid}",
                )
                ush = st.number_input("Unit price for this shipment (₹) *", min_value=0.0, value=float(o.unit_price), step=0.5, key=f"ush_{rid}")
                rnum = st.text_input("Receipt #", key=f"rn_{rid}")
                cnum = st.text_input("Contact #", key=f"cn_{rid}")
                fup = st.file_uploader("Receipt image (optional, header in WA)", type=["png", "jpg", "jpeg", "webp"], key=f"up_{rid}")
                if st.form_submit_button("Record shipment & notify", type="primary", use_container_width=True):
                    if left1 < 0.0001:
                        st.error("Nothing left to ship on this line (or check qty).")
                    else:
                        try:
                            bts: Optional[bytes] = fup.getvalue() if fup is not None else None
                            insert_customer_order_shipment(
                                int(rid),
                                float(qsh),
                                float(ush),
                                rnum or None,
                                cnum or None,
                                bts,
                                (fup.name or "r.jpg") if fup is not None else "r.jpg",
                            )
                            st.success("Shipment saved. Delivery message sent to customer (if not disabled).")
                            st.rerun()
                        except Exception as e:
                            st.error(str(e)[:500])
            for s in list_customer_order_shipments(int(rid)):
                pimg = (s.receipt_image_path or "").strip()
                if pimg:
                    pabs2 = os.path.join(get_uploads_path(), pimg.replace("/", os.sep))
                    if os.path.isfile(pabs2):
                        st.image(pabs2, width=320, caption=f"Shipment #{s.id} receipt")
            bill = get_customer_order_billing_by_order_id(int(rid))
            if bill:
                st.divider()
                _render_co_billing_tabs_and_pdf(bill, bill.id)
                if (o.status or "").strip().lower() == "delivered":
                    st.markdown("##### Payment reminder (WhatsApp)")
                    ts = getattr(bill, "payment_reminder_wa_sent_at", None)
                    if ts:
                        st.caption(f"Last sent: **{ts}**")
                    if st.button(
                        "Send payment reminder to customer",
                        key=f"cob_paywa_{rid}",
                        type="primary",
                    ):
                        try:
                            r = send_customer_order_payment_reminder_wa(int(bill.id))
                            if r.get("ok"):
                                st.success("Payment reminder sent.")
                                st.rerun()
                            else:
                                st.error(str(r.get("error") or r)[:700])
                        except Exception as e:
                            st.error(str(e)[:500])
            elif (o.status or "").strip().lower() in ("shipped", "delivered") and not bill:
                st.divider()
                if st.button("Create sales bill record", key=f"mkcob_{rid}"):
                    try:
                        insert_customer_order_billing(int(rid))
                        st.success("Billing created.")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e)[:400])
            st.divider()
            if o and st.button("Delete this order line…", type="primary", key="co_todel1"):
                st.session_state.page = "delete"
                st.rerun()
    elif page == "delete" and rid is not None:
        o = get_customer_order(rid)
        st.subheader("Delete customer order")
        if st.button("← Back to list (cancel delete)", key="co_bk_d"):
            st.session_state.co_eid = None
            st.session_state.page = None
            st.rerun()
        if o:
            st.write("Order **#**", o.id, "— also removes bills/shipments depending on DB rules")
            if st.button("Confirm delete", type="primary", key="delco"):
                delete_customer_order(o.id)
                st.success("Deleted.")
                st.session_state.co_eid = None
                st.session_state.page = None
                st.rerun()
# --- OPERATIONS: cross-module queue (no direct writes here) ---
elif dmode == "ops":
    st.subheader("What needs attention")
    cts2 = get_po_status_counts()
    vmap2 = {v.id: v for v in list_vendors()}
    pmap2 = {p.id: p for p in list_vendor_products()}
    pos2 = [p for p in list_purchase_orders() if (getattr(p, "status", None) or "open").strip() in ("open", "in_progress", "in_dispute")]
    po_rows2 = []
    for o in pos2:
        v2 = vmap2.get(o.vendor_id)
        pr2 = pmap2.get(o.product_id)
        stx2 = (getattr(o, "status", None) or "open").strip()
        recv2 = sum_received_for_po(o.id)
        left2 = max(0.0, float(o.quantity) - recv2)
        po_rows2.append(
            {
                "PO#": o.id,
                "Status": PO_STATUS_OPTS.get(stx2, stx2),
                "Vendor": (v2.person_name or "—") if v2 else "—",
                "Product": f"{pr2.our_product_id} / {pr2.name}" if pr2 else f"id {o.product_id}",
                "Left to receive": round(left2, 3),
            }
        )
    with st.expander("Purchase — open & receiving", expanded=True):
        if not po_rows2:
            st.info("No purchase lines in **open** / **in progress** / **in dispute**.")
        else:
            st.dataframe(po_rows2, use_container_width=True, hide_index=True)
        st.caption(f"By status: open {cts2.get('open', 0)}  ·  in progress {cts2.get('in_progress', 0)}  ·  dispute {cts2.get('in_dispute', 0)}  ·  closed {cts2.get('closed', 0)}")
        cpo1, cpo2 = st.columns(2)
        with cpo1:
            if st.button("Open **Purchase orders** (full)", key="op_to_po", use_container_width=True):
                _go("po_mgmt")
        with cpo2:
            if st.button("**New PO**", key="op_new_po", use_container_width=True):
                st.session_state.dash_mode = "po_mgmt"
                st.session_state.pending_erp_menu = "Order management"
                st.session_state.order_sub = "Vendor orders"
                st.session_state.page = "add"
                st.rerun()

    cos2 = list_customer_orders()
    cmap2 = {c.id: c for c in list_customers()}
    co_rows2: list[dict] = []
    for o2 in cos2:
        s2 = (getattr(o2, "status", None) or "").strip()
        if s2 in ("shipped",):
            continue
        c2o = cmap2.get(int(o2.customer_id))
        co_rows2.append(
            {
                "Order#": o2.id,
                "Status": CO_STATUS_OPTS.get(s2, s2 or "—"),
                "Customer": c2o.name if c2o else f"id {o2.customer_id}",
                "Placed": getattr(o2, "created_at", "—"),
            }
        )
    with st.expander("Sales — not fully shipped (pipeline)", expanded=True):
        if not co_rows2:
            st.info("No open customer order rows (or all marked **shipped**).")
        else:
            st.dataframe(co_rows2, use_container_width=True, hide_index=True)
        if st.button("Open **Customer orders** (full)", key="op_to_co", use_container_width=True):
            _go("cust_order")

    ag3 = list_inventory_aggregated() or []
    lowrows = [
        {
            "our_product_id": r.get("our_product_id", ""),
            "name": r.get("name", ""),
            "on_hand": round(float(r.get("on_hand") or 0), 3),
        }
        for r in ag3
        if float(r.get("on_hand") or 0) < LOW_STOCK_THRESHOLD
    ]
    with st.expander("Stock — under threshold (same as Inventory alert band)", expanded=False):
        if not lowrows:
            st.info(f"No rows below **{LOW_STOCK_THRESHOLD:.0f}** units (aggregated on hand).")
        else:
            st.dataframe(lowrows, use_container_width=True, hide_index=True)
        st.caption(f"Full stock view: **Inventory** (sidebar).")
        if st.button("Open **Inventory**", key="op_to_inv", use_container_width=True):
            _go("inv")

elif dmode == "ai":
    st.subheader("Assistant (placeholder)")
    st.text_area("Prompt / question", placeholder="E.g. Summarise low-stock SKUs…", key="ai_stub", height=120, disabled=True)
    st.caption("Wire your LLM + tools here. Read-only on DB first.")
# --- ACCOUNTING: AR / AP (linked to customer_order_billings / po_billings) ---
elif dmode == "acct_dash":
    st.markdown(
        """
**How this hangs together**

| Piece | What it is |
|------|-------------|
| **GL accounts** | Chart of accounts (balance sheet + P&L buckets). |
| **Journals** | Every accounting posting (bill, payment, COGS) becomes a balanced journal (Dr = Cr). |
| **P&L** | Revenue minus expenses **through the date you pick** (uses income/expense GL accounts). |
| **Trial balance** | All accounts with net Dr−Cr — sanity check that books tie out. |
| **AR** | Money **customers owe you** after you raised a **customer bill** (portal billing row or doc invoice). |
| **AP** | Money **you owe vendors** after a **purchase bill** (legacy PO bill or vendor bill doc). |

**Cash collection (clear AR):** sidebar **Accounts** → tile **AR (receivable)** → tab **Record collection** → choose the open bill → amount → **Record collection**.

**Vendor payment (clear AP):** **Accounts** → **AP (payable)** → **Record payment (vendor)** → pick bill → **Record vendor payment**.

Same database as orders and billing; nothing extra to sync.
        """
    )
elif dmode == "ar":
    st.info(
        "**Record customer payment:** open tab **Record collection** below → pick bill → enter amount (≤ open balance) → submit."
    )
    tab1, tab2, tab3 = st.tabs(["Open by bill", "Record collection", "Payment log"])
    with tab1:
        ar = ar_ledger_rows()
        if not ar:
            st.info("No **customer sales** bills. Create in **Customer → Billing** (after portal order is shipped).")
        else:
            st.dataframe(ar, use_container_width=True, hide_index=True)
    with tab2:
        cobs = list_customer_order_billings()
        invs = list_customer_invoice_documents()
        opts: dict[str, tuple[str, int]] = {}
        for c in cobs:
            bal = get_ar_open_balance(c.id)
            if bal > 0.005:
                cust = c.snap_customer_name or "—"
                opts[
                    f"COB {c.id}  ·  {cust}  ·  order {c.customer_order_id}  ·  open ₹{bal:,.2f}"
                ] = ("legacy", c.id)
        for i in invs:
            bal = get_ar_open_balance(customer_invoice_id=int(i["id"]))
            if bal > 0.005:
                opts[
                    f"INV {i['invoice_no']}  ·  {i.get('customer_name') or '—'}  ·  SO {i.get('sales_order_no') or i.get('sales_order_id')}  ·  open ₹{bal:,.2f}"
                ] = ("invoice", int(i["id"]))
        if not opts:
            st.caption("Nothing to collect, or all bills are paid in full.")
        else:
            with st.form("pay_ar_one"):
                pick = st.selectbox("Bill to collect (billed amount)", list(opts.keys()), key="ar_bill_pk")
                amt0 = st.number_input("Amount *", min_value=0.01, value=100.0, step=10.0, format="%.2f")
                meth = st.text_input("Method (UPI / bank / cash)", value="")
                nte = st.text_input("Reference / note", value="")
                if st.form_submit_button("Record collection", type="primary", use_container_width=True):
                    target = opts.get(pick)
                    if not target:
                        st.error("Pick a bill")
                    else:
                        doc_type, doc_id = target
                        bal2 = get_ar_open_balance(customer_invoice_id=doc_id) if doc_type == "invoice" else get_ar_open_balance(doc_id)
                        a = float(amt0)
                        if a > bal2 + 0.01:
                            st.error(f"Amount is over open balance (₹{bal2:,.2f}).")
                        else:
                            try:
                                if doc_type == "invoice":
                                    insert_ar_payment(None, a, meth or None, nte or None, customer_invoice_id=doc_id)
                                else:
                                    insert_ar_payment(doc_id, a, meth or None, nte or None)
                                st.success("Recorded.")
                                st.rerun()
                            except (ValueError, pg_errors.OperationalError) as e:
                                st.error(str(e)[:500])
    with tab3:
        plog = list_ar_payments_log()
        if not plog:
            st.caption("No **AR** payment rows yet.")
        else:
            dfp = []
            for p in plog:
                dfp.append(
                    {
                        "P#": p.get("id"),
                        "Type": p.get("doc_type") or "—",
                        "When": p.get("paid_at"),
                        "Ref": p.get("customer_invoice_id") or p.get("co_billing_id"),
                        "₹": round(float(p.get("amount") or 0), 2),
                        "Method": p.get("method") or "—",
                        "Order": p.get("customer_order_id"),
                        "Customer": (p.get("snap_customer_name") or "—")[:32],
                    }
                )
            st.dataframe(dfp, use_container_width=True, hide_index=True)
        st.subheader("Reverse a payment (typo / duplicate)")
        dkeys = {f"#{p['id']}  ₹{float(p['amount']):,.2f}  {p.get('paid_at', '')}": p["id"] for p in plog}
        pdk = st.selectbox("Select payment to **delete**", ["—"] + list(dkeys.keys()) if dkeys else ["—"], key="ar_del2")
        if pdk and pdk != "—" and dkeys and st.button("Delete AR payment row", type="primary", key="ar_del_b"):
            try:
                delete_ar_payment(dkeys[pdk])
                st.success("Deleted.")
                st.rerun()
            except (ValueError, Exception) as e:
                st.error(str(e)[:400])

elif dmode == "ap":
    st.info(
        "**Pay a vendor / clear AP:** tab **Record payment (vendor)** → choose open bill → amount → **Record vendor payment**."
    )
    tab1, tab2, tab3 = st.tabs(["Open by bill", "Record payment (vendor)", "Payment log"])
    with tab1:
        ap = ap_ledger_rows()
        if not ap:
            st.info("No **purchase** bills. Create in **Billing** → **Vendor purchase** (after you receive on a PO).")
        else:
            st.dataframe(ap, use_container_width=True, hide_index=True)
    with tab2:
        pbs = list_po_billings()
        vbs = list_vendor_bill_documents()
        opts2: dict[str, tuple[str, int]] = {}
        for b in pbs:
            balf = get_ap_open_balance(b.id)
            if balf > 0.005:
                v = get_vendor(b.vendor_id)
                vn = v.person_name if v else "—"
                opts2[f"B {b.id}  ·  PO {b.po_id}  ·  {vn}  ·  open ₹{balf:,.2f}"] = ("legacy", b.id)
        for b in vbs:
            balf = get_ap_open_balance(vendor_bill_doc_id=int(b["id"]))
            if balf > 0.005:
                opts2[f"VB {b['bill_no']}  ·  PO {b.get('po_doc_no') or b.get('po_doc_id')}  ·  {b.get('vendor_name') or '—'}  ·  open ₹{balf:,.2f}"] = ("vendor_bill", int(b["id"]))
        if not opts2:
            st.caption("Nothing to pay, or all purchase bills are paid in full.")
        else:
            with st.form("pay_ap_one"):
                pick2 = st.selectbox("Bill to pay (billed amount)", list(opts2.keys()), key="ap_bill_pk")
                amt1 = st.number_input("Amount *", min_value=0.01, value=100.0, step=10.0, format="%.2f", key="am_ap")
                meth2 = st.text_input("Method", value="")
                n2 = st.text_input("UTR / ref", value="")
                if st.form_submit_button("Record vendor payment", type="primary", use_container_width=True):
                    target = opts2.get(pick2)
                    if not target:
                        st.error("Pick a bill")
                    else:
                        doc_type, doc_id = target
                        bal3 = get_ap_open_balance(vendor_bill_doc_id=doc_id) if doc_type == "vendor_bill" else get_ap_open_balance(doc_id)
                        a2 = float(amt1)
                        if a2 > bal3 + 0.01:
                            st.error(f"Over open balance (₹{bal3:,.2f}).")
                        else:
                            try:
                                if doc_type == "vendor_bill":
                                    insert_ap_payment(None, a2, meth2 or None, n2 or None, vendor_bill_doc_id=doc_id)
                                else:
                                    insert_ap_payment(doc_id, a2, meth2 or None, n2 or None)
                                st.success("Recorded.")
                                st.rerun()
                            except (ValueError, pg_errors.OperationalError) as e:
                                st.error(str(e)[:500])
    with tab3:
        plog2 = list_ap_payments_log()
        if not plog2:
            st.caption("No **AP** payment rows yet.")
        else:
            dfp2 = []
            for p in plog2:
                dfp2.append(
                    {
                        "P#": p.get("id"),
                        "Type": p.get("doc_type") or "—",
                        "When": p.get("paid_at"),
                        "Ref": p.get("vendor_bill_doc_id") or p.get("po_billing_id"),
                        "₹": round(float(p.get("amount") or 0), 2),
                        "Method": p.get("method") or "—",
                        "PO": p.get("po_id"),
                        "Vendor": p.get("vendor_name") or "—",
                    }
                )
            st.dataframe(dfp2, use_container_width=True, hide_index=True)
        pdk2 = {f"#{p['id']}  ₹{float(p['amount']):,.2f}  {p.get('paid_at', '')}": p["id"] for p in plog2}
        selap = st.selectbox("Select payment to **delete**", ["—"] + list(pdk2.keys()) if pdk2 else ["—"], key="ap_del")
        if selap != "—" and st.button("Delete AP payment row", type="primary", key="ap_del_b"):
            try:
                delete_ap_payment(pdk2[selap])
                st.success("Deleted.")
                st.rerun()
            except (ValueError, Exception) as e:
                st.error(str(e)[:400])

elif dmode == "gl":
    st.markdown("##### Chart of accounts (default seed)")
    acc = list_gl_accounts()
    st.dataframe(acc, use_container_width=True, hide_index=True)
    st.caption("**Vendor bill** → Dr Inventory / Cr AP. **Customer bill** → Dr AR, Cr Sales; Dr COGS, Cr Inventory. **Payments** → cash vs AR or AP.")

elif dmode == "journals":
    st.markdown("##### Journal entries (newest first)")
    jl = journal_list(300)
    if not jl:
        st.info("No journals yet. Post a **vendor bill**, **customer bill**, or **AR/AP** payment after opening balance.")
    else:
        st.dataframe(jl, use_container_width=True, hide_index=True)
        jopts = {f"JE #{j['id']}  {j.get('entry_date', '')}  {str(j.get('description', ''))[:48]}": j["id"] for j in jl}
        pickj = st.selectbox("Line detail for journal", list(jopts.keys()) if jopts else ["—"], key="jpick")
        if jopts and pickj in jopts:
            st.dataframe(
                journal_lines(int(jopts[pickj])),
                use_container_width=True,
                hide_index=True,
            )

elif dmode == "pnl":
    st.markdown("##### P&L (cumulative, through selected date)")
    from datetime import date as _date

    dmax = st.date_input("As of", value=_date.today(), key="pnl_asof")
    dstr = dmax.isoformat() if dmax is not None else _date.today().isoformat()
    p = pnl_to_date(dstr)
    c1, c2, c3 = st.columns(3)
    c1.metric("Revenue (credit to sales)", f"₹{p.get('revenue', 0):,.2f}")
    c2.metric("Expense (COGS etc.)", f"₹{p.get('expense', 0):,.2f}")
    c3.metric("Net income (rev − exp)", f"₹{p.get('net_income', 0):,.2f}")

elif dmode == "trial":
    st.markdown("##### Trial balance (Dr − Cr; liability/equity/revenue normal credits show negative in this column)")
    tbr = trial_balance()
    st.dataframe(tbr, use_container_width=True, hide_index=True)
