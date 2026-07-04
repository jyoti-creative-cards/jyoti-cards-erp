"use client";

import React, { useCallback, useEffect, useState } from "react";
import { Drawer } from "@/components/Drawer";
import { CatalogScreen } from "@/components/CatalogScreen";
import { apiUrl, fetchApi, formatApiError } from "@/lib/api";
import type { CatalogProductPublic, InventoryRowPublic, StockAdjustmentPublic, VendorPublic } from "@/lib/types";

interface LedgerEntryDetail {
  date: string;
  type: "inward" | "outward" | "adjustment";
  qty: number;
  reference: string;
  party?: string;
  running_balance: number;
}
interface LedgerMonthSummary {
  year: number;
  month: number;
  month_label: string;
  opening: number;
  inward: number;
  outward: number;
  closing: number;
  entries: LedgerEntryDetail[];
}
interface ProductLedgerResponse {
  catalog_product_id: number;
  our_product_id: string;
  name: string;
  current_stock: number;
  invoice_count?: number;
  months: LedgerMonthSummary[];
}

interface VendorOrderLine {
  line_id: string;
  catalog_product_id: number;
  product_name: string;
  qty_ordered: number;
  qty_received: number;
  unit_price: number;
  date_ordered: string;
  date_received: string | null;
  notes: string;
}
interface VendorOrderRecord {
  id: number;
  vendor_id: number;
  vendor_name: string | null;
  status: "open" | "closed";
  items: VendorOrderLine[];
  created_at: string;
  updated_at: string;
}

const INPUT = "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500";
const LABEL = "mb-1 block text-xs font-semibold text-slate-500 uppercase tracking-wider";
const BTN_PRIMARY = "inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-700 disabled:opacity-50";
const BTN_SECONDARY = "inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm transition hover:bg-slate-50";

function stockBadge(status: string, qty?: number) {
  if (status === "negative_stock") return <span className="rounded-full bg-red-200 px-2 py-0.5 text-xs font-bold text-red-900">Negative Stock</span>;
  if (status === "out_of_stock") return <span className="rounded-full bg-slate-200 px-2 py-0.5 text-xs font-medium text-slate-600">Out of Stock</span>;
  if (status === "low_stock") return <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">Low Stock</span>;
  return <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700">In Stock</span>;
}

interface Props {
  adminKey: string;
}

