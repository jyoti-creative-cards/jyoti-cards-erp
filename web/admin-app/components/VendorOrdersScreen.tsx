"use client";

import { useCallback, useEffect, useState } from "react";
import { apiUrl, fetchApi, formatApiError } from "@/lib/api";
import type { AuthState } from "@/lib/types";

// ─── types ────────────────────────────────────────────────────────────────────

interface VendorPublic {
  id: number;
  company_name?: string;
  person_name?: string;
  phone?: string;
}

interface OrderLine {
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

interface VendorOrderSummary {
  total_items: number;
  total_ordered: number;
  total_received: number;
  total_pending: number;
  total_ordered_value: number;
  total_received_value: number;
  bill_discrepancy: number | null;
}

interface VendorOrder {
  id: number;
  vendor_id: number;
  vendor_name: string | null;
  status: "open" | "closed";
  items: OrderLine[];
  notes: string | null;
  bill_number: string | null;
  bill_amount: number | null;
  bill_key: string | null;
  bill_uploaded_at: string | null;
  summary: VendorOrderSummary;
  created_at: string;
  updated_at: string;
}

interface CatalogItem {
  id: number;
  our_product_id: string;
  name: string;
  buying_price?: string;
  vendor_id?: number;
}

// ─── helpers ──────────────────────────────────────────────────────────────────

function fmt(n: number | null | undefined) {
  if (n == null) return "—";
  return `₹${Number(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function fmtDate(iso: string | null | undefined) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString("en-IN", { dateStyle: "short", timeStyle: "short" }); }
  catch { return iso; }
}

function pending(line: OrderLine) { return Math.max(0, line.qty_ordered - line.qty_received); }

const BTN = "inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-semibold transition disabled:opacity-50";
const BTN_PRIMARY = `${BTN} bg-blue-600 text-white hover:bg-blue-700`;
const BTN_SECONDARY = `${BTN} border border-slate-300 bg-white text-slate-700 hover:bg-slate-50`;
const BTN_DANGER = `${BTN} bg-red-100 text-red-700 hover:bg-red-200`;
const INPUT = "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500";
const LBL = "mb-1 block text-xs font-semibold uppercase tracking-wider text-slate-500";

// ─── component ────────────────────────────────────────────────────────────────

export function VendorOrdersScreen({ auth }: { auth: AuthState }) {
  const adminKey = auth.type === "admin_key" ? auth.key : "";
  const h = (): Record<string, string> => {
    if (adminKey) return { "X-Admin-Key": adminKey };
    if (auth.type === "staff") return { Authorization: `Bearer ${auth.token}` };
    return {};
  };
  const jh = (): Record<string, string> => ({ ...h(), "Content-Type": "application/json" });

  const [tab, setTab] = useState<"orders" | "summary">("orders");
  const [vendors, setVendors] = useState<VendorPublic[]>([]);
  const [catalog, setCatalog] = useState<CatalogItem[]>([]);
  const [orders, setOrders] = useState<VendorOrder[]>([]);
  const [summary, setSummary] = useState<{ vendor_id: number; vendor_name: string; open_orders: number; total_pending_items: number; total_pending_value: number; total_received_value: number; pending_lines: { product_name: string; qty_ordered: number; qty_received: number; qty_pending: number; unit_price: number; date_ordered: string }[] }[]>([]);
  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState<{ ok: boolean; msg: string } | null>(null);

  const showToast = (msg: string, ok: boolean) => { setToast({ msg, ok }); setTimeout(() => setToast(null), 4000); };

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const [ordersR, vendorsR, catalogR] = await Promise.all([
        fetchApi(apiUrl("vendor-orders"), { headers: h() }),
        fetchApi(apiUrl("vendors"), { headers: h() }),
        fetchApi(apiUrl("catalog?all=true"), { headers: h() }),
      ]);
      if (ordersR.ok) setOrders(await ordersR.json());
      if (vendorsR.ok) setVendors(await vendorsR.json());
      if (catalogR.ok) {
        const data = await catalogR.json();
        setCatalog(Array.isArray(data) ? data : (data.items || []));
      }
    } finally { setLoading(false); }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const loadSummary = useCallback(async () => {
    const r = await fetchApi(apiUrl("vendor-orders/summary"), { headers: h() });
    if (r.ok) setSummary(await r.json());
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { void loadAll(); }, [loadAll]);
  useEffect(() => { if (tab === "summary") void loadSummary(); }, [tab, loadSummary]);

  // ── Place new order drawer ──
  const [placeVendorId, setPlaceVendorId] = useState("");
  const [placeItems, setPlaceItems] = useState<{ cid: string; qty: string; price: string; notes: string }[]>([{ cid: "", qty: "", price: "", notes: "" }]);
  const [placing, setPlacing] = useState(false);

  const [vendorDupWarning, setVendorDupWarning] = useState<{ message: string; pendingVendorId: string; pendingItems: typeof placeItems } | null>(null);

  async function placeOrderBody(vendorId: string, items: {catalog_product_id: number; qty_ordered: number; unit_price: number; notes: string}[], forceDuplicate = false) {
    setPlacing(true);
    const r = await fetchApi(apiUrl(`vendor-orders/${vendorId}/add-items`), { method: "POST", headers: jh(), body: JSON.stringify({ items, force_duplicate: forceDuplicate }) });
    const data = await r.json().catch(() => ({})) as Record<string, unknown>;
    setPlacing(false);
    if (r.status === 409 && (data.detail as Record<string, unknown>)?.duplicate) {
      const detail = data.detail as Record<string, unknown>;
      setVendorDupWarning({ message: String(detail.message || "Duplicate vendor order detected."), pendingVendorId: vendorId, pendingItems: placeItems });
      return;
    }
    if (!r.ok) return showToast(formatApiError(data) || "Failed", false);
    showToast("Order placed!", true);
    setVendorDupWarning(null);
    setPlaceItems([{ cid: "", qty: "", price: "", notes: "" }]);
    setPlaceVendorId("");
    await loadAll();
  }

  async function placeOrder() {
    if (!placeVendorId) return showToast("Select a vendor", false);
    const items = placeItems.map(r => ({
      catalog_product_id: Number(r.cid), qty_ordered: Number(r.qty),
      unit_price: Number(r.price || 0), notes: r.notes,
    })).filter(i => i.catalog_product_id > 0 && i.qty_ordered > 0);
    if (!items.length) return showToast("Add at least one item", false);
    setVendorDupWarning(null);
    await placeOrderBody(placeVendorId, items);
  }

  // ── Active order drawer ──
  const [activeOrder, setActiveOrder] = useState<VendorOrder | null>(null);
  const [receiveMode, setReceiveMode] = useState(false);
  const [recvQty, setRecvQty] = useState<Record<string, string>>({});
  const [recvDate, setRecvDate] = useState(new Date().toISOString().slice(0, 10));
  const [receiving, setReceiving] = useState(false);
  const [billMode, setBillMode] = useState(false);
  const [billNum, setBillNum] = useState("");
  const [billAmt, setBillAmt] = useState("");
  const [billFile, setBillFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);

  function openOrder(vo: VendorOrder) {
    setActiveOrder(vo);
    setReceiveMode(false);
    setBillMode(false);
    setRecvQty({});
  }

  async function doReceive() {
    if (!activeOrder) return;
    const lines = activeOrder.items
      .map(it => ({ line_id: it.line_id, catalog_product_id: it.catalog_product_id, qty_received: Number(recvQty[it.line_id] || 0), date_received: new Date(recvDate).toISOString() }))
      .filter(l => l.qty_received > 0);
    if (!lines.length) return showToast("Enter at least one received quantity", false);
    setReceiving(true);
    const r = await fetchApi(apiUrl(`vendor-orders/${activeOrder.id}/receive`), { method: "POST", headers: jh(), body: JSON.stringify({ lines }) });
    const data = await r.json().catch(() => ({}));
    setReceiving(false);
    if (!r.ok) return showToast(formatApiError(data) || "Failed", false);
    showToast("Stock updated!", true);
    setActiveOrder(data as VendorOrder);
    setReceiveMode(false);
    setRecvQty({});
    await loadAll();
  }

  async function doUploadBill() {
    if (!activeOrder) return;
    setUploading(true);
    const fd = new FormData();
    fd.append("bill_number", billNum);
    fd.append("bill_amount", billAmt);
    if (billFile) fd.append("bill_file", billFile);
    const r = await fetchApi(apiUrl(`vendor-orders/${activeOrder.id}/upload-bill`), { method: "POST", headers: h(), body: fd });
    const data = await r.json().catch(() => ({}));
    setUploading(false);
    if (!r.ok) return showToast(formatApiError(data) || "Failed", false);
    showToast("Bill saved!", true);
    setActiveOrder(data as VendorOrder);
    setBillMode(false);
    await loadAll();
  }

  async function doClose(voId: number) {
    const r = await fetchApi(apiUrl(`vendor-orders/${voId}/close`), { method: "PATCH", headers: jh() });
    if (r.ok) { showToast("Order closed", true); setActiveOrder(null); await loadAll(); }
  }

  const vName = (id: number) => { const v = vendors.find(vv => vv.id === id); return v?.company_name || v?.person_name || `Vendor #${id}`; };

  return (
    <div className="relative space-y-6 p-4 sm:p-6">
      {toast && (
        <div className={`fixed right-4 top-16 z-50 rounded-xl px-4 py-3 text-sm font-semibold shadow-xl ${toast.ok ? "bg-emerald-600 text-white" : "bg-red-600 text-white"}`}>
          {toast.msg}
        </div>
      )}

      {/* Tab bar */}
      <div className="flex gap-2">
        {([["orders", "📋 Orders"], ["summary", "📊 Summary"]] as const).map(([id, label]) => (
          <button key={id} type="button" onClick={() => setTab(id)}
            className={`rounded-lg px-4 py-2 text-sm font-semibold transition ${tab === id ? "bg-blue-600 text-white" : "border border-slate-200 bg-white text-slate-600 hover:bg-slate-50"}`}>
            {label}
          </button>
        ))}
      </div>

      {/* ── ORDERS TAB ── */}
      {tab === "orders" && (
        <div className="grid gap-6 lg:grid-cols-[1fr_1.6fr]">
          {/* Left: place order + list */}
          <div className="space-y-4">
            {/* Place new order */}
            <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
              <h3 className="mb-3 text-sm font-bold uppercase tracking-wide text-slate-500">Place order with vendor</h3>
              <div className="mb-3">
                <label className={LBL}>Vendor *</label>
                <select value={placeVendorId} onChange={e => setPlaceVendorId(e.target.value)} className={INPUT}>
                  <option value="">— select vendor —</option>
                  {vendors.map(v => <option key={v.id} value={v.id}>{v.company_name || v.person_name}</option>)}
                </select>
              </div>

              {placeItems.map((row, idx) => (
                <div key={idx} className="mb-2 flex flex-wrap gap-2 rounded-lg border border-slate-100 bg-slate-50 p-2">
                  <select value={row.cid}
                    onChange={e => setPlaceItems(p => p.map((r, i) => i === idx ? { ...r, cid: e.target.value, price: catalog.find(c => String(c.id) === e.target.value)?.buying_price || "" } : r))}
                    className="min-w-0 flex-1 rounded-lg border border-slate-300 px-2 py-1.5 text-sm">
                    <option value="">— product —</option>
                    {catalog.filter(c => !placeVendorId || String(c.vendor_id) === placeVendorId).map(c => <option key={c.id} value={c.id}>{c.our_product_id}</option>)}
                  </select>
                  <input type="number" min="1" placeholder="Qty" value={row.qty}
                    onChange={e => setPlaceItems(p => p.map((r, i) => i === idx ? { ...r, qty: e.target.value } : r))}
                    className="w-16 rounded-lg border border-slate-300 px-2 py-1.5 text-sm" />
                  <input type="number" min="0" step="0.01" placeholder="Price" value={row.price}
                    onChange={e => setPlaceItems(p => p.map((r, i) => i === idx ? { ...r, price: e.target.value } : r))}
                    className="w-24 rounded-lg border border-slate-300 px-2 py-1.5 text-sm" />
                  {placeItems.length > 1 && (
                    <button type="button" onClick={() => setPlaceItems(p => p.filter((_, i) => i !== idx))}
                      className="text-xs text-red-500 hover:underline">×</button>
                  )}
                </div>
              ))}

              <div className="mt-2 flex gap-2 flex-wrap">
                <button type="button" onClick={() => setPlaceItems(p => [...p, { cid: "", qty: "", price: "", notes: "" }])}
                  className={BTN_SECONDARY + " text-xs"}>+ Add item</button>
                <button type="button" onClick={placeOrder} disabled={placing} className={BTN_PRIMARY}>
                  {placing ? "Placing…" : "Place Order"}
                </button>
              </div>
              {vendorDupWarning && (
                <div className="mt-2 rounded-xl border border-amber-300 bg-amber-50 p-3 space-y-2">
                  <div className="text-sm font-semibold text-amber-800">⚠️ Duplicate Order Detected</div>
                  <div className="text-xs text-amber-700">{vendorDupWarning.message}</div>
                  <div className="flex gap-2">
                    <button type="button" disabled={placing} onClick={() => {
                      const items = vendorDupWarning.pendingItems.map(r => ({ catalog_product_id: Number(r.cid), qty_ordered: Number(r.qty), unit_price: Number(r.price || 0), notes: r.notes })).filter(i => i.catalog_product_id > 0 && i.qty_ordered > 0);
                      void placeOrderBody(vendorDupWarning.pendingVendorId, items, true);
                    }} className="rounded-lg bg-amber-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-amber-700 disabled:opacity-50">
                      {placing ? "Placing…" : "Proceed Anyway"}
                    </button>
                    <button type="button" onClick={() => setVendorDupWarning(null)} className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-100">Cancel</button>
                  </div>
                </div>
              )}
            </div>

            {/* Order list */}
            <div className="rounded-2xl border border-slate-200 bg-white shadow-sm overflow-hidden">
              <div className="border-b border-slate-100 bg-slate-50 px-4 py-3 flex items-center justify-between">
                <h3 className="text-sm font-bold text-slate-600">All Vendor Orders</h3>
                <button onClick={loadAll} className="text-xs text-blue-600 hover:underline">{loading ? "…" : "Refresh"}</button>
              </div>
              {orders.length === 0 && !loading && (
                <p className="px-4 py-8 text-center text-sm text-slate-400">No vendor orders yet</p>
              )}
              <ul className="divide-y divide-slate-100">
                {orders.map(vo => (
                  <li key={vo.id}
                    onClick={() => openOrder(vo)}
                    className={`cursor-pointer px-4 py-3 transition hover:bg-slate-50 ${activeOrder?.id === vo.id ? "bg-blue-50" : ""}`}>
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <p className="text-sm font-semibold text-slate-800">{vName(vo.vendor_id)}</p>
                        <p className="text-xs text-slate-500">{fmtDate(vo.updated_at)}</p>
                      </div>
                      <div className="text-right">
                        <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${vo.status === "open" ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-600"}`}>
                          {vo.status}
                        </span>
                        <p className="mt-1 text-xs text-slate-500">{vo.summary.total_pending} pending</p>
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          </div>

          {/* Right: active order detail */}
          {activeOrder ? (
            <div className="rounded-2xl border border-slate-200 bg-white shadow-sm overflow-hidden">
              {/* Header */}
              <div className="border-b border-slate-100 bg-gradient-to-r from-slate-50 to-white px-5 py-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h2 className="text-base font-bold text-slate-800">{vName(activeOrder.vendor_id)}</h2>
                    <p className="text-xs text-slate-500">Order #{activeOrder.id} · {fmtDate(activeOrder.updated_at)}</p>
                  </div>
                  <span className={`rounded-full px-3 py-1 text-xs font-bold ${activeOrder.status === "open" ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-600"}`}>
                    {activeOrder.status}
                  </span>
                </div>

                {/* Summary pills */}
                <div className="mt-3 flex flex-wrap gap-3 text-xs">
                  <span className="rounded-lg bg-slate-100 px-2 py-1"><strong>{activeOrder.summary.total_pending}</strong> pending</span>
                  <span className="rounded-lg bg-blue-50 px-2 py-1">{fmt(activeOrder.summary.total_ordered_value)} ordered</span>
                  <span className="rounded-lg bg-emerald-50 px-2 py-1">{fmt(activeOrder.summary.total_received_value)} received</span>
                  {activeOrder.summary.bill_discrepancy != null && (
                    <span className="rounded-lg bg-red-100 px-2 py-1 text-red-700 font-bold">
                      ⚠ Bill mismatch: {fmt(activeOrder.summary.bill_discrepancy)}
                    </span>
                  )}
                </div>

                {/* Action buttons */}
                {activeOrder.status === "open" && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button type="button" onClick={() => { setReceiveMode(true); setBillMode(false); }} className={BTN_PRIMARY + " text-xs"}>
                      📦 Receive Goods
                    </button>
                    <button type="button" onClick={() => { setBillMode(true); setReceiveMode(false); }} className={BTN_SECONDARY + " text-xs"}>
                      🧾 Upload Bill
                    </button>
                    <button type="button" onClick={() => doClose(activeOrder.id)} className={BTN_SECONDARY + " text-xs"}>
                      ✓ Close Order
                    </button>
                  </div>
                )}
              </div>

              {/* Receive form */}
              {receiveMode && (
                <div className="border-b border-slate-100 bg-blue-50/40 px-5 py-4 space-y-3">
                  <h4 className="text-sm font-semibold text-blue-800">Record received goods</h4>
                  <div>
                    <label className={LBL}>Receipt date</label>
                    <input type="date" value={recvDate} onChange={e => setRecvDate(e.target.value)} className={INPUT + " max-w-xs"} />
                  </div>
                  <div className="overflow-hidden rounded-xl border border-slate-200">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="bg-slate-50 text-xs font-semibold uppercase text-slate-500">
                          <th className="px-3 py-2 text-left">Product</th>
                          <th className="px-3 py-2 text-right">Ordered</th>
                          <th className="px-3 py-2 text-right">Received so far</th>
                          <th className="px-3 py-2 text-right">Pending</th>
                          <th className="px-3 py-2 text-right">Receive now</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {activeOrder.items.filter(it => pending(it) > 0).map(it => (
                          <tr key={it.line_id}>
                            <td className="px-3 py-2 font-medium text-slate-800">
                              {it.product_name}
                              <span className="ml-1.5 text-xs text-slate-400">{fmtDate(it.date_ordered)}</span>
                            </td>
                            <td className="px-3 py-2 text-right tabular-nums">{it.qty_ordered}</td>
                            <td className="px-3 py-2 text-right tabular-nums text-emerald-700">{it.qty_received}</td>
                            <td className="px-3 py-2 text-right tabular-nums text-amber-700 font-semibold">{pending(it)}</td>
                            <td className="px-3 py-2 text-right">
                              <input type="number" min="0" max={pending(it)}
                                value={recvQty[it.line_id] ?? ""}
                                onChange={e => setRecvQty(p => ({ ...p, [it.line_id]: e.target.value }))}
                                className="w-20 rounded border border-slate-300 px-2 py-1 text-right text-sm" />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <div className="flex gap-2">
                    <button type="button" onClick={doReceive} disabled={receiving} className={BTN_PRIMARY}>
                      {receiving ? "Saving…" : "Add Stock"}
                    </button>
                    <button type="button" onClick={() => { setReceiveMode(false); setRecvQty({}); }} className={BTN_SECONDARY}>Cancel</button>
                  </div>
                </div>
              )}

              {/* Bill upload form */}
              {billMode && (
                <div className="border-b border-slate-100 bg-amber-50/40 px-5 py-4 space-y-3">
                  <h4 className="text-sm font-semibold text-amber-800">Upload vendor bill</h4>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className={LBL}>Bill number</label>
                      <input value={billNum} onChange={e => setBillNum(e.target.value)} placeholder="e.g. VB-2024-001" className={INPUT} />
                    </div>
                    <div>
                      <label className={LBL}>Bill amount (₹)</label>
                      <input type="number" step="0.01" value={billAmt} onChange={e => setBillAmt(e.target.value)}
                        placeholder={String(activeOrder.summary.total_received_value)} className={INPUT} />
                      {billAmt && Math.abs(Number(billAmt) - activeOrder.summary.total_received_value) > 0.01 && (
                        <p className="mt-1 text-xs text-red-600 font-semibold">
                          ⚠ Calculated: {fmt(activeOrder.summary.total_received_value)} · Diff: {fmt(Math.abs(Number(billAmt) - activeOrder.summary.total_received_value))}
                        </p>
                      )}
                    </div>
                    <div className="col-span-2">
                      <label className={LBL}>Bill document (PDF / image)</label>
                      <input type="file" accept="image/*,.pdf" onChange={e => setBillFile(e.target.files?.[0] ?? null)}
                        className="block w-full text-sm text-slate-500 file:mr-3 file:rounded-lg file:border-0 file:bg-slate-100 file:px-3 file:py-1.5 file:text-sm" />
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <button type="button" onClick={doUploadBill} disabled={uploading} className={BTN_PRIMARY}>
                      {uploading ? "Saving…" : "Save Bill"}
                    </button>
                    <button type="button" onClick={() => setBillMode(false)} className={BTN_SECONDARY}>Cancel</button>
                  </div>
                </div>
              )}

              {/* Bill info banner */}
              {activeOrder.bill_number && (
                <div className={`border-b px-5 py-3 text-sm ${activeOrder.summary.bill_discrepancy ? "border-red-100 bg-red-50" : "border-emerald-100 bg-emerald-50"}`}>
                  <span className="font-semibold">Bill #{activeOrder.bill_number}</span>
                  <span className="mx-2 text-slate-400">·</span>
                  <span>{fmt(activeOrder.bill_amount)}</span>
                  {activeOrder.summary.bill_discrepancy != null && (
                    <span className="ml-2 font-semibold text-red-700">
                      ⚠ Discrepancy: {fmt(activeOrder.summary.bill_discrepancy)}
                    </span>
                  )}
                  {activeOrder.bill_uploaded_at && (
                    <span className="ml-2 text-xs text-slate-400">uploaded {fmtDate(activeOrder.bill_uploaded_at)}</span>
                  )}
                </div>
              )}

              {/* Items table */}
              <div className="overflow-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-slate-50 text-xs font-semibold uppercase text-slate-500">
                      <th className="px-4 py-2.5 text-left">Product</th>
                      <th className="px-4 py-2.5 text-left">Order Date</th>
                      <th className="px-4 py-2.5 text-right">Ordered</th>
                      <th className="px-4 py-2.5 text-right">Received</th>
                      <th className="px-4 py-2.5 text-right">Pending</th>
                      <th className="px-4 py-2.5 text-right">Unit Price</th>
                      <th className="px-4 py-2.5 text-right">Value</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {activeOrder.items.map(it => {
                      const pend = pending(it);
                      return (
                        <tr key={it.line_id} className={pend > 0 ? "" : "opacity-60"}>
                          <td className="px-4 py-2.5 font-medium text-slate-800">{it.product_name}</td>
                          <td className="px-4 py-2.5 text-xs text-slate-500">{fmtDate(it.date_ordered)}</td>
                          <td className="px-4 py-2.5 text-right tabular-nums">{it.qty_ordered}</td>
                          <td className="px-4 py-2.5 text-right tabular-nums text-emerald-700">
                            {it.qty_received > 0 ? `${it.qty_received}` : "—"}
                            {it.date_received && <span className="ml-1 text-xs text-slate-400">{fmtDate(it.date_received)}</span>}
                          </td>
                          <td className={`px-4 py-2.5 text-right tabular-nums font-semibold ${pend > 0 ? "text-amber-700" : "text-slate-400"}`}>
                            {pend > 0 ? pend : "✓"}
                          </td>
                          <td className="px-4 py-2.5 text-right tabular-nums">{fmt(it.unit_price)}</td>
                          <td className="px-4 py-2.5 text-right tabular-nums">{fmt(it.qty_ordered * it.unit_price)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <div className="flex items-center justify-center rounded-2xl border border-dashed border-slate-200 bg-slate-50 p-12 text-center">
              <div>
                <p className="text-4xl">📋</p>
                <p className="mt-3 text-sm font-semibold text-slate-600">Select an order to view details</p>
                <p className="mt-1 text-xs text-slate-400">Or place a new order with a vendor on the left</p>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── SUMMARY TAB ── */}
      {tab === "summary" && (
        <div className="space-y-4">
          {summary.filter(s => s.open_orders > 0 || s.total_pending_items > 0).length === 0 && (
            <p className="text-center py-10 text-slate-400 text-sm">No open vendor orders</p>
          )}
          {summary.filter(s => s.open_orders > 0 || s.total_pending_items > 0).map(s => (
            <div key={s.vendor_id} className="rounded-2xl border border-slate-200 bg-white shadow-sm overflow-hidden">
              <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50 px-5 py-3">
                <h3 className="font-bold text-slate-800">{s.vendor_name}</h3>
                <div className="flex gap-4 text-xs text-slate-500">
                  <span><strong className="text-slate-800">{s.open_orders}</strong> open orders</span>
                  <span><strong className="text-amber-700">{s.total_pending_items}</strong> items pending</span>
                  <span>{fmt(s.total_pending_value)} pending value</span>
                  <span>{fmt(s.total_received_value)} received</span>
                </div>
              </div>
              {s.pending_lines.length > 0 && (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-slate-50 text-xs font-semibold uppercase text-slate-500">
                      <th className="px-4 py-2 text-left">Product</th>
                      <th className="px-4 py-2 text-right">Ordered</th>
                      <th className="px-4 py-2 text-right">Received</th>
                      <th className="px-4 py-2 text-right">Pending</th>
                      <th className="px-4 py-2 text-right">Unit Price</th>
                      <th className="px-4 py-2 text-right">Pending Value</th>
                      <th className="px-4 py-2 text-left">Order Date</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {s.pending_lines.map((line, i) => (
                      <tr key={i}>
                        <td className="px-4 py-2 font-medium text-slate-800">{line.product_name}</td>
                        <td className="px-4 py-2 text-right tabular-nums">{line.qty_ordered}</td>
                        <td className="px-4 py-2 text-right tabular-nums text-emerald-700">{line.qty_received}</td>
                        <td className="px-4 py-2 text-right tabular-nums font-semibold text-amber-700">{line.qty_pending}</td>
                        <td className="px-4 py-2 text-right tabular-nums">{fmt(line.unit_price)}</td>
                        <td className="px-4 py-2 text-right tabular-nums">{fmt(line.qty_pending * line.unit_price)}</td>
                        <td className="px-4 py-2 text-xs text-slate-400">{fmtDate(line.date_ordered)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
