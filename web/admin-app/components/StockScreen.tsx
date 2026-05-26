"use client";

import { useCallback, useEffect, useState } from "react";
import { Drawer } from "@/components/Drawer";
import { apiUrl, fetchApi, formatApiError } from "@/lib/api";import type { CatalogProductPublic, InventoryRowPublic, PurchaseOrderPublic, StockAdjustmentPublic, VendorPublic } from "@/lib/types";

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
      fetchApi(apiUrl("inventory") + "?allCatalog=true", { headers: headersAdmin() }),
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
          { label: "In stock", count: rows.filter((r) => r.stock_status === "in_stock").length, color: "bg-emerald-50 text-emerald-700 border-emerald-200" },
          { label: "Low stock", count: rows.filter((r) => r.stock_status === "low_stock").length, color: "bg-amber-50 text-amber-700 border-amber-200" },
          { label: "Out of stock", count: rows.filter((r) => r.stock_status === "out_of_stock").length, color: "bg-red-50 text-red-700 border-red-200" },
        ].map((s) => (
          <div key={s.label} className={`cursor-pointer rounded-xl border p-3 text-center transition hover:shadow-sm ${s.color}`}
            onClick={() => setStatusFilter(statusFilter === s.label.toLowerCase().replace(" ", "_") ? "" : s.label.toLowerCase().replace(" ", "_"))}>
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
                <th className="px-4 py-3 text-right">Sell ₹</th>
                <th className="px-4 py-3 text-right">Qty</th>
                <th className="px-4 py-3 text-left">Status</th>
                <th className="px-4 py-3 text-left">Low threshold</th>
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
                    <td className="px-4 py-3 text-right font-medium text-slate-700">
                      {catRow ? `₹${catRow.selling_price}` : "—"}
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

// ────────────────────────── ADJUSTMENTS LOG ──────────────────────────

function AdjustmentsTab({
  catalog,
  headers,
  headersAdmin,
  adminKey,
}: {
  catalog: CatalogProductPublic[];
  headers: () => Record<string, string>;
  headersAdmin: () => Record<string, string>;
  adminKey: string;
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
  pos,
  headers,
  headersAdmin,
  adminKey,
  onRefresh,
}: {
  catalog: CatalogProductPublic[];
  pos: PurchaseOrderPublic[];
  headers: () => Record<string, string>;
  headersAdmin: () => Record<string, string>;
  adminKey: string;
  onRefresh: () => void;
}) {
  const [mode, setMode] = useState<"po" | "manual">("po");
  const [selPoId, setSelPoId] = useState("");
  const [selPo, setSelPo] = useState<PurchaseOrderPublic | null>(null);
  const [recvQty, setRecvQty] = useState<Record<number, string>>({});
  const [receiptNo, setReceiptNo] = useState("");
  const [contactNo, setContactNo] = useState("");
  const [notes, setNotes] = useState("");
  const [partial, setPartial] = useState(false);
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
    if (contactNo) fd.append("contact_number", contactNo);
    if (notes) fd.append("notes", notes);
    const r = await fetchApi(apiUrl("inventory/receipts/from-po"), { method: "POST", headers: headersAdmin(), body: fd });
    const data = await r.json().catch(() => ({}));
    setSaving(false);
    if (!r.ok) { showToast(formatApiError(data), false); return; }
    showToast("Goods received.", true);
    setSelPoId(""); setSelPo(null); setReceiptNo(""); setContactNo(""); setNotes(""); setPartial(false);
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

      <div className="mb-4 flex gap-2">
        {[
          { id: "po", label: "Receive against PO" },
          { id: "manual", label: "Ad-hoc receive" },
        ].map((m) => (
          <button key={m.id} type="button" onClick={() => setMode(m.id as "po" | "manual")}
            className={`rounded-lg px-4 py-2 text-sm font-semibold ${mode === m.id ? "bg-blue-600 text-white" : "border border-slate-300 bg-white text-slate-700 hover:bg-slate-50"}`}>
            {m.label}
          </button>
        ))}
      </div>

      {mode === "po" ? (
        <div className="space-y-4">
          <div>
            <label className={LABEL}>Select open purchase order</label>
            <select value={selPoId} onChange={(e) => setSelPoId(e.target.value)} className={INPUT + " max-w-sm"}>
              <option value="">— select PO —</option>
              {openPos.map((p) => <option key={p.id} value={p.id}>PO #{p.id} — Vendor {p.vendor_id} ({p.status})</option>)}
            </select>
          </div>

          {selPo && (
            <form onSubmit={receiveFromPo} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div><label className={LABEL}>Receipt number</label><input value={receiptNo} onChange={(e) => setReceiptNo(e.target.value)} className={INPUT} /></div>
                <div><label className={LABEL}>Contact number</label><input value={contactNo} onChange={(e) => setContactNo(e.target.value)} className={INPUT} /></div>
                <div className="col-span-2"><label className={LABEL}>Notes</label><input value={notes} onChange={(e) => setNotes(e.target.value)} className={INPUT} /></div>
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
                    {selPo.items.map((it) => (
                      <tr key={it.catalog_product_id}>
                        <td className="px-3 py-2 font-medium">{it.name}</td>
                        <td className="px-3 py-2 text-right">{it.quantity}</td>
                        <td className="px-3 py-2 text-right">
                          <input type="number" min="0" max={it.quantity}
                            value={recvQty[it.catalog_product_id] ?? ""}
                            onChange={(e) => setRecvQty((p) => ({ ...p, [it.catalog_product_id]: e.target.value }))}
                            className="w-20 rounded border border-slate-300 px-2 py-1 text-right text-sm" />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="flex items-center gap-4">
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={partial} onChange={(e) => setPartial(e.target.checked)} className="h-4 w-4 rounded" />
                  Partial delivery
                </label>
                <button type="submit" disabled={saving} className={BTN_PRIMARY}>
                  {saving ? "Saving…" : "Confirm receipt"}
                </button>
              </div>
            </form>
          )}
        </div>
      ) : (
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
