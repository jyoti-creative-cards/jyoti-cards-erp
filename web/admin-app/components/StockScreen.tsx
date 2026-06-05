"use client";

import { useCallback, useEffect, useState } from "react";
import { Drawer } from "@/components/Drawer";
import { apiUrl, fetchApi, formatApiError } from "@/lib/api";
import type { CatalogProductPublic, InventoryRowPublic, PurchaseOrderPublic, StockAdjustmentPublic, VendorPublic } from "@/lib/types";

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
  invoice_count: number;
  months: LedgerMonthSummary[];
}

const INPUT = "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500";
const LABEL = "mb-1 block text-xs font-semibold text-slate-500 uppercase tracking-wider";
const BTN_PRIMARY = "inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-700 disabled:opacity-50";
const BTN_SECONDARY = "inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm transition hover:bg-slate-50";

function stockBadge(status: string) {
  if (status === "out_of_stock") return <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">Out of stock</span>;
  if (status === "low_stock") return <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">Low stock</span>;
  return <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700">In stock</span>;
}

interface Props {
  adminKey: string;
}

export function StockScreen({ adminKey }: Props) {
  const [tab, setTab] = useState<"current" | "receive" | "adjustments">("current");

  const headers = () => {
    const h: Record<string, string> = { "Content-Type": "application/json" };
    if (adminKey.trim()) h["X-Admin-Key"] = adminKey.trim();
    return h;
  };
  const headersAdmin = (): Record<string, string> => adminKey.trim() ? { "X-Admin-Key": adminKey.trim() } : {};

  const [rows, setRows] = useState<InventoryRowPublic[]>([]);
  const [catalog, setCatalog] = useState<CatalogProductPublic[]>([]);
  const [vendors, setVendors] = useState<VendorPublic[]>([]);
  const [pos, setPos] = useState<PurchaseOrderPublic[]>([]);

  const loadAll = useCallback(async () => {
    if (!adminKey.trim()) return;
    const [ir, cr, vr, pr] = await Promise.all([
      fetchApi(apiUrl("inventory") + "?all_catalog=true", { headers: headersAdmin() }),
      fetchApi(apiUrl("catalog"), { headers: headersAdmin() }),
      fetchApi(apiUrl("vendors"), { headers: headersAdmin() }),
      fetchApi(apiUrl("purchase-orders"), { headers: headersAdmin() }),
    ]);
    if (ir.ok) setRows(await ir.json());
    if (cr.ok) setCatalog(await cr.json());
    if (vr.ok) setVendors(await vr.json());
    if (pr.ok) setPos(await pr.json());
  }, [adminKey]);

  useEffect(() => { void loadAll(); }, [loadAll]);

  const vendorName = (id: number) => {
    const v = vendors.find((v) => v.id === id);
    return v?.company_name || v?.person_name || `#${id}`;
  };

  return (
    <div>
      <div className="mb-6 flex gap-2">
        {([
          { id: "current",     label: "📊 Current stock" },
          { id: "receive",     label: "📥 Receive goods" },
          { id: "adjustments", label: "✏️ Adjustments log" },
        ] as const).map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={`rounded-full px-5 py-2 text-sm font-semibold transition ${
              tab === t.id ? "bg-blue-600 text-white shadow" : "bg-white text-slate-600 shadow-sm hover:bg-slate-50"
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
        />
      )}
      {tab === "receive" && (
        <ReceiveGoodsTab
          catalog={catalog}
          pos={pos}
          vendors={vendors}
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
}: {
  rows: InventoryRowPublic[];
  catalog: CatalogProductPublic[];
  vendorName: (id: number) => string;
  vendors: VendorPublic[];
  headers: () => Record<string, string>;
  headersAdmin: () => Record<string, string>;
  adminKey: string;
  onRefresh: () => void;
}) {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [vendorFilter, setVendorFilter] = useState("");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerRow, setDrawerRow] = useState<InventoryRowPublic | null>(null);
  const [ledgerRow, setLedgerRow] = useState<InventoryRowPublic | null>(null);
  const [ledgerOpen, setLedgerOpen] = useState(false);
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null);
  // Inline qty edit
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editQty, setEditQty] = useState("");
  // Threshold drafts
  const [threshDraft, setThreshDraft] = useState<Record<number, string>>({});

  const showToast = (msg: string, ok: boolean) => { setToast({ msg, ok }); setTimeout(() => setToast(null), 3500); };

  const filtered = rows.filter((r) => {
    const q = search.toLowerCase();
    const matchSearch = !q || r.name.toLowerCase().includes(q) || r.our_product_id.toLowerCase().includes(q) || r.category.toLowerCase().includes(q);
    const matchStatus = !statusFilter || r.stock_status === statusFilter;
    const matchVendor = !vendorFilter || String(r.vendor_id) === vendorFilter;
    return matchSearch && matchStatus && matchVendor;
  });

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
      <div className="mb-4 grid grid-cols-3 gap-3">
        {[
          { label: "In stock",     key: "in_stock",     count: rows.filter((r) => r.stock_status === "in_stock").length,     color: "bg-emerald-50 text-emerald-700 border-emerald-200" },
          { label: "Low stock",    key: "low_stock",    count: rows.filter((r) => r.stock_status === "low_stock").length,    color: "bg-amber-50 text-amber-700 border-amber-200" },
          { label: "Out of stock", key: "out_of_stock", count: rows.filter((r) => r.stock_status === "out_of_stock").length, color: "bg-red-50 text-red-700 border-red-200" },
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
          <div className="text-4xl">🏪</div>
          <div className="mt-2 font-medium">No stock items found</div>
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-xs font-semibold uppercase text-slate-500">
                <th className="px-4 py-3 text-left">Product</th>
                <th className="px-4 py-3 text-left">Category</th>
                <th className="px-4 py-3 text-right">Invoices</th>
                <th className="px-4 py-3 text-right">Sell ₹</th>
                <th className="px-4 py-3 text-right">Qty</th>
                <th className="px-4 py-3 text-left">Status</th>
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
                        className="cursor-pointer font-medium text-blue-700 hover:underline"
                        onClick={() => { setDrawerRow(row); setDrawerOpen(true); }}
                      >
                        {row.name}
                      </div>
                      <div className="text-xs font-mono text-slate-400">{row.our_product_id}</div>
                    </td>
                    <td className="px-4 py-3 text-slate-500">{row.category}</td>
                    <td className="px-4 py-3 text-right text-slate-600">{row.invoice_count ?? "—"}</td>
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
                    <td className="px-4 py-3">{stockBadge(row.stock_status)}</td>
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
                <div className="text-lg font-bold">{stockBadge(drawerRow.stock_status)}</div>
                <div className="text-xs text-slate-500 mt-1">Status</div>
              </div>
            </div>
            <div className="text-sm text-slate-500">
              <p><span className="font-medium text-slate-700">Vendor:</span> {vendorName(drawerRow.vendor_id)}</p>
              <p><span className="font-medium text-slate-700">Low threshold:</span> {drawerRow.low_stock_threshold ?? 0}</p>
            </div>
          </div>
        )}
      </Drawer>
    </div>
  );
}

// ────────────────────────── LEDGER MODAL ──────────────────────────

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

  return (
    <div
      style={{ position: "fixed", inset: 0, zIndex: 60, display: "flex", alignItems: "center", justifyContent: "center", background: "rgba(0,0,0,0.45)" }}
      onClick={onClose}
    >
      <div
        style={{ background: "#fff", borderRadius: 16, width: "min(780px, 95vw)", maxHeight: "90vh", display: "flex", flexDirection: "column", overflow: "hidden", boxShadow: "0 25px 50px rgba(0,0,0,0.25)" }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div style={{ padding: "20px 24px 16px", borderBottom: "1px solid #e2e8f0", display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
          <div>
            <div style={{ fontSize: 17, fontWeight: 700, color: "#0f172a" }}>{row.name}</div>
            <div style={{ fontSize: 12, color: "#64748b", marginTop: 2 }}>
              {row.our_product_id} · Stock: <strong>{data?.current_stock ?? row.quantity}</strong>
              {data?.invoice_count != null && <> · Invoices: <strong>{data.invoice_count}</strong></>}
            </div>
          </div>
          <button type="button" onClick={onClose} style={{ fontSize: 20, lineHeight: 1, background: "none", border: "none", cursor: "pointer", color: "#94a3b8", padding: "2px 6px" }}>✕</button>
        </div>

        {/* Body */}
        <div style={{ overflowY: "auto", flex: 1, padding: "16px 24px" }}>
          {loading && <div style={{ textAlign: "center", padding: "48px 0", color: "#94a3b8" }}>Loading…</div>}
          {error && <div style={{ textAlign: "center", padding: "48px 0", color: "#ef4444" }}>{error}</div>}
          {data && !loading && (
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ background: "#f8fafc", borderBottom: "1px solid #e2e8f0" }}>
                  <th style={{ padding: "8px 12px", textAlign: "left", fontSize: 11, fontWeight: 600, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.05em" }}>Month</th>
                  <th style={{ padding: "8px 12px", textAlign: "right", fontSize: 11, fontWeight: 600, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.05em" }}>Opening</th>
                  <th style={{ padding: "8px 12px", textAlign: "right", fontSize: 11, fontWeight: 600, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.05em" }}>Inward</th>
                  <th style={{ padding: "8px 12px", textAlign: "right", fontSize: 11, fontWeight: 600, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.05em" }}>Outward</th>
                  <th style={{ padding: "8px 12px", textAlign: "right", fontSize: 11, fontWeight: 600, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.05em" }}>Closing</th>
                  <th style={{ padding: "8px 12px", width: 32 }} />
                </tr>
              </thead>
              <tbody>
                {data.months.map((m) => {
                  const key = `${m.year}-${m.month}`;
                  const expanded = expandedMonths.has(key);
                  return (
                    <>
                      <tr
                        key={key}
                        style={{ borderBottom: "1px solid #f1f5f9", cursor: "pointer", background: expanded ? "#eff6ff" : undefined }}
                        onClick={() => toggleMonth(key)}
                      >
                        <td style={{ padding: "9px 12px", fontWeight: 600, color: "#1e293b" }}>{m.month_label}</td>
                        <td style={{ padding: "9px 12px", textAlign: "right", color: "#475569" }}>{m.opening}</td>
                        <td style={{ padding: "9px 12px", textAlign: "right", color: "#16a34a", fontWeight: 600 }}>{m.inward > 0 ? `+${m.inward}` : m.inward}</td>
                        <td style={{ padding: "9px 12px", textAlign: "right", color: "#dc2626", fontWeight: 600 }}>{m.outward > 0 ? `-${m.outward}` : m.outward}</td>
                        <td style={{ padding: "9px 12px", textAlign: "right", fontWeight: 700, color: "#0f172a" }}>{m.closing}</td>
                        <td style={{ padding: "9px 12px", textAlign: "center", color: "#94a3b8", fontSize: 11 }}>{expanded ? "▲" : "▼"}</td>
                      </tr>
                      {expanded && m.entries.map((en, i) => (
                        <tr key={i} style={{ background: "#f8fafc", borderBottom: "1px solid #f1f5f9" }}>
                          <td style={{ padding: "6px 12px 6px 24px", color: "#64748b" }}>{en.date}</td>
                          <td colSpan={2} style={{ padding: "6px 12px", color: "#475569" }}>
                            <span style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", color: en.type === "inward" ? "#16a34a" : en.type === "outward" ? "#dc2626" : "#7c3aed", marginRight: 6 }}>{en.type}</span>
                            {en.party && <span style={{ marginRight: 6 }}>{en.party}</span>}
                            <span style={{ color: "#94a3b8", fontSize: 12 }}>{en.reference}</span>
                          </td>
                          <td style={{ padding: "6px 12px", textAlign: "right", fontWeight: 700, color: en.type === "inward" ? "#16a34a" : en.type === "outward" ? "#dc2626" : "#475569" }}>
                            {en.type === "inward" ? `+${en.qty}` : en.type === "outward" ? `-${en.qty}` : en.qty}
                          </td>
                          <td style={{ padding: "6px 12px", textAlign: "right", color: "#0f172a", fontWeight: 600 }}>{en.running_balance}</td>
                          <td />
                        </tr>
                      ))}
                    </>
                  );
                })}
                {data.months.length === 0 && (
                  <tr><td colSpan={6} style={{ padding: "48px 0", textAlign: "center", color: "#94a3b8" }}>No ledger entries yet.</td></tr>
                )}
              </tbody>
            </table>
          )}
        </div>
      </div>
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

interface VendorPendingItem {
  po_id: number;
  po_date: string | null;
  catalog_product_id: number;
  product_name: string;
  ordered_qty: number;
  received_qty: number;
  pending_qty: number;
  unit_price: number;
  pending_value: number;
}

interface VendorPendingResponse {
  vendor_id: number;
  vendor_name: string;
  pending_items: VendorPendingItem[];
  total_pending_value: number;
  total_owed: number;
  open_po_count: number;
}

function ReceiveGoodsTab({
  catalog,
  pos,
  vendors,
  headers,
  headersAdmin,
  adminKey,
  onRefresh,
}: {
  catalog: CatalogProductPublic[];
  pos: PurchaseOrderPublic[];
  vendors: VendorPublic[];
  headers: () => Record<string, string>;
  headersAdmin: () => Record<string, string>;
  adminKey: string;
  onRefresh: () => void;
}) {
  const [mode, setMode] = useState<"vendor" | "po" | "manual">("vendor");

  // Vendor receive state
  const [selVendorId, setSelVendorId] = useState("");
  const [vendorPending, setVendorPending] = useState<VendorPendingResponse | null>(null);
  const [vendorPendingLoading, setVendorPendingLoading] = useState(false);
  const [vendorRecvQty, setVendorRecvQty] = useState<Record<number, string>>({});
  const [vendorUnitPrice, setVendorUnitPrice] = useState<Record<number, string>>({});
  const [vendorExtraCharges, setVendorExtraCharges] = useState("");
  const [vendorNotes, setVendorNotes] = useState("");
  const [vendorBillFile, setVendorBillFile] = useState<File | null>(null);
  const [vendorSaving, setVendorSaving] = useState(false);
  const [vendorAdHocItems, setVendorAdHocItems] = useState<{ cid: string; qty: string; price: string }[]>([]);

  useEffect(() => {
    if (!selVendorId) { setVendorPending(null); return; }
    setVendorPendingLoading(true);
    fetchApi(apiUrl(`purchase-orders/vendor/${selVendorId}/pending`), { headers: headersAdmin() })
      .then((r) => r.json())
      .then((data: VendorPendingResponse) => {
        setVendorPending(data);
        const qty: Record<number, string> = {};
        const price: Record<number, string> = {};
        (data.pending_items || []).forEach((it) => {
          qty[it.catalog_product_id] = String(it.pending_qty);
          price[it.catalog_product_id] = String(it.unit_price || "");
        });
        setVendorRecvQty(qty);
        setVendorUnitPrice(price);
      })
      .catch(() => setVendorPending(null))
      .finally(() => setVendorPendingLoading(false));
  }, [selVendorId, headersAdmin]);

  async function receiveFromVendor(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!selVendorId) return;
    setVendorSaving(true);

    const items: { catalog_product_id: number; quantity: number; unit_price: number }[] = [];

    // Items from pending POs
    (vendorPending?.pending_items || []).forEach((it) => {
      const qty = Number(vendorRecvQty[it.catalog_product_id] || 0);
      if (qty > 0) {
        items.push({ catalog_product_id: it.catalog_product_id, quantity: qty, unit_price: Number(vendorUnitPrice[it.catalog_product_id] || it.unit_price || 0) });
      }
    });

    // Ad-hoc items
    vendorAdHocItems.forEach((row) => {
      const cid = Number(row.cid);
      const qty = Number(row.qty);
      if (cid > 0 && qty > 0) {
        items.push({ catalog_product_id: cid, quantity: qty, unit_price: Number(row.price || 0) });
      }
    });

    if (items.length === 0) { showToast("No items to receive", false); setVendorSaving(false); return; }

    const fd = new FormData();
    fd.append("vendor_id", selVendorId);
    fd.append("items", JSON.stringify(items));
    fd.append("extra_charges", vendorExtraCharges || "0");
    if (vendorNotes.trim()) fd.append("notes", vendorNotes.trim());
    if (vendorBillFile) fd.append("bill_photo", vendorBillFile);

    const r = await fetchApi(apiUrl("inventory/receipts/from-vendor"), { method: "POST", headers: headersAdmin(), body: fd });
    const data = await r.json().catch(() => ({}));
    setVendorSaving(false);
    if (!r.ok) { showToast(formatApiError(data) || "Failed", false); return; }
    showToast(`Goods received! ${(data as { items_received?: number }).items_received ?? items.length} item(s) added to stock.`, true);
    setSelVendorId(""); setVendorPending(null); setVendorRecvQty({}); setVendorUnitPrice({}); setVendorExtraCharges(""); setVendorNotes(""); setVendorBillFile(null); setVendorAdHocItems([]);
    onRefresh();
  }

  const [selPoId, setSelPoId] = useState("");
  const [selPo, setSelPo] = useState<PurchaseOrderPublic | null>(null);
  const [recvQty, setRecvQty] = useState<Record<number, string>>({});
  const [receiptNo, setReceiptNo] = useState("");
  const [vendorBillNo, setVendorBillNo] = useState("");
  const [billPhoto, setBillPhoto] = useState<File | null>(null);
  const [contactNo, setContactNo] = useState("");
  const [notes, setNotes] = useState("");
  const [partial, setPartial] = useState(false);
  const [forceClose, setForceClose] = useState(false);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null);

  const showToast = (msg: string, ok: boolean) => { setToast({ msg, ok }); setTimeout(() => setToast(null), 3500); };

  useEffect(() => {
    if (!selPoId) { setSelPo(null); return; }
    const po = pos.find((p) => String(p.id) === selPoId);
    setSelPo(po ?? null);
    if (po) {
      const init: Record<number, string> = {};
      po.items.forEach((it) => { init[it.catalog_product_id] = String(it.quantity_pending ?? it.quantity); });
      setRecvQty(init);
    }
  }, [selPoId, pos]);

  async function receiveFromPo(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!selPo) return;
    setSaving(true);
    const lines = selPo.items.map((it) => ({
      catalog_product_id: it.catalog_product_id,
      quantity: Number(recvQty[it.catalog_product_id] ?? 0),
    })).filter((l) => l.quantity > 0);
    const fd = new FormData();
    fd.append("purchase_order_id", String(selPo.id));
    fd.append("lines", JSON.stringify(lines));
    fd.append("is_partial", partial ? "true" : "false");
    if (receiptNo) fd.append("receipt_number", receiptNo);
    if (vendorBillNo.trim()) fd.append("vendor_bill_no", vendorBillNo.trim());
    if (contactNo) fd.append("contact_number", contactNo);
    if (notes) fd.append("notes", notes);
    if (forceClose) fd.append("force_close", "true");
    if (billPhoto) fd.append("bill_photo", billPhoto);
    const r = await fetchApi(apiUrl("inventory/receipts/from-po"), { method: "POST", headers: headersAdmin(), body: fd });
    const data = await r.json().catch(() => ({}));
    setSaving(false);
    if (!r.ok) { showToast(formatApiError(data), false); return; }
    showToast("Goods received.", true);
    setSelPoId(""); setSelPo(null); setReceiptNo(""); setVendorBillNo(""); setBillPhoto(null); setContactNo(""); setNotes(""); setPartial(false); setForceClose(false);
    onRefresh();
  }

  async function manualReceive(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setSaving(true);
    const fd = new FormData(e.currentTarget);
    const body = {
      catalog_product_id: Number(fd.get("catalog_product_id")),
      quantity_delta: Number(fd.get("quantity")),
      reason: `Manual receive: ${fd.get("reason") || "goods in"}`,
    };
    const r = await fetchApi(apiUrl("inventory/adjustments"), { method: "POST", headers: headers(), body: JSON.stringify(body) });
    const data = await r.json().catch(() => ({}));
    setSaving(false);
    if (!r.ok) { showToast(formatApiError(data), false); return; }
    showToast("Stock added.", true);
    (e.target as HTMLFormElement).reset();
    onRefresh();
  }

  const openPos = pos.filter((p) => p.status === "booked" || p.status === "in_progress");

  return (
    <div>
      {toast && (
        <div className={`fixed right-4 top-20 z-50 rounded-lg px-4 py-3 text-sm font-medium shadow-lg ${toast.ok ? "bg-emerald-600 text-white" : "bg-red-600 text-white"}`}>
          {toast.msg}
        </div>
      )}

      <div className="mb-4 flex flex-wrap gap-2">
        {[
          { id: "vendor", label: "📦 Receive from Vendor" },
          { id: "po", label: "Receive against PO" },
          { id: "manual", label: "Ad-hoc / Manual" },
        ].map((m) => (
          <button key={m.id} type="button" onClick={() => setMode(m.id as "vendor" | "po" | "manual")}
            className={`rounded-lg px-4 py-2 text-sm font-semibold ${mode === m.id ? "bg-blue-600 text-white" : "border border-slate-300 bg-white text-slate-700 hover:bg-slate-50"}`}>
            {m.label}
          </button>
        ))}
      </div>

      {mode === "vendor" && (
        <div className="space-y-4">
          <div>
            <label className={LABEL}>Select vendor</label>
            <select value={selVendorId} onChange={(e) => setSelVendorId(e.target.value)} className={INPUT + " max-w-sm"}>
              <option value="">— select vendor —</option>
              {vendors.map((v) => <option key={v.id} value={v.id}>{v.company_name || v.person_name}</option>)}
            </select>
          </div>

          {vendorPendingLoading && <p className="text-sm text-slate-500">Loading pending items…</p>}

          {vendorPending && (
            <form onSubmit={receiveFromVendor} className="space-y-4">
              {/* Vendor status summary */}
              <div className="flex flex-wrap gap-4 rounded-xl border border-blue-200 bg-blue-50 p-3 text-sm">
                <span><strong>{vendorPending.open_po_count}</strong> open POs</span>
                <span><strong>₹{vendorPending.total_pending_value.toFixed(2)}</strong> pending value</span>
                <span><strong>₹{vendorPending.total_owed.toFixed(2)}</strong> owed to vendor</span>
              </div>

              {/* Pending items from POs */}
              {vendorPending.pending_items.length > 0 && (
                <div>
                  <p className={LABEL}>Pending items from open POs</p>
                  <div className="overflow-hidden rounded-xl border border-slate-200">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-slate-200 bg-slate-50 text-xs font-semibold uppercase text-slate-500">
                          <th className="px-3 py-2 text-left">Product</th>
                          <th className="px-3 py-2 text-left">PO #</th>
                          <th className="px-3 py-2 text-left">PO Date</th>
                          <th className="px-3 py-2 text-right">Pending</th>
                          <th className="px-3 py-2 text-right">Unit Price</th>
                          <th className="px-3 py-2 text-right">Receive Qty</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {vendorPending.pending_items.map((it) => (
                          <tr key={`${it.po_id}-${it.catalog_product_id}`}>
                            <td className="px-3 py-2 font-medium">{it.product_name}</td>
                            <td className="px-3 py-2 text-slate-500">PO #{it.po_id}</td>
                            <td className="px-3 py-2 text-slate-500 text-xs">{it.po_date ? new Date(it.po_date).toLocaleDateString() : "—"}</td>
                            <td className="px-3 py-2 text-right tabular-nums">{it.pending_qty}</td>
                            <td className="px-3 py-2 text-right">
                              <input type="number" min="0" step="0.01"
                                value={vendorUnitPrice[it.catalog_product_id] ?? ""}
                                onChange={(e) => setVendorUnitPrice((p) => ({ ...p, [it.catalog_product_id]: e.target.value }))}
                                className="w-24 rounded border border-slate-300 px-2 py-1 text-right text-sm" />
                            </td>
                            <td className="px-3 py-2 text-right">
                              <input type="number" min="0"
                                value={vendorRecvQty[it.catalog_product_id] ?? ""}
                                onChange={(e) => setVendorRecvQty((p) => ({ ...p, [it.catalog_product_id]: e.target.value }))}
                                className="w-20 rounded border border-slate-300 px-2 py-1 text-right text-sm" />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Ad-hoc items not in any PO */}
              <div>
                <div className="flex items-center justify-between">
                  <p className={LABEL}>Extra items (not in any PO)</p>
                  <button type="button" onClick={() => setVendorAdHocItems((p) => [...p, { cid: "", qty: "", price: "" }])}
                    className={BTN_SECONDARY + " text-xs"}>+ Add item</button>
                </div>
                {vendorAdHocItems.map((row, idx) => (
                  <div key={idx} className="mt-2 flex flex-wrap gap-2">
                    <select value={row.cid} onChange={(e) => setVendorAdHocItems((p) => p.map((r, i) => i === idx ? { ...r, cid: e.target.value } : r))}
                      className={INPUT + " max-w-[200px]"}>
                      <option value="">— product —</option>
                      {catalog.map((c) => <option key={c.id} value={c.id}>{c.our_product_id}</option>)}
                    </select>
                    <input type="number" min="1" placeholder="Qty" value={row.qty}
                      onChange={(e) => setVendorAdHocItems((p) => p.map((r, i) => i === idx ? { ...r, qty: e.target.value } : r))}
                      className="w-24 rounded border border-slate-300 px-2 py-1 text-sm" />
                    <input type="number" min="0" step="0.01" placeholder="Unit price" value={row.price}
                      onChange={(e) => setVendorAdHocItems((p) => p.map((r, i) => i === idx ? { ...r, price: e.target.value } : r))}
                      className="w-28 rounded border border-slate-300 px-2 py-1 text-sm" />
                    <button type="button" onClick={() => setVendorAdHocItems((p) => p.filter((_, i) => i !== idx))}
                      className="text-xs font-semibold text-red-600 hover:underline">Remove</button>
                  </div>
                ))}
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className={LABEL}>Extra charges (transport, etc.)</label>
                  <input type="number" min="0" step="0.01" value={vendorExtraCharges}
                    onChange={(e) => setVendorExtraCharges(e.target.value)} placeholder="0.00" className={INPUT} />
                </div>
                <div>
                  <label className={LABEL}>Notes</label>
                  <input value={vendorNotes} onChange={(e) => setVendorNotes(e.target.value)} className={INPUT} />
                </div>
                <div className="col-span-2">
                  <label className={LABEL}>Upload vendor bill (optional)</label>
                  <input type="file" accept="image/*,.pdf" onChange={(e) => setVendorBillFile(e.target.files?.[0] ?? null)}
                    className="block w-full text-sm text-slate-500 file:mr-3 file:rounded-lg file:border-0 file:bg-slate-100 file:px-3 file:py-1.5 file:text-sm file:font-semibold hover:file:bg-slate-200" />
                </div>
              </div>

              <button type="submit" disabled={vendorSaving} className={BTN_PRIMARY}>
                {vendorSaving ? "Adding stock…" : "Add Stock"}
              </button>
            </form>
          )}

          {selVendorId && !vendorPendingLoading && vendorPending && vendorPending.pending_items.length === 0 && vendorAdHocItems.length === 0 && (
            <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 p-6 text-center text-sm text-slate-500">
              No pending PO items for this vendor. Use "+ Add item" above to receive goods not tied to a PO.
              <button type="button" onClick={() => setVendorAdHocItems([{ cid: "", qty: "", price: "" }])} className={BTN_PRIMARY + " mt-3 mx-auto"}>+ Add item</button>
            </div>
          )}
        </div>
      )}

      {mode === "po" && (
        <div className="space-y-4">
          <div>
            <label className={LABEL}>Select open purchase order</label>
            <select value={selPoId} onChange={(e) => setSelPoId(e.target.value)} className={INPUT + " max-w-sm"}>
              <option value="">— select PO —</option>
              {openPos.map((p) => {
                const v = vendors.find((vv) => vv.id === p.vendor_id);
                const vname = v?.company_name || v?.person_name || `Vendor #${p.vendor_id}`;
                return <option key={p.id} value={p.id}>PO #{p.id} — {vname} ({p.status})</option>;
              })}
            </select>
          </div>

          {selPo && (
            <form onSubmit={receiveFromPo} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div><label className={LABEL}>Vendor Bill No.</label><input value={vendorBillNo} onChange={(e) => setVendorBillNo(e.target.value)} placeholder="Bill number on vendor's paper" className={INPUT} /></div>
                <div><label className={LABEL}>Receipt number</label><input value={receiptNo} onChange={(e) => setReceiptNo(e.target.value)} className={INPUT} /></div>
                <div><label className={LABEL}>Contact number</label><input value={contactNo} onChange={(e) => setContactNo(e.target.value)} className={INPUT} /></div>
                <div><label className={LABEL}>Notes</label><input value={notes} onChange={(e) => setNotes(e.target.value)} className={INPUT} /></div>
                <div className="col-span-2">
                  <label className={LABEL}>Bill photo (optional)</label>
                  <input type="file" accept="image/*,.pdf" onChange={(e) => setBillPhoto(e.target.files?.[0] ?? null)} className="block w-full text-sm text-slate-500 file:mr-3 file:rounded-lg file:border-0 file:bg-slate-100 file:px-3 file:py-1.5 file:text-sm file:font-semibold hover:file:bg-slate-200" />
                </div>
              </div>

              <div className="overflow-hidden rounded-xl border border-slate-200">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-200 bg-slate-50 text-xs font-semibold uppercase text-slate-500">
                      <th className="px-3 py-2 text-left">Product</th>
                      <th className="px-3 py-2 text-right">Ordered</th>
                      <th className="px-3 py-2 text-right">Receive qty</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {selPo.items.map((it) => {
                      const entered = Number(recvQty[it.catalog_product_id] ?? 0);
                      const overDelivery = entered > it.quantity;
                      return (
                        <tr key={it.catalog_product_id}>
                          <td className="px-3 py-2 font-medium">{it.name}</td>
                          <td className="px-3 py-2 text-right">{it.quantity}</td>
                          <td className="px-3 py-2 text-right">
                            <div className="flex items-center justify-end gap-2">
                              <input type="number" min="0"
                                value={recvQty[it.catalog_product_id] ?? ""}
                                onChange={(e) => setRecvQty((p) => ({ ...p, [it.catalog_product_id]: e.target.value }))}
                                className="w-20 rounded border border-slate-300 px-2 py-1 text-right text-sm" />
                              {overDelivery && (
                                <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-700">Over-delivery</span>
                              )}
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              <div className="flex flex-wrap items-center gap-4">
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={partial} onChange={(e) => setPartial(e.target.checked)} className="h-4 w-4 rounded" />
                  Partial delivery
                </label>
                <label className="flex items-center gap-2 text-sm text-amber-700">
                  <input type="checkbox" checked={forceClose} onChange={(e) => setForceClose(e.target.checked)} className="h-4 w-4 rounded" />
                  Force close this PO after receipt
                </label>
                <button type="submit" disabled={saving} className={BTN_PRIMARY}>
                  {saving ? "Saving…" : "Confirm receipt"}
                </button>
              </div>
            </form>
          )}
        </div>
      )}

      {mode === "manual" && (
        <form onSubmit={manualReceive} className="max-w-md space-y-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div>
            <label className={LABEL}>Product *</label>
            <select name="catalog_product_id" required className={INPUT}>
              <option value="">— select product —</option>
              {catalog.map((p) => <option key={p.id} value={p.id}>{p.our_product_id} — {p.name}</option>)}
            </select>
          </div>
          <div>
            <label className={LABEL}>Quantity to add *</label>
            <input name="quantity" type="number" required min="1" className={INPUT} />
          </div>
          <div>
            <label className={LABEL}>Reason / note</label>
            <input name="reason" className={INPUT} placeholder="e.g. Direct purchase" />
          </div>
          <button type="submit" disabled={saving} className={BTN_PRIMARY}>
            {saving ? "Saving…" : "Add to stock"}
          </button>
        </form>
      )}
    </div>
  );
}
