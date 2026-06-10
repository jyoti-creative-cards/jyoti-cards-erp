export interface StaffPublic {
  id: number;
  name: string;
  username: string;
  role: string;
  is_active: boolean;
  permissions: string[];
  created_at: string;
  updated_at: string;
}

export const ALL_PERMISSIONS: { id: string; label: string; group: string }[] = [
  { id: "people.view",    label: "View people",            group: "People"    },
  { id: "people.edit",    label: "Edit people",            group: "People"    },
  { id: "catalog.view",   label: "View catalog",           group: "Catalog"   },
  { id: "catalog.edit",   label: "Edit catalog",           group: "Catalog"   },
  { id: "stock.view",     label: "View stock",             group: "Stock"     },
  { id: "stock.edit",     label: "Edit stock",             group: "Stock"     },
  { id: "orders.view",    label: "View orders",            group: "Orders"    },
  { id: "orders.edit",    label: "Edit orders",            group: "Orders"    },
  { id: "finance.view",   label: "View finance",           group: "Finance"   },
  { id: "returns.view",   label: "View returns",           group: "Returns"   },
  { id: "returns.edit",   label: "Issue credit notes",     group: "Returns"   },
  { id: "admin.manage",   label: "Manage staff accounts",  group: "Admin"     },
  { id: "admin.setup",    label: "Manage routes/cities/categories/series", group: "Admin" },
  { id: "admin.audit",    label: "View audit log",         group: "Admin"     },
  { id: "recyclebin.view",label: "View & restore recycle bin", group: "Admin" },
  { id: "create.use",     label: "Use create form",        group: "Create"    },
];

export type AuthState =
  | { type: "none" }
  | { type: "admin_key"; key: string }
  | { type: "staff"; token: string; staff: StaffPublic };

export interface CreditNoteReturnItem {
  catalog_product_id: number;
  product_name: string;
  quantity: number;
  unit_price: number;
  line_amount: number;
}

export interface CreditNotePublicFull {
  id: number;
  customer_id: number;
  customer_order_id: number;
  customer_bill_id: number | null;
  amount: string;
  reason: string | null;
  status: string;
  refund_method: string;
  is_full_return: boolean;
  return_items: CreditNoteReturnItem[];
  note_date: string | null;
  paid_out_at: string | null;
  applied_to_bill_id: number | null;
  created_at: string;
  updated_at: string;
}

export interface CustomerPublic {
  id: number;
  name: string;
  phone: string;
  company_name: string | null;
  alias: string | null;
  address: string | null;
  secondary_phone: string | null;
  city: string | null;
  city_id: number | null;
  route_id: number | null;
  credit_limit: string | null;
  credit_override: boolean;
  created_at: string;
  updated_at: string;
  invoice_count?: number;
  total_billed?: string;
}

export interface VendorPublic {
  id: number;
  person_name: string;
  phone: string;
  company_name: string | null;
  alias: string | null;
  secondary_phone: string | null;
  address: string | null;
  billing_percentage: number | null;
  city: string | null;
  created_at: string;
  updated_at: string;
}

export interface RoutePublic {
  id: number;
  name: string;
  notes: string | null;
  is_active: boolean;
}

export interface CityPublic {
  id: number;
  name: string;
  route_id: number | null;
  is_active: boolean;
}

export interface ExpensePublic {
  id: number;
  expense_date: string;
  category: string;
  description: string | null;
  amount: string;
  payment_mode: string;
  reference: string | null;
}

export interface ProductPricePublic {
  id: number;
  catalog_product_id: number;
  buying_price: string;
  selling_price: string;
  start_date: string;
  end_date: string | null;
  is_current: boolean;
}

export interface CatalogProductPublic {
  id: number;
  our_product_id: string;
  vendor_id: number;
  name: string;
  vendor_product_id: string;
  category: string;
  series?: string | null;
  year_group?: string | null;
  unit: string;
  buying_price: number;
  selling_price: number;
  image_keys: string[];
  image_urls: string[];
  created_at: string;
  updated_at: string;
}

export interface PurchaseOrderReceiptLinePublic {
  catalog_product_id: number;
  quantity: number;
  name: string;
}

export interface PurchaseOrderReceiptPublic {
  id: number;
  receipt_number: string | null;
  contact_number: string | null;
  is_partial: boolean;
  receipt_image_url: string | null;
  lines: PurchaseOrderReceiptLinePublic[];
  created_at: string;
  notes: string | null;
}

export interface PurchaseOrderLinePublic {
  catalog_product_id: number;
  quantity: number;
  received_quantity?: number;
  quantity_pending?: number;
  name: string;
  our_product_id: string;
  vendor_product_id: string;
  buying_price: number;
  selling_price: number;
  line_total_buying: number;
}

export interface PurchaseOrderPublic {
  id: number;
  vendor_id: number;
  status: string;
  items: PurchaseOrderLinePublic[];
  receipts?: PurchaseOrderReceiptPublic[];
  notes?: string | null;
  total_buying_value: number;
  created_at: string;
  updated_at: string;
}

export interface ProductAlternativePublic {
  id: number;
  catalog_product_id: number;
  alternative_catalog_product_id: number;
  alternative_our_product_id: string;
  alternative_name: string;
  alternative_category: string;
  alternative_vendor_id: number;
  created_at: string;
}

