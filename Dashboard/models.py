"""Customer row + SQL for SQLite (shared with Customer Ordering App)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

CREATE_CUSTOMERS_TABLE = """
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    company_name TEXT,
    phone TEXT NOT NULL,
    alternate_phone TEXT,
    address TEXT,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_customers_phone ON customers(phone);
"""


@dataclass
class Customer:
    id: int
    name: str
    company_name: Optional[str]
    phone: str
    alternate_phone: Optional[str]
    address: Optional[str]
    password_hash: str
    created_at: str


CREATE_VENDORS_TABLE = """
CREATE TABLE IF NOT EXISTS vendors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_name TEXT NOT NULL,
    company_name TEXT,
    primary_phone TEXT NOT NULL,
    secondary_phone TEXT,
    payment_terms INTEGER,
    billing INTEGER,
    notes TEXT,
    issuer_legal_name TEXT,
    issuer_address TEXT,
    issuer_city_pin TEXT,
    issuer_gstin TEXT,
    issuer_phone TEXT,
    issuer_email TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_vendors_phone ON vendors(primary_phone);
"""


@dataclass
class Vendor:
    id: int
    person_name: str
    company_name: Optional[str]
    primary_phone: str
    secondary_phone: Optional[str]
    payment_terms: Optional[int]
    billing: Optional[int]
    notes: Optional[str]
    issuer_legal_name: Optional[str]
    issuer_address: Optional[str]
    issuer_city_pin: Optional[str]
    issuer_gstin: Optional[str]
    issuer_phone: Optional[str]
    issuer_email: Optional[str]
    created_at: str


CREATE_VENDOR_PRODUCTS_TABLE = """
CREATE TABLE IF NOT EXISTS vendor_products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor_id INTEGER NOT NULL,
    vendor_product_id TEXT NOT NULL,
    our_product_id TEXT NOT NULL,
    name TEXT NOT NULL,
    category TEXT,
    cost_price REAL,
    tax_rate REAL,
    tax_inclusive INTEGER,
    image_paths TEXT,
    low_stock_threshold REAL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (vendor_id) REFERENCES vendors (id) ON DELETE CASCADE,
    UNIQUE (vendor_id, vendor_product_id),
    UNIQUE (our_product_id)
);
CREATE INDEX IF NOT EXISTS idx_vendor_products_vendor ON vendor_products (vendor_id);
CREATE INDEX IF NOT EXISTS idx_vendor_products_our_sku ON vendor_products (our_product_id);
"""


@dataclass
class VendorProduct:
    id: int
    vendor_id: int
    vendor_product_id: str
    our_product_id: str
    name: str
    category: Optional[str]
    cost_price: Optional[float]
    tax_rate: Optional[float]
    tax_inclusive: Optional[int]
    image_paths: Optional[str]
    low_stock_threshold: Optional[float]
    created_at: str


CREATE_PURCHASE_ORDERS_TABLE = """
CREATE TABLE IF NOT EXISTS purchase_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity REAL NOT NULL DEFAULT 1,
    unit_cost REAL NOT NULL,
    payment_terms INTEGER,
    billing INTEGER,
    tax_rate REAL,
    tax_inclusive INTEGER,
    notes TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    transport_name TEXT,
    transport_number TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (vendor_id) REFERENCES vendors (id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES vendor_products (id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_po_vendor ON purchase_orders (vendor_id);
CREATE INDEX IF NOT EXISTS idx_po_product ON purchase_orders (product_id);
CREATE INDEX IF NOT EXISTS idx_po_created ON purchase_orders (created_at);
"""


@dataclass
class PurchaseOrder:
    id: int
    vendor_id: int
    product_id: int
    quantity: float
    unit_cost: float
    payment_terms: Optional[int]
    billing: Optional[int]
    tax_rate: Optional[float]
    tax_inclusive: Optional[int]
    notes: Optional[str]
    status: str
    transport_name: Optional[str]
    transport_number: Optional[str]
    created_at: str


CREATE_STOCK_RECEIPTS_TABLE = """
CREATE TABLE IF NOT EXISTS stock_receipts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    po_id INTEGER,
    quantity REAL NOT NULL,
    shipment_id TEXT,
    grn_number TEXT,
    selling_price REAL,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (product_id) REFERENCES vendor_products (id) ON DELETE RESTRICT,
    FOREIGN KEY (po_id) REFERENCES purchase_orders (id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_stock_product ON stock_receipts (product_id);
CREATE INDEX IF NOT EXISTS idx_stock_po ON stock_receipts (po_id);
CREATE INDEX IF NOT EXISTS idx_stock_grn ON stock_receipts (grn_number);
"""


@dataclass
class StockReceipt:
    id: int
    product_id: int
    po_id: Optional[int]
    quantity: float
    shipment_id: Optional[str]
    grn_number: Optional[str]
    selling_price: Optional[float]
    notes: Optional[str]
    created_at: str


CREATE_PO_BILLINGS_TABLE = """
CREATE TABLE IF NOT EXISTS po_billings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    po_id INTEGER NOT NULL UNIQUE,
    vendor_id INTEGER NOT NULL,
    quantity REAL NOT NULL,
    unit_cost REAL NOT NULL,
    billing_pct INTEGER,
    gst_rate_pct REAL,
    raw_line_total REAL NOT NULL,
    gst_taxable_total REAL NOT NULL,
    gst_amount REAL NOT NULL,
    gst_grand_total REAL NOT NULL,
    vendor_invoice_raw TEXT,
    vendor_invoice_gst TEXT,
    notes TEXT,
    snap_vendor_person TEXT,
    snap_vendor_company TEXT,
    snap_vendor_phone TEXT,
    snap_issuer_legal_name TEXT,
    snap_issuer_address TEXT,
    snap_issuer_city_pin TEXT,
    snap_issuer_gstin TEXT,
    snap_issuer_phone TEXT,
    snap_issuer_email TEXT,
    snap_item_sku TEXT,
    snap_item_name TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT,
    FOREIGN KEY (po_id) REFERENCES purchase_orders (id) ON DELETE CASCADE,
    FOREIGN KEY (vendor_id) REFERENCES vendors (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_po_billings_vendor ON po_billings(vendor_id);
"""


@dataclass
class PoBilling:
    id: int
    po_id: int
    vendor_id: int
    quantity: float
    unit_cost: float
    billing_pct: Optional[int]
    gst_rate_pct: Optional[float]
    raw_line_total: float
    gst_taxable_total: float
    gst_amount: float
    gst_grand_total: float
    vendor_invoice_raw: Optional[str]
    vendor_invoice_gst: Optional[str]
    notes: Optional[str]
    created_at: str
    updated_at: Optional[str]
    snap_vendor_person: Optional[str] = None
    snap_vendor_company: Optional[str] = None
    snap_vendor_phone: Optional[str] = None
    snap_issuer_legal_name: Optional[str] = None
    snap_issuer_address: Optional[str] = None
    snap_issuer_city_pin: Optional[str] = None
    snap_issuer_gstin: Optional[str] = None
    snap_issuer_phone: Optional[str] = None
    snap_issuer_email: Optional[str] = None
    snap_item_sku: Optional[str] = None
    snap_item_name: Optional[str] = None
    gl_journal_id: Optional[int] = None


CREATE_CUSTOMER_ORDERS_TABLE = """
CREATE TABLE IF NOT EXISTS customer_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity REAL NOT NULL,
    unit_price REAL NOT NULL,
    billing_pct INTEGER,
    gst_rate_pct REAL,
    status TEXT NOT NULL DEFAULT 'placed',
    shipment_id TEXT,
    transport_name TEXT,
    transport_number TEXT,
    notes TEXT,
    delivery_receipt_number TEXT,
    delivery_contact TEXT,
    delivery_notes TEXT,
    receipt_image_path TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT,
    FOREIGN KEY (customer_id) REFERENCES customers (id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES vendor_products (id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_co_customer ON customer_orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_co_status ON customer_orders(status);
CREATE INDEX IF NOT EXISTS idx_co_created ON customer_orders(created_at);
"""


@dataclass
class CustomerOrder:
    id: int
    customer_id: int
    product_id: int
    quantity: float
    unit_price: float
    billing_pct: Optional[int]
    gst_rate_pct: Optional[float]
    status: str
    shipment_id: Optional[str]
    transport_name: Optional[str]
    transport_number: Optional[str]
    notes: Optional[str]
    delivery_receipt_number: Optional[str]
    delivery_contact: Optional[str]
    delivery_notes: Optional[str]
    receipt_image_path: Optional[str]
    created_at: str
    updated_at: Optional[str]


@dataclass
class CustomerOrderShipment:
    id: int
    customer_order_id: int
    quantity: float
    unit_price: float
    delivery_receipt_number: Optional[str]
    delivery_contact: Optional[str]
    receipt_image_path: Optional[str]
    created_at: str


CREATE_CUSTOMER_ORDER_BILLINGS_TABLE = """
CREATE TABLE IF NOT EXISTS customer_order_billings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_order_id INTEGER NOT NULL UNIQUE,
    customer_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity REAL NOT NULL,
    unit_cost REAL NOT NULL,
    billing_pct INTEGER,
    gst_rate_pct REAL,
    raw_line_total REAL NOT NULL,
    gst_taxable_total REAL NOT NULL,
    gst_amount REAL NOT NULL,
    gst_grand_total REAL NOT NULL,
    vendor_invoice_raw TEXT,
    vendor_invoice_gst TEXT,
    notes TEXT,
    snap_customer_name TEXT,
    snap_customer_company TEXT,
    snap_customer_phone TEXT,
    snap_customer_address TEXT,
    snap_issuer_legal_name TEXT,
    snap_issuer_address TEXT,
    snap_issuer_city_pin TEXT,
    snap_issuer_gstin TEXT,
    snap_issuer_phone TEXT,
    snap_issuer_email TEXT,
    snap_item_sku TEXT,
    snap_item_name TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT,
    FOREIGN KEY (customer_order_id) REFERENCES customer_orders (id) ON DELETE CASCADE,
    FOREIGN KEY (customer_id) REFERENCES customers (id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES vendor_products (id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_cob_customer ON customer_order_billings(customer_id);
"""


@dataclass
class CustomerOrderBilling:
    id: int
    customer_order_id: int
    customer_id: int
    product_id: int
    quantity: float
    unit_cost: float
    billing_pct: Optional[int]
    gst_rate_pct: Optional[float]
    raw_line_total: float
    gst_taxable_total: float
    gst_amount: float
    gst_grand_total: float
    vendor_invoice_raw: Optional[str]
    vendor_invoice_gst: Optional[str]
    notes: Optional[str]
    created_at: str
    updated_at: Optional[str]
    snap_customer_name: Optional[str] = None
    snap_customer_company: Optional[str] = None
    snap_customer_phone: Optional[str] = None
    snap_customer_address: Optional[str] = None
    snap_issuer_legal_name: Optional[str] = None
    snap_issuer_address: Optional[str] = None
    snap_issuer_city_pin: Optional[str] = None
    snap_issuer_gstin: Optional[str] = None
    snap_issuer_phone: Optional[str] = None
    snap_issuer_email: Optional[str] = None
    snap_item_sku: Optional[str] = None
    snap_item_name: Optional[str] = None
    gl_journal_id: Optional[int] = None


CREATE_AR_PAYMENTS_TABLE = """
CREATE TABLE IF NOT EXISTS ar_payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    co_billing_id INTEGER,
    customer_invoice_id INTEGER,
    amount REAL NOT NULL,
    paid_at TEXT NOT NULL DEFAULT (datetime('now')),
    method TEXT,
    note TEXT,
    FOREIGN KEY (co_billing_id) REFERENCES customer_order_billings (id) ON DELETE CASCADE,
    FOREIGN KEY (customer_invoice_id) REFERENCES customer_invoice_docs (id) ON DELETE CASCADE,
    CHECK (co_billing_id IS NOT NULL OR customer_invoice_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_ar_payments_cob ON ar_payments (co_billing_id);
CREATE INDEX IF NOT EXISTS idx_ar_payments_inv ON ar_payments (customer_invoice_id);
"""

CREATE_AP_PAYMENTS_TABLE = """
CREATE TABLE IF NOT EXISTS ap_payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    po_billing_id INTEGER,
    vendor_bill_doc_id INTEGER,
    amount REAL NOT NULL,
    paid_at TEXT NOT NULL DEFAULT (datetime('now')),
    method TEXT,
    note TEXT,
    FOREIGN KEY (po_billing_id) REFERENCES po_billings (id) ON DELETE CASCADE,
    FOREIGN KEY (vendor_bill_doc_id) REFERENCES vendor_bill_docs (id) ON DELETE CASCADE,
    CHECK (po_billing_id IS NOT NULL OR vendor_bill_doc_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_ap_payments_pob ON ap_payments (po_billing_id);
CREATE INDEX IF NOT EXISTS idx_ap_payments_vbd ON ap_payments (vendor_bill_doc_id);
"""

CREATE_PRODUCT_ALTERNATIVES_TABLE = """
CREATE TABLE IF NOT EXISTS product_alternatives (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    alt_product_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (product_id) REFERENCES vendor_products (id) ON DELETE CASCADE,
    FOREIGN KEY (alt_product_id) REFERENCES vendor_products (id) ON DELETE CASCADE,
    CHECK (product_id != alt_product_id),
    UNIQUE (product_id, alt_product_id)
);
CREATE INDEX IF NOT EXISTS idx_palt_base ON product_alternatives (product_id);
CREATE INDEX IF NOT EXISTS idx_palt_alt ON product_alternatives (alt_product_id);
"""


CREATE_WAREHOUSES_TABLE = """
CREATE TABLE IF NOT EXISTS warehouses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    is_default INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_warehouses_default ON warehouses (is_default);
"""


@dataclass
class Warehouse:
    id: int
    code: str
    name: str
    is_default: int
    created_at: str


CREATE_PURCHASE_ORDER_DOCS_TABLE = """
CREATE TABLE IF NOT EXISTS purchase_order_docs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_no TEXT NOT NULL UNIQUE,
    vendor_id INTEGER NOT NULL,
    warehouse_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    payment_terms INTEGER,
    billing INTEGER,
    gst_rate_pct REAL NOT NULL DEFAULT 18,
    transport_name TEXT,
    transport_number TEXT,
    notes TEXT,
    pdf_path TEXT,
    whatsapp_sent_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT,
    FOREIGN KEY (vendor_id) REFERENCES vendors (id) ON DELETE RESTRICT,
    FOREIGN KEY (warehouse_id) REFERENCES warehouses (id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_po_docs_vendor ON purchase_order_docs(vendor_id);
CREATE INDEX IF NOT EXISTS idx_po_docs_status ON purchase_order_docs(status);
CREATE INDEX IF NOT EXISTS idx_po_docs_created ON purchase_order_docs(created_at);
"""


CREATE_PURCHASE_ORDER_DOC_LINES_TABLE = """
CREATE TABLE IF NOT EXISTS purchase_order_doc_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    po_doc_id INTEGER NOT NULL,
    line_no INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    sku TEXT NOT NULL,
    item_name TEXT NOT NULL,
    quantity REAL NOT NULL,
    unit_cost REAL NOT NULL,
    gst_rate_pct REAL NOT NULL DEFAULT 18,
    line_base_total REAL NOT NULL,
    line_gst_total REAL NOT NULL,
    line_grand_total REAL NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (po_doc_id) REFERENCES purchase_order_docs (id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES vendor_products (id) ON DELETE RESTRICT,
    UNIQUE (po_doc_id, line_no)
);
CREATE INDEX IF NOT EXISTS idx_po_doc_lines_doc ON purchase_order_doc_lines(po_doc_id);
CREATE INDEX IF NOT EXISTS idx_po_doc_lines_product ON purchase_order_doc_lines(product_id);
"""


CREATE_GOODS_RECEIPT_DOCS_TABLE = """
CREATE TABLE IF NOT EXISTS goods_receipt_docs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_no TEXT NOT NULL UNIQUE,
    po_doc_id INTEGER NOT NULL,
    warehouse_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'posted',
    vendor_receipt_ref TEXT,
    grn_number TEXT,
    receipt_image_path TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT,
    FOREIGN KEY (po_doc_id) REFERENCES purchase_order_docs (id) ON DELETE RESTRICT,
    FOREIGN KEY (warehouse_id) REFERENCES warehouses (id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_gr_docs_po ON goods_receipt_docs(po_doc_id);
CREATE INDEX IF NOT EXISTS idx_gr_docs_created ON goods_receipt_docs(created_at);
"""


CREATE_GOODS_RECEIPT_LINES_TABLE = """
CREATE TABLE IF NOT EXISTS goods_receipt_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goods_receipt_id INTEGER NOT NULL,
    po_line_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity REAL NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (goods_receipt_id) REFERENCES goods_receipt_docs (id) ON DELETE CASCADE,
    FOREIGN KEY (po_line_id) REFERENCES purchase_order_doc_lines (id) ON DELETE RESTRICT,
    FOREIGN KEY (product_id) REFERENCES vendor_products (id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_gr_lines_receipt ON goods_receipt_lines(goods_receipt_id);
CREATE INDEX IF NOT EXISTS idx_gr_lines_po_line ON goods_receipt_lines(po_line_id);
"""


CREATE_VENDOR_BILL_DOCS_TABLE = """
CREATE TABLE IF NOT EXISTS vendor_bill_docs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_no TEXT NOT NULL UNIQUE,
    vendor_id INTEGER NOT NULL,
    po_doc_id INTEGER NOT NULL,
    goods_receipt_id INTEGER,
    status TEXT NOT NULL DEFAULT 'recorded',
    bill_date TEXT,
    vendor_invoice_ref TEXT,
    vendor_gstin TEXT,
    bill_image_path TEXT,
    notes TEXT,
    base_total REAL NOT NULL DEFAULT 0,
    gst_total REAL NOT NULL DEFAULT 0,
    grand_total REAL NOT NULL DEFAULT 0,
    match_status TEXT NOT NULL DEFAULT 'pending',
    match_summary TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT,
    FOREIGN KEY (vendor_id) REFERENCES vendors (id) ON DELETE RESTRICT,
    FOREIGN KEY (po_doc_id) REFERENCES purchase_order_docs (id) ON DELETE RESTRICT,
    FOREIGN KEY (goods_receipt_id) REFERENCES goods_receipt_docs (id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_vendor_bills_vendor ON vendor_bill_docs(vendor_id);
CREATE INDEX IF NOT EXISTS idx_vendor_bills_po ON vendor_bill_docs(po_doc_id);
CREATE INDEX IF NOT EXISTS idx_vendor_bills_match ON vendor_bill_docs(match_status);
"""


CREATE_VENDOR_BILL_LINES_TABLE = """
CREATE TABLE IF NOT EXISTS vendor_bill_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor_bill_id INTEGER NOT NULL,
    po_line_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity REAL NOT NULL,
    unit_cost REAL NOT NULL,
    gst_rate_pct REAL NOT NULL DEFAULT 18,
    line_base_total REAL NOT NULL,
    line_gst_total REAL NOT NULL,
    line_grand_total REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (vendor_bill_id) REFERENCES vendor_bill_docs (id) ON DELETE CASCADE,
    FOREIGN KEY (po_line_id) REFERENCES purchase_order_doc_lines (id) ON DELETE RESTRICT,
    FOREIGN KEY (product_id) REFERENCES vendor_products (id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_vendor_bill_lines_bill ON vendor_bill_lines(vendor_bill_id);
"""


CREATE_STOCK_MOVEMENTS_TABLE = """
CREATE TABLE IF NOT EXISTS stock_movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    warehouse_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    movement_type TEXT NOT NULL,
    quantity REAL NOT NULL,
    ref_type TEXT NOT NULL,
    ref_id INTEGER NOT NULL,
    ref_line_id INTEGER,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (warehouse_id) REFERENCES warehouses (id) ON DELETE RESTRICT,
    FOREIGN KEY (product_id) REFERENCES vendor_products (id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_stock_movements_product ON stock_movements(product_id);
CREATE INDEX IF NOT EXISTS idx_stock_movements_wh ON stock_movements(warehouse_id);
CREATE INDEX IF NOT EXISTS idx_stock_movements_ref ON stock_movements(ref_type, ref_id);
"""


CREATE_SALES_ORDER_DOCS_TABLE = """
CREATE TABLE IF NOT EXISTS sales_order_docs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_no TEXT NOT NULL UNIQUE,
    customer_id INTEGER NOT NULL,
    warehouse_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'placed',
    gst_rate_pct REAL NOT NULL DEFAULT 18,
    notes TEXT,
    whatsapp_sent_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT,
    FOREIGN KEY (customer_id) REFERENCES customers (id) ON DELETE RESTRICT,
    FOREIGN KEY (warehouse_id) REFERENCES warehouses (id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_so_docs_customer ON sales_order_docs(customer_id);
CREATE INDEX IF NOT EXISTS idx_so_docs_status ON sales_order_docs(status);
"""


CREATE_SALES_ORDER_DOC_LINES_TABLE = """
CREATE TABLE IF NOT EXISTS sales_order_doc_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sales_order_id INTEGER NOT NULL,
    line_no INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    sku TEXT NOT NULL,
    item_name TEXT NOT NULL,
    quantity REAL NOT NULL,
    unit_price_incl_gst REAL NOT NULL,
    gst_rate_pct REAL NOT NULL DEFAULT 18,
    line_base_total REAL NOT NULL,
    line_gst_total REAL NOT NULL,
    line_grand_total REAL NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (sales_order_id) REFERENCES sales_order_docs (id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES vendor_products (id) ON DELETE RESTRICT,
    UNIQUE (sales_order_id, line_no)
);
CREATE INDEX IF NOT EXISTS idx_so_doc_lines_order ON sales_order_doc_lines(sales_order_id);
"""


CREATE_DELIVERY_DOCS_TABLE = """
CREATE TABLE IF NOT EXISTS delivery_docs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    delivery_no TEXT NOT NULL UNIQUE,
    sales_order_id INTEGER NOT NULL,
    warehouse_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'posted',
    delivery_receipt_number TEXT,
    delivery_contact TEXT,
    receipt_image_path TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT,
    FOREIGN KEY (sales_order_id) REFERENCES sales_order_docs (id) ON DELETE RESTRICT,
    FOREIGN KEY (warehouse_id) REFERENCES warehouses (id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_delivery_docs_order ON delivery_docs(sales_order_id);
"""


CREATE_DELIVERY_LINES_TABLE = """
CREATE TABLE IF NOT EXISTS delivery_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    delivery_doc_id INTEGER NOT NULL,
    sales_order_line_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity REAL NOT NULL,
    unit_price_incl_gst REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (delivery_doc_id) REFERENCES delivery_docs (id) ON DELETE CASCADE,
    FOREIGN KEY (sales_order_line_id) REFERENCES sales_order_doc_lines (id) ON DELETE RESTRICT,
    FOREIGN KEY (product_id) REFERENCES vendor_products (id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_delivery_lines_doc ON delivery_lines(delivery_doc_id);
"""


CREATE_CUSTOMER_INVOICE_DOCS_TABLE = """
CREATE TABLE IF NOT EXISTS customer_invoice_docs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_no TEXT NOT NULL UNIQUE,
    sales_order_id INTEGER NOT NULL,
    customer_id INTEGER NOT NULL,
    delivery_doc_id INTEGER,
    status TEXT NOT NULL DEFAULT 'issued',
    invoice_date TEXT,
    gst_rate_pct REAL NOT NULL DEFAULT 18,
    invoice_image_path TEXT,
    pdf_path TEXT,
    notes TEXT,
    base_total REAL NOT NULL DEFAULT 0,
    gst_total REAL NOT NULL DEFAULT 0,
    grand_total REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT,
    FOREIGN KEY (sales_order_id) REFERENCES sales_order_docs (id) ON DELETE RESTRICT,
    FOREIGN KEY (customer_id) REFERENCES customers (id) ON DELETE RESTRICT,
    FOREIGN KEY (delivery_doc_id) REFERENCES delivery_docs (id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_customer_invoices_order ON customer_invoice_docs(sales_order_id);
CREATE INDEX IF NOT EXISTS idx_customer_invoices_customer ON customer_invoice_docs(customer_id);
"""


CREATE_CUSTOMER_INVOICE_LINES_TABLE = """
CREATE TABLE IF NOT EXISTS customer_invoice_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_invoice_id INTEGER NOT NULL,
    sales_order_line_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity REAL NOT NULL,
    unit_price_incl_gst REAL NOT NULL,
    gst_rate_pct REAL NOT NULL DEFAULT 18,
    line_base_total REAL NOT NULL,
    line_gst_total REAL NOT NULL,
    line_grand_total REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (customer_invoice_id) REFERENCES customer_invoice_docs (id) ON DELETE CASCADE,
    FOREIGN KEY (sales_order_line_id) REFERENCES sales_order_doc_lines (id) ON DELETE RESTRICT,
    FOREIGN KEY (product_id) REFERENCES vendor_products (id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_customer_invoice_lines_invoice ON customer_invoice_lines(customer_invoice_id);
"""


@dataclass
class ArPayment:
    id: int
    co_billing_id: int
    amount: float
    paid_at: str
    method: Optional[str]
    note: Optional[str]
    gl_journal_id: Optional[int] = None


@dataclass
class ApPayment:
    id: int
    po_billing_id: int
    amount: float
    paid_at: str
    method: Optional[str]
    note: Optional[str]
    gl_journal_id: Optional[int] = None