export function StockScreen({ adminKey }: Props) {
  const [tab, setTab] = useState<"current" | "receive" | "adjustments" | "catalog">("current");

  const headers = () => {
    const h: Record<string, string> = { "Content-Type": "application/json" };
    if (adminKey.trim()) h["X-Admin-Key"] = adminKey.trim();
    return h;
  };
  const headersAdmin = (): Record<string, string> => adminKey.trim() ? { "X-Admin-Key": adminKey.trim() } : {};

  const [rows, setRows] = useState<InventoryRowPublic[]>([]);
  const [catalog, setCatalog] = useState<CatalogProductPublic[]>([]);
  const [vendors, setVendors] = useState<VendorPublic[]>([]);
  const [openVendorOrders, setOpenVendorOrders] = useState<VendorOrderRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");

  const loadAll = useCallback(async () => {
    if (!adminKey.trim()) return;
    setLoading(true);
    setLoadError("");
    try {
      const [ir, cr, vr, vor] = await Promise.all([
        fetchApi(apiUrl("inventory") + "?all_catalog=true", { headers: headersAdmin() }),
        fetchApi(apiUrl("catalog") + "?limit=5000", { headers: headersAdmin() }),
        fetchApi(apiUrl("vendors"), { headers: headersAdmin() }),
        fetchApi(apiUrl("vendor-orders"), { headers: headersAdmin() }),
      ]);
      if (ir.ok) setRows(await ir.json());
      else setLoadError("Failed to load inventory.");
      if (cr.ok) {
        const cd = await cr.json() as { items: CatalogProductPublic[] } | CatalogProductPublic[];
        setCatalog(Array.isArray(cd) ? cd : (cd.items ?? []));
      }
      if (vr.ok) setVendors(await vr.json());
      if (vor.ok) {
        const all: VendorOrderRecord[] = await vor.json();
        setOpenVendorOrders(all.filter((v) => v.status === "open"));
      }
    } catch {
      setLoadError("Network error loading stock data.");
    } finally {
      setLoading(false);
    }
  }, [adminKey]);

  useEffect(() => { void loadAll(); }, [loadAll]);

  const vendorName = (id: number) => {
    const v = vendors.find((v) => v.id === id);
    return v?.company_name || v?.person_name || `#${id}`;
  };

  return (
    <div>
      {loadError && (
        <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {loadError} <button type="button" onClick={() => void loadAll()} className="ml-2 underline">Retry</button>
        </div>
      )}
      <div className="mb-6 inline-flex rounded-xl border border-slate-200 bg-white p-1 shadow-sm flex-wrap gap-1">
        {([
          { id: "current",     label: "📊 Stock" },
          { id: "receive",     label: "📥 Receive" },
          { id: "adjustments", label: "✏️ Adjustments" },
          { id: "catalog",     label: "📦 Catalog" },
        ] as const).map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={`rounded-lg px-4 py-2 text-sm font-semibold transition ${
              tab === t.id ? "bg-blue-600 text-white shadow" : "text-slate-600 hover:bg-slate-50"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "current" && (
        <CurrentStockTab
          rows={rows}
          catalog={catalog}
          vendorName={vendorName}
          vendors={vendors}
          headers={headers}
          headersAdmin={headersAdmin}
          adminKey={adminKey}
          onRefresh={loadAll}
          loading={loading}
        />
      )}
      {tab === "receive" && (
        <ReceiveGoodsTab
          catalog={catalog}
          vendors={vendors}
          openVendorOrders={openVendorOrders}
          headers={headers}
          headersAdmin={headersAdmin}
          adminKey={adminKey}
          onRefresh={loadAll}
        />
      )}
      {tab === "adjustments" && (
        <AdjustmentsTab
          catalog={catalog}
          headers={headers}
          headersAdmin={headersAdmin}
          adminKey={adminKey}
          onRefresh={loadAll}
        />
      )}
      {tab === "catalog" && (
        <CatalogScreen adminKey={adminKey} />
      )}
    </div>
  );
}

// ────────────────────────── CURRENT STOCK ──────────────────────────

function CurrentStockTab({
  rows,
  catalog,
  vendorName,
  vendors,
  headers,
  headersAdmin,
  adminKey,
  onRefresh,
  loading,
}: {
  rows: InventoryRowPublic[];
  catalog: CatalogProductPublic[];
  vendorName: (id: number) => string;
  vendors: VendorPublic[];
  headers: () => Record<string, string>;
  headersAdmin: () => Record<string, string>;
  adminKey: string;
  onRefresh: () => void;
  loading?: boolean;
}) {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [vendorFilter, setVendorFilter] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [qtySort, setQtySort] = useState<"" | "asc" | "desc">("");
  const [invoiceSort, setInvoiceSort] = useState<"" | "asc" | "desc">("");
  const [invoiceFilter, setInvoiceFilter] = useState<Set<number>>(new Set());
  const [sellSort, setSellSort] = useState<"" | "asc" | "desc">("");
  const [colDropdown, setColDropdown] = useState<"" | "status" | "category" | "qty" | "invoice" | "sell">("");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerRow, setDrawerRow] = useState<InventoryRowPublic | null>(null);
  const [drawerAlternatives, setDrawerAlternatives] = useState<{id: number; alternative_catalog_product_id: number; alternative_our_product_id: string; alternative_name: string; alternative_category: string}[]>([]);
  const [ledgerRow, setLedgerRow] = useState<InventoryRowPublic | null>(null);
  const [ledgerOpen, setLedgerOpen] = useState(false);
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null);
  // Inline qty edit
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editQty, setEditQty] = useState("");
  // Threshold drafts
  const [threshDraft, setThreshDraft] = useState<Record<number, string>>({});

  const showToast = (msg: string, ok: boolean) => { setToast({ msg, ok }); setTimeout(() => setToast(null), 3500); };

  // Close column dropdowns on outside click
  useEffect(() => {
    if (!colDropdown) return;
    const handler = () => setColDropdown("");
    document.addEventListener("click", handler);
    return () => document.removeEventListener("click", handler);
  }, [colDropdown]);

  const filtered = rows.filter((r) => {
    const q = search.toLowerCase();
    const matchSearch = !q || r.name.toLowerCase().includes(q) || r.our_product_id.toLowerCase().includes(q) || r.category.toLowerCase().includes(q);
    const matchStatus = !statusFilter || r.stock_status === statusFilter;
    const matchVendor = !vendorFilter || String(r.vendor_id) === vendorFilter;
    const matchCategory = !categoryFilter || r.category === categoryFilter;
    const matchInvoice = invoiceFilter.size === 0 || invoiceFilter.has(r.invoice_count ?? 0);
    return matchSearch && matchStatus && matchVendor && matchCategory && matchInvoice;
  }).sort((a, b) => {
    if (invoiceSort === "asc") return (a.invoice_count ?? 0) - (b.invoice_count ?? 0);
    if (invoiceSort === "desc") return (b.invoice_count ?? 0) - (a.invoice_count ?? 0);
    const catA = a.selling_price ?? 0; const catB = b.selling_price ?? 0;
    if (sellSort === "asc") return catA - catB;
    if (sellSort === "desc") return catB - catA;
    if (qtySort === "asc") return a.quantity - b.quantity;
    if (qtySort === "desc") return b.quantity - a.quantity;
    return 0;
  });

  const categories = Array.from(new Set(rows.map((r) => r.category).filter(Boolean))).sort();
  const invoiceCounts = Array.from(new Set(rows.map((r) => r.invoice_count ?? 0))).sort((a, b) => a - b);

  async function saveQty(catalogProductId: number, newQty: number) {
    const current = rows.find((r) => r.catalog_product_id === catalogProductId);
    const delta = newQty - (current?.quantity ?? 0);
    if (delta === 0) { setEditingId(null); return; }
    const r = await fetchApi(apiUrl("inventory/adjustments"), {
      method: "POST", headers: headers(),
      body: JSON.stringify({ catalog_product_id: catalogProductId, quantity_delta: delta, reason: "Manual edit" }),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) { showToast(formatApiError(data), false); return; }
    setEditingId(null);
    showToast("Stock updated.", true);
    onRefresh();
  }

  async function saveThreshold(catalogProductId: number, val: number) {
    const r = await fetchApi(apiUrl(`inventory/balances/${catalogProductId}`), {
      method: "PATCH", headers: headers(),
      body: JSON.stringify({ low_stock_threshold: val }),
    });
    if (r.ok) { showToast("Threshold saved.", true); onRefresh(); }
    else showToast("Failed.", false);
  }

  const drawerCatalog = drawerRow ? catalog.find((c) => c.id === drawerRow.catalog_product_id) : null;

  return (
    <div>
      {toast && (
        <div className={`fixed right-4 top-20 z-50 rounded-lg px-4 py-3 text-sm font-medium shadow-lg ${toast.ok ? "bg-emerald-600 text-white" : "bg-red-600 text-white"}`}>
          {toast.msg}
        </div>
      )}

      {/* Stats row */}
      <div className="mb-4 grid grid-cols-4 gap-3">
        {[
          { label: "In stock",     key: "in_stock",       count: rows.filter((r) => r.stock_status === "in_stock").length,       color: "bg-emerald-50 text-emerald-700 border-emerald-200" },
          { label: "Low stock",    key: "low_stock",      count: rows.filter((r) => r.stock_status === "low_stock").length,      color: "bg-amber-50 text-amber-700 border-amber-200" },
          { label: "Zero stock",   key: "out_of_stock",   count: rows.filter((r) => r.stock_status === "out_of_stock").length,   color: "bg-red-50 text-red-700 border-red-200" },
          { label: "Negative",     key: "negative_stock", count: rows.filter((r) => r.stock_status === "negative_stock").length, color: "bg-red-100 text-red-800 border-red-300" },
        ].map((s) => (
          <div key={s.label} className={`cursor-pointer rounded-xl border p-3 text-center transition hover:shadow-sm ${s.color}`}
            onClick={() => setStatusFilter(statusFilter === s.key ? "" : s.key)}>
            <div className="text-2xl font-bold">{s.count}</div>
            <div className="text-xs font-medium">{s.label}</div>
          </div>
        ))}
      </div>

      {/* Filters */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search products…"
          className="min-w-[200px] flex-1 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none"
        />
        <select value={vendorFilter} onChange={(e) => setVendorFilter(e.target.value)} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm">
          <option value="">All vendors</option>
          {vendors.map((v) => <option key={v.id} value={v.id}>{v.company_name || v.person_name}</option>)}
        </select>
        <button type="button" onClick={onRefresh} className={BTN_SECONDARY}>↻ Refresh</button>
      </div>

      {filtered.length === 0 ? (
        <div className="rounded-xl border-2 border-dashed border-slate-200 py-16 text-center text-slate-400">
          {loading ? (
            <><div className="text-4xl">⏳</div><div className="mt-2 font-medium">Loading stock…</div></>
          ) : (
            <><div className="text-4xl">🏪</div><div className="mt-2 font-medium">No stock items found</div></>
          )}
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-xs font-semibold uppercase text-slate-500">
                <th className="px-4 py-3 text-left">Product</th>
                {/* Category column with filter */}
                <th className="px-4 py-3 text-left">
                  <div className="relative inline-flex items-center gap-1">
                    <span>Category</span>
                    <button
                      type="button"
                      onClick={(e) => { e.stopPropagation(); setColDropdown(colDropdown === "category" ? "" : "category"); }}
                      className={`rounded px-1 py-0.5 text-xs transition ${categoryFilter ? "bg-blue-100 text-blue-700" : "hover:bg-slate-200 text-slate-400"}`}
                      title="Filter category"
                    >▼</button>
                    {colDropdown === "category" && (
                      <div className="absolute left-0 top-7 z-30 min-w-[160px] rounded-xl border border-slate-200 bg-white shadow-xl" onClick={(e) => e.stopPropagation()}>
                        <div className="border-b border-slate-100 px-3 py-2 text-xs font-bold uppercase text-slate-500">Category</div>
                        <button type="button" onClick={() => { setCategoryFilter(""); setColDropdown(""); }}
                          className={`w-full px-3 py-1.5 text-left text-xs hover:bg-slate-50 ${!categoryFilter ? "font-bold text-blue-600" : ""}`}>All</button>
                        {categories.map((c) => (
                          <button key={c} type="button" onClick={() => { setCategoryFilter(c); setColDropdown(""); }}
                            className={`w-full px-3 py-1.5 text-left text-xs hover:bg-slate-50 ${categoryFilter === c ? "font-bold text-blue-600" : ""}`}>{c}</button>
                        ))}
                      </div>
                    )}
                  </div>
                </th>
                {/* Invoices column with filter + sort */}
                <th className="px-4 py-3 text-right">
                  <div className="relative inline-flex items-center justify-end gap-1">
                    <span>Invoices</span>
                    <button
                      type="button"
                      onClick={(e) => { e.stopPropagation(); setColDropdown(colDropdown === "invoice" ? "" : "invoice"); }}
                      className={`rounded px-1 py-0.5 text-xs transition ${invoiceFilter.size > 0 || invoiceSort ? "bg-blue-100 text-blue-700" : "hover:bg-slate-200 text-slate-400"}`}
                    >{invoiceSort === "asc" ? "↑" : invoiceSort === "desc" ? "↓" : "▼"}</button>
                    {colDropdown === "invoice" && (
                      <div className="absolute right-0 top-7 z-30 min-w-[170px] rounded-xl border border-slate-200 bg-white shadow-xl" onClick={(e) => e.stopPropagation()}>
                        <div className="border-b border-slate-100 px-3 py-2 text-xs font-bold uppercase text-slate-500">Sort</div>
                        <button type="button" onClick={() => setInvoiceSort("")} className={`w-full px-3 py-1.5 text-left text-xs hover:bg-slate-50 ${!invoiceSort ? "font-bold text-blue-600" : ""}`}>Default</button>
                        <button type="button" onClick={() => setInvoiceSort("asc")} className={`w-full px-3 py-1.5 text-left text-xs hover:bg-slate-50 ${invoiceSort === "asc" ? "font-bold text-blue-600" : ""}`}>↑ Low to High</button>
                        <button type="button" onClick={() => setInvoiceSort("desc")} className={`w-full px-3 py-1.5 text-left text-xs hover:bg-slate-50 ${invoiceSort === "desc" ? "font-bold text-blue-600" : ""}`}>↓ High to Low</button>
                        <div className="border-t border-slate-100 px-3 py-2 text-xs font-bold uppercase text-slate-500">Filter by count</div>
                        <div className="max-h-40 overflow-y-auto">
                          <label className="flex cursor-pointer items-center gap-2 px-3 py-1.5 text-xs hover:bg-slate-50">
                            <input type="checkbox" checked={invoiceFilter.size === 0} onChange={() => setInvoiceFilter(new Set())} />
                            All
                          </label>
                          {invoiceCounts.map((n) => (
                            <label key={n} className="flex cursor-pointer items-center gap-2 px-3 py-1.5 text-xs hover:bg-slate-50">
                              <input type="checkbox" checked={invoiceFilter.has(n)} onChange={() => {
                                const s = new Set(invoiceFilter);
                                s.has(n) ? s.delete(n) : s.add(n);
                                setInvoiceFilter(s);
                              }} />
                              {n} order{n !== 1 ? "s" : ""}
                            </label>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </th>
                {/* Vendor Orders column */}
                <th className="px-4 py-3 text-right">
                  <span className="text-indigo-600">Vendor Orders</span>
                </th>
                {/* Sell ₹ column with sort */}
                <th className="px-4 py-3 text-right">
                  <div className="relative inline-flex items-center justify-end gap-1">
                    <span>Sell ₹</span>
                    <button
                      type="button"
                      onClick={(e) => { e.stopPropagation(); setColDropdown(colDropdown === "sell" ? "" : "sell"); }}
                      className={`rounded px-1 py-0.5 text-xs transition ${sellSort ? "bg-blue-100 text-blue-700" : "hover:bg-slate-200 text-slate-400"}`}
                    >{sellSort === "asc" ? "↑" : sellSort === "desc" ? "↓" : "▼"}</button>
                    {colDropdown === "sell" && (
                      <div className="absolute right-0 top-7 z-30 min-w-[150px] rounded-xl border border-slate-200 bg-white shadow-xl" onClick={(e) => e.stopPropagation()}>
                        <div className="border-b border-slate-100 px-3 py-2 text-xs font-bold uppercase text-slate-500">Sort Sell ₹</div>
                        <button type="button" onClick={() => { setSellSort(""); setColDropdown(""); }} className={`w-full px-3 py-1.5 text-left text-xs hover:bg-slate-50 ${!sellSort ? "font-bold text-blue-600" : ""}`}>Default</button>
                        <button type="button" onClick={() => { setSellSort("asc"); setColDropdown(""); }} className={`w-full px-3 py-1.5 text-left text-xs hover:bg-slate-50 ${sellSort === "asc" ? "font-bold text-blue-600" : ""}`}>↑ Low to High</button>
                        <button type="button" onClick={() => { setSellSort("desc"); setColDropdown(""); }} className={`w-full px-3 py-1.5 text-left text-xs hover:bg-slate-50 ${sellSort === "desc" ? "font-bold text-blue-600" : ""}`}>↓ High to Low</button>
                      </div>
                    )}
                  </div>
                </th>
                {/* Qty column with sort */}
                <th className="px-4 py-3 text-right">
                  <div className="relative inline-flex items-center justify-end gap-1">
                    <span>Qty</span>
                    <button
                      type="button"
                      onClick={(e) => { e.stopPropagation(); setColDropdown(colDropdown === "qty" ? "" : "qty"); }}
                      className={`rounded px-1 py-0.5 text-xs transition ${qtySort ? "bg-blue-100 text-blue-700" : "hover:bg-slate-200 text-slate-400"}`}
                      title="Sort qty"
                    >{qtySort === "asc" ? "↑" : qtySort === "desc" ? "↓" : "▼"}</button>
                    {colDropdown === "qty" && (
                      <div className="absolute right-0 top-7 z-30 min-w-[140px] rounded-xl border border-slate-200 bg-white shadow-xl" onClick={(e) => e.stopPropagation()}>
                        <div className="border-b border-slate-100 px-3 py-2 text-xs font-bold uppercase text-slate-500">Sort Qty</div>
                        <button type="button" onClick={() => { setQtySort(""); setColDropdown(""); }}
                          className={`w-full px-3 py-1.5 text-left text-xs hover:bg-slate-50 ${!qtySort ? "font-bold text-blue-600" : ""}`}>Default</button>
                        <button type="button" onClick={() => { setQtySort("asc"); setColDropdown(""); }}
                          className={`w-full px-3 py-1.5 text-left text-xs hover:bg-slate-50 ${qtySort === "asc" ? "font-bold text-blue-600" : ""}`}>↑ Low to High</button>
                        <button type="button" onClick={() => { setQtySort("desc"); setColDropdown(""); }}
                          className={`w-full px-3 py-1.5 text-left text-xs hover:bg-slate-50 ${qtySort === "desc" ? "font-bold text-blue-600" : ""}`}>↓ High to Low</button>
                      </div>
                    )}
                  </div>
                </th>
                {/* Status column with filter */}
                <th className="px-4 py-3 text-left">
                  <div className="relative inline-flex items-center gap-1">
                    <span>Status</span>
                    <button
                      type="button"
                      onClick={(e) => { e.stopPropagation(); setColDropdown(colDropdown === "status" ? "" : "status"); }}
                      className={`rounded px-1 py-0.5 text-xs transition ${statusFilter ? "bg-blue-100 text-blue-700" : "hover:bg-slate-200 text-slate-400"}`}
                      title="Filter status"
                    >▼</button>
                    {colDropdown === "status" && (
                      <div className="absolute left-0 top-7 z-30 min-w-[160px] rounded-xl border border-slate-200 bg-white shadow-xl" onClick={(e) => e.stopPropagation()}>
                        <div className="border-b border-slate-100 px-3 py-2 text-xs font-bold uppercase text-slate-500">Status</div>
                        {[
                          { key: "", label: "All" },
                          { key: "in_stock", label: "In Stock" },
                          { key: "low_stock", label: "Low Stock" },
                          { key: "out_of_stock", label: "Out of Stock" },
                          { key: "negative_stock", label: "Negative Stock" },
                        ].map((o) => (
                          <button key={o.key} type="button" onClick={() => { setStatusFilter(o.key); setColDropdown(""); }}
                            className={`w-full px-3 py-1.5 text-left text-xs hover:bg-slate-50 ${statusFilter === o.key ? "font-bold text-blue-600" : ""}`}>{o.label}</button>
                        ))}
                      </div>
                    )}
                  </div>
                </th>
                <th className="px-4 py-3 text-left">Low threshold</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {filtered.map((row) => {
                const catRow = catalog.find((c) => c.id === row.catalog_product_id);
                return (
                  <tr key={row.catalog_product_id} className="transition hover:bg-blue-50/40">
                    <td className="px-4 py-3">
                      <div
                        className="cursor-pointer font-mono font-semibold text-blue-700 hover:underline"
                        onClick={async () => {
  setDrawerRow(row); setDrawerOpen(true); setDrawerAlternatives([]);
  const r = await fetchApi(apiUrl(`catalog/${row.catalog_product_id}/alternatives`), { headers: headersAdmin() }).catch(() => null);
  if (r?.ok) setDrawerAlternatives(await r.json());
}}
                      >
                        {row.our_product_id}
                      </div>
                      <div className="text-xs text-slate-500">{row.name}</div>
                    </td>
                    <td className="px-4 py-3 text-slate-500">{row.category}</td>
                    <td className="px-4 py-3 text-right text-slate-600">{row.invoice_count ?? "—"}</td>
                    <td className="px-4 py-3 text-right text-indigo-600 font-medium">{row.vendor_order_count ?? "—"}</td>
                    <td className="px-4 py-3 text-right font-medium text-slate-700">
                      {row.selling_price != null ? `₹${row.selling_price}` : catRow ? `₹${catRow.selling_price}` : "—"}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {editingId === row.catalog_product_id ? (
                        <div className="flex items-center justify-end gap-1">
                          <input
                            type="number" min={0}
                            value={editQty}
                            onChange={(e) => setEditQty(e.target.value)}
                            autoFocus
                            className="w-20 rounded border border-slate-300 px-1 py-0.5 text-right text-sm"
                            onKeyDown={(e) => {
                              if (e.key === "Enter") void saveQty(row.catalog_product_id, Math.max(0, Math.floor(Number(editQty))));
                              if (e.key === "Escape") setEditingId(null);
                            }}
                          />
                          <button type="button" onClick={() => void saveQty(row.catalog_product_id, Math.max(0, Math.floor(Number(editQty))))} className="rounded bg-blue-600 px-2 py-0.5 text-xs text-white">✓</button>
                          <button type="button" onClick={() => setEditingId(null)} className="text-xs text-slate-400">✕</button>
                        </div>
                      ) : (
                        <button
                          type="button"
                          onClick={() => { setEditingId(row.catalog_product_id); setEditQty(String(row.quantity)); }}
                          className="font-bold text-slate-900 hover:text-blue-600"
                          title="Click to edit"
                        >
                          {row.quantity}
                        </button>
                      )}
                    </td>
                    <td className="px-4 py-3">{stockBadge(row.stock_status, row.quantity)}</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1">
                        <input
                          type="number" min={0}
                          className="w-16 rounded border border-slate-300 px-1 py-0.5 text-sm"
                          value={threshDraft[row.catalog_product_id] ?? String(row.low_stock_threshold ?? 0)}
                          onChange={(e) => setThreshDraft((p) => ({ ...p, [row.catalog_product_id]: e.target.value }))}
                        />
                        <button
                          type="button"
                          onClick={() => void saveThreshold(row.catalog_product_id, Math.max(0, Number(threshDraft[row.catalog_product_id] ?? row.low_stock_threshold ?? 0)))}
                          className="rounded border border-slate-300 px-2 py-0.5 text-xs hover:bg-slate-50"
                        >
                          Set
                        </button>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); setLedgerRow(row); setLedgerOpen(true); }}
                        className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50"
                      >
                        📊 Ledger
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="border-t border-slate-100 px-4 py-2 text-xs text-slate-400">
            {filtered.length} item{filtered.length !== 1 ? "s" : ""}
          </div>
        </div>
      )}

      {ledgerOpen && ledgerRow && (
        <LedgerModal
          row={ledgerRow}
          headersAdmin={headersAdmin}
          onClose={() => { setLedgerOpen(false); setLedgerRow(null); }}
        />
      )}

      {/* Product detail drawer */}
      <Drawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        title={drawerRow?.name ?? ""}
        subtitle={drawerRow ? `${drawerRow.our_product_id} · ${drawerRow.category}` : ""}
      >
        {drawerRow && drawerCatalog && (
          <div className="space-y-4">
            {drawerCatalog.image_urls[0] && (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={drawerCatalog.image_urls[0]} alt={drawerRow.name} className="h-48 w-full rounded-xl object-cover" />
            )}
            <div className="grid grid-cols-2 gap-4">
              <div className="rounded-xl bg-slate-50 p-3 text-center">
                <div className="text-2xl font-bold text-slate-900">{drawerRow.quantity}</div>
                <div className="text-xs text-slate-500">Current stock</div>
              </div>
              <div className="rounded-xl bg-slate-50 p-3 text-center">
                <div className="text-2xl font-bold text-slate-900">₹{drawerCatalog.selling_price}</div>
                <div className="text-xs text-slate-500">Selling price</div>
              </div>
              <div className="rounded-xl bg-slate-50 p-3 text-center">
                <div className="text-lg font-bold text-slate-900">₹{drawerCatalog.buying_price}</div>
                <div className="text-xs text-slate-500">Buying price</div>
              </div>
              <div className="rounded-xl bg-slate-50 p-3 text-center">
                <div className="text-lg font-bold">{stockBadge(drawerRow.stock_status, drawerRow.quantity)}</div>
                <div className="text-xs text-slate-500 mt-1">Status</div>
              </div>
            </div>
            <div className="text-sm text-slate-500">
              <p><span className="font-medium text-slate-700">Vendor:</span> {vendorName(drawerRow.vendor_id)}</p>
              <p><span className="font-medium text-slate-700">Low threshold:</span> {drawerRow.low_stock_threshold ?? 0}</p>
            </div>

            {/* Alternatives */}
            <div>
              <div className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-slate-500">Alternatives / Substitutes</div>
              {drawerAlternatives.length === 0 ? (
                <div className="text-xs text-slate-400 italic">No alternatives configured.</div>
              ) : (
                <div className="space-y-1">
                  {drawerAlternatives.map(alt => {
                    const altStock = rows.find(r => r.catalog_product_id === alt.alternative_catalog_product_id);
                    return (
                      <div key={alt.id} className="flex items-center justify-between rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs">
                        <div>
                          <span className="font-semibold text-slate-700">{alt.alternative_name}</span>
                          <span className="ml-2 text-slate-400">{alt.alternative_our_product_id}</span>
                          <span className="ml-2 text-slate-400">{alt.alternative_category}</span>
                        </div>
                        <div>{altStock ? stockBadge(altStock.stock_status, altStock.quantity) : <span className="text-slate-400">—</span>}</div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        )}
      </Drawer>
    </div>
  );
}

// ────────────────────────── LEDGER MODAL ──────────────────────────

function fmtLedgerDate(raw: string | null | undefined): string {
  if (!raw) return "—";
  try {
    const d = new Date(raw);
    return d.toLocaleString("en-IN", {
      day: "2-digit", month: "short", year: "numeric",
      hour: "2-digit", minute: "2-digit", hour12: true,
    });
  } catch { return raw; }
}

function LedgerModal({
  row,
  headersAdmin,
  onClose,
}: {
  row: InventoryRowPublic;
  headersAdmin: () => Record<string, string>;
  onClose: () => void;
}) {
  const [data, setData] = useState<ProductLedgerResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [expandedMonths, setExpandedMonths] = useState<Set<string>>(new Set());
  const [typeFilter, setTypeFilter] = useState<"all" | "inward" | "outward" | "adjustment">("all");
  const [detail, setDetail] = useState<{ ref: string; data: Record<string, unknown> } | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    if (!data) return;
    setExpandedMonths(new Set(data.months.map((m) => `${m.year}-${m.month}`)));
  }, [data]);

  useEffect(() => {
    setLoading(true);
    setError("");
    fetchApi(apiUrl(`inventory/${row.catalog_product_id}/ledger`), { headers: headersAdmin() })
      .then(async (r) => {
        if (!r.ok) { setError("Failed to load ledger."); return; }
        setData(await r.json());
      })
      .catch(() => setError("Network error."))
      .finally(() => setLoading(false));
  }, [row.catalog_product_id]);

  function toggleMonth(key: string) {
    setExpandedMonths((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  }

  async function openDetail(reference: string) {
    setDetailLoading(true);
    setDetail(null);
    try {
      let url = "";
      if (reference.startsWith("ORD-")) url = apiUrl(`customer-orders/${reference.slice(4)}`);
      else if (reference.startsWith("VO-")) url = apiUrl(`vendor-orders/${reference.slice(3)}`);
      else if (reference.startsWith("ADJ-")) { setDetail({ ref: reference, data: { note: "Stock adjustment", id: reference } }); setDetailLoading(false); return; }
      else { setDetail({ ref: reference, data: { note: reference } }); setDetailLoading(false); return; }
      const r = await fetchApi(url, { headers: headersAdmin() });
      const d = await r.json();
      setDetail({ ref: reference, data: d });
    } catch { setDetail({ ref: reference, data: { error: "Could not load details." } }); }
    setDetailLoading(false);
  }

  // Flatten all entries for filtering
  const allEntries = data ? data.months.flatMap((m) => m.entries) : [];
  const filtered = allEntries.filter((en) => typeFilter === "all" || en.type === typeFilter);

  return (
    <div
      style={{ position: "fixed", inset: 0, zIndex: 60, display: "flex", alignItems: "center", justifyContent: "center", background: "rgba(0,0,0,0.45)" }}
      onClick={onClose}
    >
      <div
        style={{ background: "#fff", borderRadius: 16, width: "min(900px, 96vw)", maxHeight: "92vh", display: "flex", flexDirection: "column", overflow: "hidden", boxShadow: "0 25px 50px rgba(0,0,0,0.25)" }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div style={{ padding: "18px 24px 14px", borderBottom: "1px solid #e2e8f0", display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
          <div>
            <div style={{ fontSize: 17, fontWeight: 700, color: "#0f172a" }}>📒 Ledger — {row.name}</div>
            <div style={{ fontSize: 12, color: "#64748b", marginTop: 2 }}>
              {row.our_product_id} · Current stock: <strong>{data?.current_stock ?? row.quantity}</strong>
              {data?.invoice_count != null && <> · Sales orders: <strong>{data.invoice_count}</strong></>}
            </div>
          </div>
          <button type="button" onClick={onClose} style={{ fontSize: 20, lineHeight: 1, background: "none", border: "none", cursor: "pointer", color: "#94a3b8", padding: "2px 6px" }}>✕</button>
        </div>

        {/* Filters */}
        <div style={{ padding: "10px 24px", borderBottom: "1px solid #f1f5f9", display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          {(["all", "inward", "outward", "adjustment"] as const).map((t) => (
            <button key={t} type="button" onClick={() => setTypeFilter(t)}
              style={{
                padding: "4px 14px", borderRadius: 20, fontSize: 12, fontWeight: 600, border: "1px solid",
                cursor: "pointer",
                background: typeFilter === t ? (t === "inward" ? "#dcfce7" : t === "outward" ? "#fee2e2" : t === "adjustment" ? "#ede9fe" : "#eff6ff") : "#f8fafc",
                color: typeFilter === t ? (t === "inward" ? "#15803d" : t === "outward" ? "#b91c1c" : t === "adjustment" ? "#6d28d9" : "#1d4ed8") : "#64748b",
                borderColor: typeFilter === t ? "currentColor" : "#e2e8f0",
              }}>
              {t === "all" ? `All (${allEntries.length})` : t === "inward" ? `↓ Inward (${allEntries.filter(e => e.type === "inward").length})` : t === "outward" ? `↑ Outward (${allEntries.filter(e => e.type === "outward").length})` : `⚙ Adjustment (${allEntries.filter(e => e.type === "adjustment").length})`}
            </button>
          ))}
          <span style={{ marginLeft: "auto", fontSize: 11, color: "#94a3b8" }}>Click any row to view details</span>
        </div>

        {/* Body: split view if detail is open */}
        <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
          {/* Ledger table */}
          <div style={{ flex: 1, overflowY: "auto", padding: "0 0 16px 0" }}>
            {loading && <div style={{ textAlign: "center", padding: "48px 0", color: "#94a3b8" }}>Loading…</div>}
            {error && <div style={{ textAlign: "center", padding: "48px 0", color: "#ef4444" }}>{error}</div>}
            {data && !loading && (
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                <thead style={{ position: "sticky", top: 0, zIndex: 2 }}>
                  <tr style={{ background: "#f8fafc", borderBottom: "1px solid #e2e8f0" }}>
                    <th style={{ padding: "8px 16px", textAlign: "left", fontSize: 11, fontWeight: 600, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.05em" }}>Date & Time</th>
                    <th style={{ padding: "8px 12px", textAlign: "left", fontSize: 11, fontWeight: 600, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.05em" }}>Type</th>
                    <th style={{ padding: "8px 12px", textAlign: "left", fontSize: 11, fontWeight: 600, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.05em" }}>Party / Reference</th>
                    <th style={{ padding: "8px 12px", textAlign: "right", fontSize: 11, fontWeight: 600, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.05em" }}>Qty</th>
                    <th style={{ padding: "8px 16px", textAlign: "right", fontSize: 11, fontWeight: 600, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.05em" }}>Balance</th>
                  </tr>
                </thead>
                <tbody>
                  {typeFilter === "all" ? (
                    // grouped by month
                    data.months.map((m) => {
                      const key = `${m.year}-${m.month}`;
                      const expanded = expandedMonths.has(key);
                      return (
                        <React.Fragment key={key}>
                          <tr style={{ background: "#f1f5f9", cursor: "pointer", borderBottom: "1px solid #e2e8f0" }} onClick={() => toggleMonth(key)}>
                            <td colSpan={3} style={{ padding: "7px 16px", fontWeight: 700, color: "#334155", fontSize: 12 }}>
                              {expanded ? "▾" : "▸"} {m.month_label}
                              <span style={{ marginLeft: 12, fontWeight: 400, color: "#64748b", fontSize: 11 }}>
                                {m.entries.length} transactions · Opening {m.opening} → Closing {m.closing}
                              </span>
                            </td>
                            <td style={{ padding: "7px 12px", textAlign: "right", fontSize: 12 }}>
                              <span style={{ color: "#16a34a", fontWeight: 600 }}>{m.inward > 0 ? `+${m.inward}` : ""}</span>
                              {m.inward > 0 && m.outward > 0 && <span style={{ color: "#94a3b8", margin: "0 4px" }}>/</span>}
                              <span style={{ color: "#dc2626", fontWeight: 600 }}>{m.outward > 0 ? `-${m.outward}` : ""}</span>
                            </td>
                            <td style={{ padding: "7px 16px", textAlign: "right", fontWeight: 700, color: "#0f172a", fontSize: 12 }}>{m.closing}</td>
                          </tr>
                          {expanded && m.entries.map((en, i) => (
                            <EntryRow key={i} en={en} onClick={() => openDetail(en.reference)} active={detail?.ref === en.reference} />
                          ))}
                        </React.Fragment>
                      );
                    })
                  ) : (
                    // flat filtered list
                    filtered.map((en, i) => (
                      <EntryRow key={i} en={en} onClick={() => openDetail(en.reference)} active={detail?.ref === en.reference} />
                    ))
                  )}
                  {(typeFilter === "all" ? data.months.length === 0 : filtered.length === 0) && (
                    <tr><td colSpan={5} style={{ padding: "48px 0", textAlign: "center", color: "#94a3b8" }}>No entries found.</td></tr>
                  )}
                </tbody>
              </table>
            )}
          </div>

          {/* Detail panel */}
          {(detail || detailLoading) && (
            <div style={{ width: 300, borderLeft: "1px solid #e2e8f0", overflowY: "auto", padding: "16px", background: "#fafafa", flexShrink: 0 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                <span style={{ fontWeight: 700, fontSize: 13, color: "#0f172a" }}>{detail?.ref ?? "Loading…"}</span>
                <button type="button" onClick={() => setDetail(null)} style={{ background: "none", border: "none", cursor: "pointer", color: "#94a3b8", fontSize: 16 }}>✕</button>
              </div>
              {detailLoading && <div style={{ color: "#94a3b8", fontSize: 12 }}>Loading…</div>}
              {detail && !detailLoading && <DetailPanel ref_={detail.ref} data={detail.data} />}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function EntryRow({ en, onClick, active }: { en: LedgerEntryDetail; onClick: () => void; active: boolean }) {
  return (
    <tr
      onClick={onClick}
      style={{
        borderBottom: "1px solid #f1f5f9",
        cursor: "pointer",
        background: active ? "#eff6ff" : undefined,
        transition: "background 0.1s",
      }}
      onMouseEnter={(e) => { if (!active) (e.currentTarget as HTMLTableRowElement).style.background = "#f8fafc"; }}
      onMouseLeave={(e) => { if (!active) (e.currentTarget as HTMLTableRowElement).style.background = ""; }}
    >
      <td style={{ padding: "7px 16px", color: "#475569", fontSize: 12, whiteSpace: "nowrap" }}>{fmtLedgerDate(String(en.date))}</td>
      <td style={{ padding: "7px 12px" }}>
        <span style={{
          display: "inline-block", padding: "2px 8px", borderRadius: 10, fontSize: 11, fontWeight: 600,
          background: en.type === "inward" ? "#dcfce7" : en.type === "outward" ? "#fee2e2" : "#ede9fe",
          color: en.type === "inward" ? "#15803d" : en.type === "outward" ? "#b91c1c" : "#6d28d9",
        }}>
          {en.type === "inward" ? "↓ Inward" : en.type === "outward" ? "↑ Outward" : "⚙ Adj"}
        </span>
      </td>
      <td style={{ padding: "7px 12px", color: "#334155", fontSize: 12 }}>
        {en.party && <span style={{ fontWeight: 500, marginRight: 6 }}>{en.party}</span>}
        <span style={{ color: "#94a3b8", fontSize: 11 }}>{en.reference}</span>
      </td>
      <td style={{ padding: "7px 12px", textAlign: "right", fontWeight: 700, color: en.type === "inward" ? "#15803d" : en.type === "outward" ? "#b91c1c" : "#475569" }}>
        {en.type === "inward" ? `+${en.qty}` : en.type === "outward" ? `−${Math.abs(en.qty)}` : en.qty > 0 ? `+${en.qty}` : en.qty}
      </td>
      <td style={{ padding: "7px 16px", textAlign: "right", fontWeight: 700, color: "#0f172a" }}>{en.running_balance}</td>
    </tr>
  );
}

function DetailPanel({ ref_, data }: { ref_: string; data: Record<string, unknown> }) {
  const isOrder = ref_.startsWith("ORD-");
  const isVO = ref_.startsWith("VO-");

  if (data.error) return <div style={{ color: "#ef4444", fontSize: 12 }}>{String(data.error)}</div>;

  if (isOrder) {
    const o = data as Record<string, unknown>;
    const items = (o.items as Record<string, unknown>[]) ?? [];
    const total = o.total_amount ?? o.grand_total;
    return (
      <div style={{ fontSize: 12, color: "#334155" }}>
        <div style={{ marginBottom: 10, paddingBottom: 10, borderBottom: "1px solid #e2e8f0" }}>
          <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 4 }}>Order #{String(o.id)}</div>
          <span style={{ padding: "2px 10px", borderRadius: 10, background: "#f1f5f9", fontSize: 11, fontWeight: 600, color: "#475569" }}>{String(o.status ?? "")}</span>
        </div>
        <div style={{ marginBottom: 4 }}><strong>Customer:</strong> {String(o.customer_name ?? o.customer_id ?? "—")}</div>
        {o.customer_phone && <div style={{ marginBottom: 4 }}><strong>Phone:</strong> {String(o.customer_phone)}</div>}
        <div style={{ marginBottom: 4 }}><strong>Date:</strong> {fmtLedgerDate(String(o.created_at ?? ""))}</div>
        {o.invoice_no && <div style={{ marginBottom: 4 }}><strong>Invoice:</strong> {String(o.invoice_no)}</div>}
        {o.notes && <div style={{ marginBottom: 4 }}><strong>Notes:</strong> {String(o.notes)}</div>}
        {o.customer_notes && <div style={{ marginBottom: 4 }}><strong>Customer notes:</strong> {String(o.customer_notes)}</div>}
        <div style={{ marginTop: 12, marginBottom: 6, fontWeight: 700, fontSize: 11, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.05em" }}>Items</div>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
          <thead>
            <tr style={{ background: "#f8fafc", borderBottom: "1px solid #e2e8f0" }}>
              <th style={{ padding: "4px 6px", textAlign: "left", color: "#64748b", fontWeight: 600 }}>Item #</th>
              <th style={{ padding: "4px 6px", textAlign: "left", color: "#64748b", fontWeight: 600 }}>Name</th>
              <th style={{ padding: "4px 6px", textAlign: "right", color: "#64748b", fontWeight: 600 }}>Qty</th>
              <th style={{ padding: "4px 6px", textAlign: "right", color: "#64748b", fontWeight: 600 }}>Rate</th>
              <th style={{ padding: "4px 6px", textAlign: "right", color: "#64748b", fontWeight: 600 }}>Total</th>
            </tr>
          </thead>
          <tbody>
            {items.map((it, i) => (
              <tr key={i} style={{ borderBottom: "1px solid #f1f5f9" }}>
                <td style={{ padding: "5px 6px", fontFamily: "monospace", color: "#475569", whiteSpace: "nowrap" }}>{String(it.our_product_id ?? it.catalog_product_id ?? "—")}</td>
                <td style={{ padding: "5px 6px", fontWeight: 500 }}>{String(it.name ?? it.product_name ?? "—")}</td>
                <td style={{ padding: "5px 6px", textAlign: "right" }}>{String(it.quantity ?? it.qty ?? "—")}</td>
                <td style={{ padding: "5px 6px", textAlign: "right" }}>₹{String(it.unit_price ?? it.price ?? "—")}</td>
                <td style={{ padding: "5px 6px", textAlign: "right", fontWeight: 600 }}>₹{String(it.line_total ?? "—")}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {total && (
          <div style={{ marginTop: 8, textAlign: "right", fontWeight: 700, fontSize: 13, color: "#0f172a", borderTop: "2px solid #e2e8f0", paddingTop: 6 }}>
            Total: ₹{String(total)}
          </div>
        )}
      </div>
    );
  }

  if (isVO) {
    const o = data as Record<string, unknown>;
    const items = (o.items as Record<string, unknown>[]) ?? [];
    return (
      <div style={{ fontSize: 12, color: "#334155" }}>
        <div style={{ marginBottom: 10, paddingBottom: 10, borderBottom: "1px solid #e2e8f0" }}>
          <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 4 }}>Vendor Order #{String(o.id)}</div>
          <span style={{ padding: "2px 10px", borderRadius: 10, background: "#f1f5f9", fontSize: 11, fontWeight: 600, color: "#475569" }}>{String(o.status ?? "")}</span>
        </div>
        <div style={{ marginBottom: 4 }}><strong>Vendor:</strong> {String(o.vendor_name ?? o.vendor_id ?? "—")}</div>
        <div style={{ marginBottom: 4 }}><strong>Date:</strong> {fmtLedgerDate(String(o.created_at ?? ""))}</div>
        {o.bill_number && <div style={{ marginBottom: 4 }}><strong>Bill:</strong> {String(o.bill_number)}</div>}
        {o.bill_amount && <div style={{ marginBottom: 4 }}><strong>Bill amount:</strong> ₹{String(o.bill_amount)}</div>}
        {o.notes && <div style={{ marginBottom: 4 }}><strong>Notes:</strong> {String(o.notes)}</div>}
        <div style={{ marginTop: 12, marginBottom: 6, fontWeight: 700, fontSize: 11, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.05em" }}>Items</div>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
          <thead>
            <tr style={{ background: "#f8fafc", borderBottom: "1px solid #e2e8f0" }}>
              <th style={{ padding: "4px 6px", textAlign: "left", color: "#64748b", fontWeight: 600 }}>Item #</th>
              <th style={{ padding: "4px 6px", textAlign: "left", color: "#64748b", fontWeight: 600 }}>Name</th>
              <th style={{ padding: "4px 6px", textAlign: "right", color: "#64748b", fontWeight: 600 }}>Ordered</th>
              <th style={{ padding: "4px 6px", textAlign: "right", color: "#64748b", fontWeight: 600 }}>Received</th>
              <th style={{ padding: "4px 6px", textAlign: "right", color: "#64748b", fontWeight: 600 }}>Rate</th>
            </tr>
          </thead>
          <tbody>
            {items.map((it, i) => (
              <tr key={i} style={{ borderBottom: "1px solid #f1f5f9" }}>
                <td style={{ padding: "5px 6px", fontFamily: "monospace", color: "#475569" }}>{String(it.our_product_id ?? it.catalog_product_id ?? "—")}</td>
                <td style={{ padding: "5px 6px", fontWeight: 500 }}>{String(it.product_name ?? it.name ?? "—")}</td>
                <td style={{ padding: "5px 6px", textAlign: "right" }}>{String(it.qty_ordered ?? "—")}</td>
                <td style={{ padding: "5px 6px", textAlign: "right", color: it.qty_received ? "#16a34a" : "#94a3b8", fontWeight: 600 }}>{String(it.qty_received ?? "0")}</td>
                <td style={{ padding: "5px 6px", textAlign: "right" }}>₹{String(it.unit_price ?? "—")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  return (
    <div style={{ fontSize: 12, color: "#334155" }}>
      <div style={{ marginBottom: 6, fontWeight: 600 }}>{ref_}</div>
      {Object.entries(data).map(([k, v]) => (
        <div key={k} style={{ marginBottom: 3 }}><strong>{k}:</strong> {String(v ?? "—")}</div>
      ))}
    </div>
  );
}

// ────────────────────────── ADJUSTMENTS LOG ──────────────────────────

function AdjustmentsTab({
  catalog,
  headers,
  headersAdmin,
  adminKey,
  onRefresh,
}: {
  catalog: CatalogProductPublic[];
  headers: () => Record<string, string>;
  headersAdmin: () => Record<string, string>;
  adminKey: string;
  onRefresh: () => void;
}) {
  const [adjustments, setAdjustments] = useState<StockAdjustmentPublic[]>([]);
  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);

  const showToast = (msg: string, ok: boolean) => { setToast({ msg, ok }); setTimeout(() => setToast(null), 3500); };

  const load = useCallback(async () => {
    if (!adminKey.trim()) return;
    setLoading(true);
    const r = await fetchApi(apiUrl("inventory/adjustments"), { headers: headersAdmin() });
    if (r.ok) setAdjustments(await r.json());
    setLoading(false);
  }, [adminKey]);

  useEffect(() => { void load(); }, [load]);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setSaving(true);
    const fd = new FormData(e.currentTarget);
    const body = {
      catalog_product_id: Number(fd.get("catalog_product_id")),
      quantity_delta: Number(fd.get("quantity_delta")),
      reason: fd.get("reason") || "Manual",
    };
    const r = await fetchApi(apiUrl("inventory/adjustments"), { method: "POST", headers: headers(), body: JSON.stringify(body) });
    const data = await r.json().catch(() => ({}));
    setSaving(false);
    if (!r.ok) { showToast(formatApiError(data), false); return; }
    showToast("Adjustment recorded.", true);
    (e.target as HTMLFormElement).reset();
    setShowForm(false);
    void load();
    onRefresh();
  }

  const productName = (id: number) => catalog.find((c) => c.id === id)?.name ?? `#${id}`;

  return (
    <div>
      {toast && (
        <div className={`fixed right-4 top-20 z-50 rounded-lg px-4 py-3 text-sm font-medium shadow-lg ${toast.ok ? "bg-emerald-600 text-white" : "bg-red-600 text-white"}`}>
          {toast.msg}
        </div>
      )}

      <div className="mb-4 flex items-center gap-3">
        <button type="button" onClick={() => void load()} className={BTN_SECONDARY}>↻ Refresh</button>
        <button type="button" onClick={() => setShowForm((v) => !v)} className={BTN_PRIMARY}>
          + New adjustment
        </button>
      </div>

      {showForm && (
        <form onSubmit={onSubmit} className="mb-6 grid grid-cols-3 gap-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div>
            <label className={LABEL}>Product *</label>
            <select name="catalog_product_id" required className={INPUT}>
              <option value="">— select —</option>
              {catalog.map((p) => <option key={p.id} value={p.id}>{p.our_product_id} — {p.name}</option>)}
            </select>
          </div>
          <div>
            <label className={LABEL}>Qty delta * (+ add / − remove)</label>
            <input name="quantity_delta" type="number" required className={INPUT} placeholder="e.g. +50 or -10" />
          </div>
          <div>
            <label className={LABEL}>Reason</label>
            <input name="reason" className={INPUT} placeholder="e.g. Damage, Recount" />
          </div>
          <div className="col-span-3">
            <button type="submit" disabled={saving} className={BTN_PRIMARY}>
              {saving ? "Saving…" : "Record adjustment"}
            </button>
          </div>
        </form>
      )}

      {loading ? (
        <div className="py-12 text-center text-slate-400">Loading…</div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-xs font-semibold uppercase text-slate-500">
                <th className="px-4 py-3 text-left">Product</th>
                <th className="px-4 py-3 text-right">Delta</th>
                <th className="px-4 py-3 text-left">Reason</th>
                <th className="px-4 py-3 text-left">Date</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {adjustments.map((a) => (
                <tr key={a.id}>
                  <td className="px-4 py-3 font-medium">{productName(a.catalog_product_id)}</td>
                  <td className={`px-4 py-3 text-right font-mono font-bold ${a.quantity_delta > 0 ? "text-emerald-600" : "text-red-600"}`}>
                    {a.quantity_delta > 0 ? "+" : ""}{a.quantity_delta}
                  </td>
                  <td className="px-4 py-3 text-slate-500">{a.note ?? "—"}</td>
                  <td className="px-4 py-3 text-slate-400 text-xs">{new Date(a.created_at).toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" })}</td>
                </tr>
              ))}
              {adjustments.length === 0 && (
                <tr><td colSpan={4} className="px-4 py-8 text-center text-slate-400">No adjustments yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ────────────────────────── RECEIVE GOODS ──────────────────────────

function ReceiveGoodsTab({
  catalog,
  vendors,
  openVendorOrders,
  headers,
  headersAdmin,
  adminKey,
  onRefresh,
}: {
  catalog: CatalogProductPublic[];
  vendors: VendorPublic[];
  openVendorOrders: VendorOrderRecord[];
  headers: () => Record<string, string>;
  headersAdmin: () => Record<string, string>;
  adminKey: string;
  onRefresh: () => void;
}) {
  const [mode, setMode] = useState<"vo" | "manual">("vo");

  // ── Vendor Orders (new system) state ──────────────────────────────────
  const [voVendorFilter, setVoVendorFilter] = useState("");
  const [selVo, setSelVo] = useState<VendorOrderRecord | null>(null);
  const [voRecvQty, setVoRecvQty] = useState<Record<string, string>>({});
  const [voDate, setVoDate] = useState(new Date().toISOString().slice(0, 10));
  const [voBillNum, setVoBillNum] = useState("");
  const [voBillAmt, setVoBillAmt] = useState("");
  const [voSaving, setVoSaving] = useState(false);
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null);
  const showToast = (msg: string, ok: boolean) => { setToast({ msg, ok }); setTimeout(() => setToast(null), 3500); };

  const filteredVOs = openVendorOrders.filter((vo) =>
    !voVendorFilter || String(vo.vendor_id) === voVendorFilter
  );

  function selectVo(vo: VendorOrderRecord) {
    setSelVo(vo);
    const init: Record<string, string> = {};
    vo.items.forEach((it) => {
      const pending = it.qty_ordered - it.qty_received;
      if (pending > 0) init[it.line_id] = String(pending);
    });
    setVoRecvQty(init);
  }

  async function receiveFromVo(e: React.FormEvent) {
    e.preventDefault();
    if (!selVo) return;
    if (!voBillNum.trim()) { showToast("Enter vendor's bill number", false); return; }
    if (!voBillAmt.trim() || Number(voBillAmt) <= 0) { showToast("Enter vendor's bill amount", false); return; }
    const lines = selVo.items
      .filter((it) => Number(voRecvQty[it.line_id] || 0) > 0)
      .map((it) => ({
        line_id: it.line_id,
        catalog_product_id: it.catalog_product_id,
        qty_received: Number(voRecvQty[it.line_id]),
        date_received: new Date(voDate).toISOString(),
      }));
    if (!lines.length) { showToast("Enter qty for at least one item", false); return; }
    setVoSaving(true);
    const r = await fetchApi(apiUrl(`vendor-orders/${selVo.id}/receive`), {
      method: "POST", headers: { ...headersAdmin(), "Content-Type": "application/json" },
      body: JSON.stringify({ lines, bill_number: voBillNum.trim(), bill_amount: Number(voBillAmt) }),
    });
    const data = await r.json().catch(() => ({}));
    setVoSaving(false);
    if (!r.ok) { showToast(formatApiError(data) || "Failed", false); return; }
    showToast("Stock received + AP entry created!", true);
    setSelVo(null); setVoRecvQty({}); setVoBillNum(""); setVoBillAmt("");
    onRefresh();
  }

  // Ad-hoc / Manual state
  const [manualVendorId, setManualVendorId] = useState("");
  const [manualRows, setManualRows] = useState<{ cid: string; qty: string }[]>([{ cid: "", qty: "" }]);
  const [manualNotes, setManualNotes] = useState("");
  const [manualSaving, setManualSaving] = useState(false);

  const manualVendorProducts = catalog.filter((p) => manualVendorId && String(p.vendor_id) === manualVendorId);

  async function manualReceive(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!manualVendorId) { showToast("Select a vendor", false); return; }
    const items = manualRows
      .filter((r) => r.cid && Number(r.qty) > 0)
      .map((r) => ({ catalog_product_id: Number(r.cid), quantity: Number(r.qty) }));
    if (!items.length) { showToast("Add at least one item with quantity", false); return; }
    setManualSaving(true);
    const body = { vendor_id: Number(manualVendorId), items, notes: manualNotes.trim() || undefined };
    const r = await fetchApi(apiUrl("inventory/receipts/adhoc"), { method: "POST", headers: headers(), body: JSON.stringify(body) });
    const data = await r.json().catch(() => ({}));
    setManualSaving(false);
    if (!r.ok) { showToast(formatApiError(data), false); return; }
    showToast("Stock added and vendor order created.", true);
    setManualVendorId(""); setManualRows([{ cid: "", qty: "" }]); setManualNotes("");
    onRefresh();
  }

  return (
    <div>
      {toast && (
        <div className={`fixed right-4 top-20 z-50 rounded-lg px-4 py-3 text-sm font-medium shadow-lg ${toast.ok ? "bg-emerald-600 text-white" : "bg-red-600 text-white"}`}>
          {toast.msg}
        </div>
      )}

      <div className="mb-4 flex flex-wrap gap-2">
        {[
          { id: "vo", label: `📋 Open Vendor Orders (${openVendorOrders.length})` },
          { id: "manual", label: "Ad-hoc / Manual" },
        ].map((m) => (
          <button key={m.id} type="button" onClick={() => setMode(m.id as "vo" | "manual")}
            className={`rounded-lg px-4 py-2 text-sm font-semibold ${mode === m.id ? "bg-blue-600 text-white" : "border border-slate-300 bg-white text-slate-700 hover:bg-slate-50"}`}>
            {m.label}
          </button>
        ))}
      </div>

      {/* ── Vendor Orders mode ── */}
      {mode === "vo" && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <select value={voVendorFilter} onChange={(e) => { setVoVendorFilter(e.target.value); setSelVo(null); }}
              className={INPUT + " max-w-xs"}>
              <option value="">All vendors</option>
              {vendors.map((v) => <option key={v.id} value={v.id}>{v.company_name || v.person_name}</option>)}
            </select>
            {voVendorFilter && <button type="button" onClick={() => { setVoVendorFilter(""); setSelVo(null); }} className="text-xs text-slate-400 hover:text-slate-600">✕ Clear</button>}
          </div>

          {filteredVOs.length === 0 && (
            <div className="rounded-xl border-2 border-dashed border-slate-200 py-12 text-center text-slate-400">
              <div className="text-3xl">📋</div>
              <div className="mt-2 font-medium">No open vendor orders{voVendorFilter ? " for this vendor" : ""}</div>
            </div>
          )}

          {filteredVOs.length > 0 && !selVo && (
            <div className="space-y-2">
              <p className="text-sm text-slate-500">Select an order to receive goods:</p>
              {filteredVOs.map((vo) => {
                const pending = vo.items.filter((it) => it.qty_ordered - it.qty_received > 0);
                return (
                  <div key={vo.id} onClick={() => selectVo(vo)}
                    className="cursor-pointer rounded-xl border border-slate-200 bg-white p-4 hover:border-blue-400 hover:shadow-sm transition">
                    <div className="flex items-center justify-between">
                      <div>
                        <span className="font-semibold text-slate-800">{vo.vendor_name ?? `Vendor #${vo.vendor_id}`}</span>
                        <span className="ml-2 text-xs text-slate-400">VO-{vo.id}</span>
                      </div>
                      <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-700">{pending.length} items pending</span>
                    </div>
                    <div className="mt-1 text-xs text-slate-500">
                      {pending.map((it) => `${it.product_name}: ${it.qty_ordered - it.qty_received} pending`).join(" · ")}
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {selVo && (
            <form onSubmit={receiveFromVo} className="space-y-4">
              <div className="flex items-center gap-3">
                <button type="button" onClick={() => setSelVo(null)} className="text-sm text-blue-600 hover:underline">← Back to orders</button>
                <span className="font-semibold text-slate-800">{selVo.vendor_name} — VO-{selVo.id}</span>
              </div>

              <div>
                <label className={LABEL}>Receipt date</label>
                <input type="date" value={voDate} onChange={(e) => setVoDate(e.target.value)} className={INPUT + " max-w-xs"} />
              </div>

              <div className="overflow-hidden rounded-xl border border-slate-200">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-200 bg-slate-50 text-xs font-semibold uppercase text-slate-500">
                      <th className="px-3 py-2 text-left">Product</th>
                      <th className="px-3 py-2 text-right">Ordered</th>
                      <th className="px-3 py-2 text-right">Received so far</th>
                      <th className="px-3 py-2 text-right">Pending</th>
                      <th className="px-3 py-2 text-right">Receive now</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {selVo.items.filter((it) => it.qty_ordered - it.qty_received > 0).map((it) => (
                      <tr key={it.line_id}>
                        <td className="px-3 py-2 font-medium text-slate-800">{it.product_name}</td>
                        <td className="px-3 py-2 text-right tabular-nums">{it.qty_ordered}</td>
                        <td className="px-3 py-2 text-right tabular-nums text-emerald-700">{it.qty_received}</td>
                        <td className="px-3 py-2 text-right tabular-nums font-semibold text-amber-700">{it.qty_ordered - it.qty_received}</td>
                        <td className="px-3 py-2 text-right">
                          <input type="number" min="0"
                            value={voRecvQty[it.line_id] ?? ""}
                            onChange={(e) => setVoRecvQty((p) => ({ ...p, [it.line_id]: e.target.value }))}
                            className="w-24 rounded border border-slate-300 px-2 py-1 text-right text-sm"
                            title="Can enter more than pending (over-delivery allowed)" />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 space-y-3">
                <h5 className="text-xs font-bold text-amber-800 uppercase tracking-wide">Vendor Bill (mandatory — bill comes with goods)</h5>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className={LABEL}>Vendor Bill Number *</label>
                    <input value={voBillNum} onChange={(e) => setVoBillNum(e.target.value)} placeholder="e.g. VB-2024-001" className={INPUT} required />
                  </div>
                  <div>
                    <label className={LABEL}>Vendor Bill Amount ₹ *</label>
                    <input type="number" step="0.01" value={voBillAmt} onChange={(e) => setVoBillAmt(e.target.value)} placeholder="Total as per vendor invoice" className={INPUT} required />
                  </div>
                </div>
              </div>
              <div className="flex gap-2">
                <button type="submit" disabled={voSaving} className={BTN_PRIMARY}>{voSaving ? "Saving…" : "✓ Add Stock + Create AP"}</button>
                <button type="button" onClick={() => { setSelVo(null); setVoBillNum(""); setVoBillAmt(""); }} className={BTN_SECONDARY}>Cancel</button>
              </div>
            </form>
          )}
        </div>
      )}

      {mode === "manual" && (
        <form onSubmit={manualReceive} className="max-w-xl space-y-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <p className="text-xs text-slate-500">Adds stock immediately and auto-creates a vendor order (status: created manually).</p>
          <div>
            <label className={LABEL}>Vendor *</label>
            <select value={manualVendorId} onChange={(e) => { setManualVendorId(e.target.value); setManualRows([{ cid: "", qty: "" }]); }} className={INPUT} required>
              <option value="">— select vendor —</option>
              {vendors.map((v) => <option key={v.id} value={v.id}>{v.company_name || v.person_name}</option>)}
            </select>
          </div>

          {manualVendorId && (
            <div>
              <label className={LABEL}>Products * ({manualVendorProducts.length} from this vendor)</label>
              <div className="space-y-2">
                {manualRows.map((row, idx) => (
                  <div key={idx} className="flex items-center gap-2">
                    <select
                      value={row.cid}
                      onChange={(e) => {
                        const updated = manualRows.map((r, i) => i === idx ? { ...r, cid: e.target.value } : r);
                        if (idx === manualRows.length - 1 && e.target.value) updated.push({ cid: "", qty: "" });
                        setManualRows(updated);
                      }}
                      className="flex-1 rounded-lg border border-slate-300 px-2 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
                    >
                      <option value="">— select product —</option>
                      {manualVendorProducts.map((p) => <option key={p.id} value={p.id}>{p.our_product_id}</option>)}
                    </select>
                    <input
                      type="number" min="1" placeholder="Qty"
                      value={row.qty}
                      onChange={(e) => setManualRows(manualRows.map((r, i) => i === idx ? { ...r, qty: e.target.value } : r))}
                      className="w-20 rounded-lg border border-slate-300 px-2 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
                    />
                    {manualRows.length > 1 && (
                      <button type="button" onClick={() => setManualRows(manualRows.filter((_, i) => i !== idx))}
                        className="text-red-400 hover:text-red-600 text-xs px-1">✕</button>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          <div>
            <label className={LABEL}>Notes</label>
            <input value={manualNotes} onChange={(e) => setManualNotes(e.target.value)} className={INPUT} placeholder="e.g. Direct purchase, urgent restock" />
          </div>
          <button type="submit" disabled={manualSaving} className={BTN_PRIMARY}>
            {manualSaving ? "Saving…" : "Add to stock + create vendor order"}
          </button>
        </form>
      )}
    </div>
  );
}