export interface InventoryRowPublic {
  catalog_product_id: number;
  our_product_id: string;
  name: string;
  category: string;
  vendor_id: number;
  quantity: number;
  low_stock_threshold: number;
  stock_status: string;
  image_urls: string[];
  invoice_count?: number;
  selling_price?: number;
}

export interface StockAdjustmentPublic {
  id: number;
  catalog_product_id: number;
  our_product_id: string;
  quantity_delta: number;
  note: string | null;
  created_at: string;
}

export interface CustomerOrderLinePublic {
  catalog_product_id: number;
  our_product_id?: string;
  product_code?: string;
  name: string;
  quantity: number;
  qty_billed?: number;
  unit_price: string;
  line_total: string;
}

export interface CustomerOrderAdminPublic {
  id: number;
  customer_id: number;
  customer_name: string;
  customer_phone: string;
  status: string;
  items: CustomerOrderLinePublic[];
  total_amount: string;
  notes: string | null;
  customer_notes: string | null;
  shipment_receipt: string | null;
  shipment_contact: string | null;
  shipment_notes: string | null;
  customer_confirmed_delivery_at: string | null;
  invoice_date: string | null;
  invoice_no: string | null;
  receipt_note_no: string | null;
  versions?: { version: number; timestamp: string; event: string; items: unknown[]; total_amount: string; bill_id: number | null }[] | null;
  created_at: string;
  updated_at: string;
}

export interface VendorBillPublic {
  id: number;
  purchase_order_id: number;
  document_key: string | null;
  document_url: string | null;
  bill_lines: Record<string, unknown>[];
  match_status: string;
  match_result: Record<string, unknown> | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface CustomerBillPublic {
  id: number;
  customer_order_id: number;
  gst_enabled: boolean;
  gst_rate_percent: string;
  discount_percent: string | null;
  bill_no?: string | null;
  bill_series_id?: number | null;
  totals: {
    subtotal?: string;
    discount_amount?: string;
    freight_charges?: string;
    packaging_charges?: string;
    gst_amount?: string;
    grand_total?: string;
    [key: string]: unknown;
  };
  document_key: string | null;
  document_url: string | null;
  narration?: string | null;
  bill_status?: string;       // "active" | "cancelled"
  cancelled_by?: string | null;
  cancelled_reason?: string | null;
  created_at: string;
  updated_at: string;
}

export interface BillSeries {
  id: number;
  name: string;
  prefix: string;
  start_num: number;
  end_num: number;
  current_num: number;
  is_active: boolean;
  created_at: string;
}

export interface AuditLogEntry {
  id: number;
  action: string;
  entity_type: string;
  entity_id?: number;
  description: string;
  performed_by?: string;
  ip_address?: string;
  created_at: string;
}

export interface DashboardPublic {
  date_from: string;
  date_to: string;
  revenue_total: string;
  expense_total: string;
  net_pnl: string;
  open_ar_count: number;
  open_ap_count: number;
  monthly_pnl: { month: string; revenue: string; expense: string; net_pnl: string }[];
}

export interface ARInvoicePublic {
  id: number;
  customer_bill_id: number;
  customer_id: number;
  amount: string;
  amount_paid: string;
  balance: string;
  status: string;
  payment_transaction_id: string | null;
  payment_date: string | null;
  payment_receipt_url: string | null;
  paid_at: string | null;
  created_at: string;
}

export interface APBillPublic {
  id: number;
  vendor_bill_id: number;
  vendor_id: number;
  purchase_order_id: number;
  amount: string;
  amount_paid: string;
  balance: string;
  status: string;
  payment_transaction_id: string | null;
  payment_date: string | null;
  payment_receipt_url: string | null;
  paid_at: string | null;
  created_at: string;
}

export interface JournalLinePublic {
  account_code: string;
  debit: string;
  credit: string;
}

export interface JournalEntryPublic {
  id: number;
  posted_at: string;
  memo: string;
  ref_type: string;
  ref_id: number | null;
  lines: JournalLinePublic[];
}

export interface GLAccountRowPublic {
  account_code: string;
  name: string;
  kind: string;
  debit_total: string;
  credit_total: string;
}

export interface PnLReportPublic {
  date_from: string;
  date_to: string;
  revenue_total: string;
  expense_total: string;
  net_pnl: string;
}

export interface FiscalYearPublic {
  id: number;
  name: string;
  start_date: string;
  end_date: string;
  is_closed: boolean;
}

export interface PeriodPublic {
  id: number;
  fiscal_year_id: number;
  name: string;
  start_date: string;
  end_date: string;
  is_locked: boolean;
}

export interface BankAccountPublic {
  id: number;
  name: string;
  account_number: string | null;
  bank_name: string | null;
  ifsc: string | null;
  is_active: boolean;
}

export interface ReconciliationPublic {
  id: number;
  bank_account_id: number;
  period_start: string;
  period_end: string;
  opening_balance: string;
  closing_balance_bank: string;
  closing_balance_books: string;
  difference: string;
  notes: string | null;
  statement_url: string | null;
  is_finalised: boolean;
  created_at: string;
}

export interface CreditNotePublic {
  id: number;
  customer_order_id: number;
  customer_id: number;
  amount: string;
  reason: string | null;
  status: string;
  document_url: string | null;
  note_date: string | null;
  created_at: string;
}

export interface DebitNotePublic {
  id: number;
  purchase_order_id: number;
  vendor_id: number;
  amount: string;
  reason: string | null;
  status: string;
  document_url: string | null;
  note_date: string | null;
  created_at: string;
}
