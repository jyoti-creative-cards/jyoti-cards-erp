"use client";

import { useCallback, useEffect, useState } from "react";
import { Drawer } from "@/components/Drawer";
import { apiUrl, fetchApi, formatApiError } from "@/lib/api";
import { VendorOrdersScreen } from "@/components/VendorOrdersScreen";
import { ReturnsScreen } from "@/components/ReturnsScreen";
import type { AuthState } from "@/lib/types";
import type { BillSeries, CatalogProductPublic, CustomerBillPublic, CustomerOrderAdminPublic, CustomerPublic } from "@/lib/types";

const INPUT = "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500";
const LABEL = "mb-1 block text-xs font-semibold text-slate-500 uppercase tracking-wider";
const BTN_PRIMARY = "inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-700 disabled:opacity-50";
const BTN_SECONDARY = "inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm transition hover:bg-slate-50";

function statusBadge(status: string) {
  const map: Record<string, { label: string; cls: string }> = {
    received:   { label: "Received",   cls: "bg-emerald-50 text-emerald-700 ring-emerald-200" },
    billed:     { label: "Billed",     cls: "bg-violet-50 text-violet-700 ring-violet-200" },
    closed:     { label: "Closed",     cls: "bg-slate-100 text-slate-600 ring-slate-200" },
  };
  const s = map[status] ?? { label: status, cls: "bg-slate-100 text-slate-600 ring-slate-200" };
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${s.cls}`}>
      {s.label}
    </span>
  );
}

interface Props {
  adminKey: string;
  auth: AuthState;
}

export function OrdersScreen({ adminKey, auth }: Props) {
  const [tab, setTab] = useState<"customer" | "vendor" | "returns">("customer");

  const headers = () => {
    const h: Record<string, string> = { "Content-Type": "application/json" };
    if (adminKey.trim()) h["X-Admin-Key"] = adminKey.trim();
    return h;
  };
  const headersAdmin = (): Record<string, string> => adminKey.trim() ? { "X-Admin-Key": adminKey.trim() } : {};

  return (
    <div>
      <div className="mb-6 inline-flex rounded-xl border border-slate-200 bg-white p-1 shadow-sm">
        <button
          type="button"
          onClick={() => setTab("customer")}
          className={`rounded-lg px-5 py-2 text-sm font-semibold transition ${tab === "customer" ? "bg-blue-600 text-white shadow" : "text-slate-600 hover:bg-slate-50"}`}
        >
          🛒 Customer
        </button>
        <button
          type="button"
          onClick={() => setTab("vendor")}
          className={`rounded-lg px-5 py-2 text-sm font-semibold transition ${tab === "vendor" ? "bg-blue-600 text-white shadow" : "text-slate-600 hover:bg-slate-50"}`}
        >
          📦 Vendor
        </button>
        <button
          type="button"
          onClick={() => setTab("returns")}
          className={`rounded-lg px-5 py-2 text-sm font-semibold transition ${tab === "returns" ? "bg-blue-600 text-white shadow" : "text-slate-600 hover:bg-slate-50"}`}
        >
          ↩️ Returns
        </button>
      </div>

      {tab === "customer" && (
        <CustomerOrdersTab headers={headers} headersAdmin={headersAdmin} adminKey={adminKey} />
      )}
      {tab === "vendor" && (
        <VendorOrdersScreen auth={auth} />
      )}
      {tab === "returns" && (
        <ReturnsScreen auth={auth} canEdit={true} />
      )}
    </div>
  );
}

// ─── CUSTOMER SUMMARY TAB ──────────────────────────────────────────────────────

function CustomerSummaryTab({ headersAdmin }: { headersAdmin: () => Record<string, string> }) {
  const [orders, setOrders] = useState<CustomerOrderAdminPublic[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      setLoading(true);
      const r = await fetchApi(apiUrl("customer-orders"), { headers: headersAdmin() });
      if (r.ok) setOrders(await r.json());
      setLoading(false);
    }
    void load();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Group open orders by customer
  const openOrders = orders.filter(o => ["received", "billed"].includes(o.status));

  const byCustomer: Record<string, { name: string; orders: CustomerOrderAdminPublic[] }> = {};
  for (const o of openOrders) {
    if (!byCustomer[o.customer_id]) byCustomer[o.customer_id] = { name: o.customer_name, orders: [] };
    byCustomer[o.customer_id].orders.push(o);
  }

  function pendingItems(o: CustomerOrderAdminPublic) {
    return o.items.map(it => ({
      ...it,
      qty_remaining: Math.max(0, it.quantity - (it.qty_billed ?? 0)),
    })).filter(it => it.qty_remaining > 0);
  }

  return (
    <div className="space-y-4">
      {loading && <p className="py-10 text-center text-slate-400">Loading…</p>}
      {!loading && Object.keys(byCustomer).length === 0 && (
        <p className="py-10 text-center text-slate-400">No open customer orders</p>
      )}
      {Object.entries(byCustomer).map(([cid, { name, orders: cOrders }]) => {
        const allPending = cOrders.flatMap(pendingItems);
        const totalPendingValue = allPending.reduce((s, it) => s + it.qty_remaining * Number(it.unit_price), 0);
        return (
          <div key={cid} className="rounded-2xl border border-slate-200 bg-white shadow-sm overflow-hidden">
            <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50 px-5 py-3">
              <h3 className="font-bold text-slate-800">{name}</h3>
              <div className="flex gap-4 text-xs text-slate-500">
                <span><strong className="text-slate-800">{cOrders.length}</strong> open order{cOrders.length !== 1 ? "s" : ""}</span>
                <span><strong className="text-amber-700">{allPending.length}</strong> pending lines</span>
                <span>₹{totalPendingValue.toLocaleString("en-IN", { minimumFractionDigits: 2 })} pending</span>
              </div>
            </div>
            {allPending.length > 0 && (
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-slate-50 text-xs font-semibold uppercase text-slate-500">
                    <th className="px-4 py-2 text-left">Product</th>
                    <th className="px-4 py-2 text-right">Ordered</th>
                    <th className="px-4 py-2 text-right">Billed</th>
                    <th className="px-4 py-2 text-right">Pending</th>
                    <th className="px-4 py-2 text-right">Unit Price</th>
                    <th className="px-4 py-2 text-right">Pending Value</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {allPending.map((it, i) => (
                    <tr key={i}>
                      <td className="px-4 py-2 font-medium text-slate-800">{it.our_product_id || it.name}</td>
                      <td className="px-4 py-2 text-right tabular-nums">{it.quantity}</td>
                      <td className="px-4 py-2 text-right tabular-nums text-amber-600">{it.qty_billed ?? 0}</td>
                      <td className="px-4 py-2 text-right tabular-nums font-semibold text-emerald-700">{it.qty_remaining}</td>
                      <td className="px-4 py-2 text-right tabular-nums">₹{Number(it.unit_price).toLocaleString("en-IN")}</td>
                      <td className="px-4 py-2 text-right tabular-nums">₹{(it.qty_remaining * Number(it.unit_price)).toLocaleString("en-IN")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ─────────────────────────────── CUSTOMER ORDERS ───────────────────────────────

function CustomerOrdersTab({
  headers,
  headersAdmin,
  adminKey,
}: {
  headers: () => Record<string, string>;
  headersAdmin: () => Record<string, string>;
  adminKey: string;
}) {
  const [orders, setOrders] = useState<CustomerOrderAdminPublic[]>([]);
  const [catalog, setCatalog] = useState<CatalogProductPublic[]>([]);
  const [customers, setCustomers] = useState<CustomerPublic[]>([]);
  const [loading, setLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string>("received");
  const [search, setSearch] = useState("");
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null);

  // Drawer
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selected, setSelected] = useState<CustomerOrderAdminPublic | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState("");

  // Bill form
  const [showBillForm, setShowBillForm] = useState(false);
  const [freight, setFreight] = useState("");
  const [packaging, setPackaging] = useState("");
  const [discount, setDiscount] = useState("");
  const [gstEnabled, setGstEnabled] = useState(false);
  const [gstRate, setGstRate] = useState("18");
  const [billStockMap, setBillStockMap] = useState<Record<number, number>>({});
  const [billMsg, setBillMsg] = useState("");
  const [billBusy, setBillBusy] = useState(false);
  const [billData, setBillData] = useState<CustomerBillPublic | null>(null);

  // Bill series
  const [billSeriesList, setBillSeriesList] = useState<BillSeries[]>([]);
  const [billSeriesId, setBillSeriesId] = useState("");

  // Per-item overrides
  const [itemOverrides, setItemOverrides] = useState<Record<number, { enabled: boolean; discount: string }>>({});
  // rateType removed — always use order rate (selling price)
  const [billNarration, setBillNarration] = useState("");
  const [additionalCharges, setAdditionalCharges] = useState<{ name: string; amount: string }[]>([]);
  const [stockWarning, setStockWarning] = useState<{items: {name: string; need: number; have: number}[]} | null>(null);
  const [billBodyPending, setBillBodyPending] = useState<Record<string, unknown> | null>(null);

  // Partial billing: which items/quantities to bill in this run
  const [partialBillQty, setPartialBillQty] = useState<Record<number, string>>({});

  // Rate type
  // rate_type not sent — always defaults to "order" on backend

  // Zero-rate confirmation
  const [zeroRateConfirmed, setZeroRateConfirmed] = useState(false);
  const [showZeroRateBanner, setShowZeroRateBanner] = useState(false);

  // Merge orders
  const [mergeMode, setMergeMode] = useState(false);
  const [selectedForMerge, setSelectedForMerge] = useState<Set<number>>(new Set());
  const [merging, setMerging] = useState(false);

  // Bill detail modal
  const [showBillModal, setShowBillModal] = useState(false);
  const [printCopies, setPrintCopies] = useState(1);
  const [printing, setPrinting] = useState(false);

  async function triggerPrint(billId: number, copies: number) {
    setPrinting(true);
    try {
      const url = apiUrl(`customer-bills/${billId}/print?copies=${copies}`);
      const headers: Record<string, string> = {};
      if (adminKey.trim()) headers["X-Admin-Key"] = adminKey.trim();
      const res = await fetchApi(url, { headers });
      if (!res.ok) {
        // Fallback: open download URL in new tab
        window.open(`${apiUrl(`customer-bills/${billId}/download`)}?x_admin_key=${encodeURIComponent(adminKey)}`, "_blank");
        return;
      }
      const blob = await res.blob();
      const blobUrl = URL.createObjectURL(blob);
      // Open blob in new window then trigger print
      const w = window.open(blobUrl, "_blank");
      if (w) {
        w.onload = () => { try { w.print(); } catch (_) { /* user prints manually */ } };
        // For PDFs loaded by browser plugin, onload may not fire; auto-focus helps
        setTimeout(() => { try { w.focus(); } catch (_) {} }, 500);
      }
      // Revoke after delay
      setTimeout(() => URL.revokeObjectURL(blobUrl), 120000);
    } finally {
      setPrinting(false);
    }
  }

  // Credit summary
  const [creditSummary, setCreditSummary] = useState<{ credit_limit: string | null; outstanding: string; remaining: string | null } | null>(null);

  // Freight vendors
  const [freightVendors, setFreightVendors] = useState<{ id: number; name: string; balance_due: string }[]>([]);
  const [selectedFreightVendorId, setSelectedFreightVendorId] = useState("");

  // ── Offline order (1-click order + bill) ──
  const [showOfflineForm, setShowOfflineForm] = useState(false);
  const [offlineCustomerId, setOfflineCustomerId] = useState("");
  const [offlineItems, setOfflineItems] = useState<{ cid: string; qty: string; price: string }[]>([{ cid: "", qty: "", price: "" }]);
  const [offlineStockMap, setOfflineStockMap] = useState<Record<string, number>>({}); // cid → qty
  const [offlineGst, setOfflineGst] = useState(false);
  const [offlineGstRate, setOfflineGstRate] = useState("18");
  const [offlineDiscount, setOfflineDiscount] = useState("");
  const [offlineFreight, setOfflineFreight] = useState("");
  const [offlinePkg, setOfflinePkg] = useState("");
  const [offlineSeriesId, setOfflineSeriesId] = useState("");
  const [offlineNotes, setOfflineNotes] = useState("");
  const [offlineNarration, setOfflineNarration] = useState("");
  const [offlineBusy, setOfflineBusy] = useState(false);
  const [offlineResult, setOfflineResult] = useState<{ bill_no?: string; grand_total?: string; document_url?: string; bill_id?: number } | null>(null);
  const [offlineDupWarning, setOfflineDupWarning] = useState<{ message: string; pendingBody: Record<string, unknown> } | null>(null);
  const [offlineStockWarning, setOfflineStockWarning] = useState<{ items: { name: string; need: number; have: number }[]; pendingBody: Record<string, unknown> } | null>(null);
  const [offlineAdditionalCharges, setOfflineAdditionalCharges] = useState<{ name: string; amount: string }[]>([{ name: "", amount: "" }]);
  const [offlineFreightVendorId, setOfflineFreightVendorId] = useState("");
  const [offlineShipType, setOfflineShipType] = useState<"" | "bus" | "transport">("");

  // ── Shared stock map (catalog_product_id → available qty) ──
  const [stockMap, setStockMap] = useState<Record<string, number>>({});

  const loadStockMap = useCallback(async () => {
    const r = await fetchApi(apiUrl("inventory/stock-balances"), { headers: headersAdmin() });
    if (!r.ok) return;
    const data: { catalog_product_id: number; balance: number }[] = await r.json();
    const m: Record<string, number> = {};
    for (const item of data) m[String(item.catalog_product_id)] = item.balance;
    setStockMap(m);
    setOfflineStockMap(m);
  }, [adminKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Edit order items ──
  const [editItemsMode, setEditItemsMode] = useState(false);
  const [editItemsList, setEditItemsList] = useState<{ cid: string; qty: string; price: string }[]>([]);
  const [editItemsBusy, setEditItemsBusy] = useState(false);
  const [showVersions, setShowVersions] = useState(false);

  // ── Edit bill ──
  const [editBillMode, setEditBillMode] = useState(false);
  const [editBillList, setEditBillList] = useState<{ cid: string; qty: string; price: string }[]>([]);
  const [editBillBusy, setEditBillBusy] = useState(false);
  const [billHistory, setBillHistory] = useState<CustomerBillPublic[]>([]);
  const [showBillHistory, setShowBillHistory] = useState(false);

  // Edit order state
  const [editStatus, setEditStatus] = useState("received"); // kept for overrideStatus fallback in saveOrder

  const showToast = (msg: string, ok: boolean) => { setToast({ msg, ok }); setTimeout(() => setToast(null), 3500); };

  const load = useCallback(async () => {
    if (!adminKey.trim()) return;
    setLoading(true);
    const [or, cr, fvr, custr, serR] = await Promise.all([
      fetchApi(apiUrl("customer-orders"), { headers: headersAdmin() }),
      fetchApi(apiUrl("catalog"), { headers: headersAdmin() }),
      fetchApi(apiUrl("freight-vendors"), { headers: headersAdmin() }),
      fetchApi(apiUrl("customers"), { headers: headersAdmin() }),
      fetchApi(apiUrl("bill-series"), { headers: headersAdmin() }),
    ]);
    if (or.ok) setOrders(await or.json());
    if (cr.ok) {
      const crData = await cr.json();
      setCatalog(Array.isArray(crData) ? crData : (crData?.items ?? []));
    }
    if (fvr.ok) setFreightVendors(await fvr.json());
    if (custr.ok) setCustomers(await custr.json());
    if (serR.ok) {
      const sl: BillSeries[] = await serR.json();
      setBillSeriesList(sl.filter((s) => s.is_active && s.current_num < s.end_num));
    }
    setLoading(false);
    void loadStockMap();
  }, [adminKey]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { void load(); }, [load]);

  async function submitOfflineOrderBody(body: Record<string, unknown>) {
    setOfflineBusy(true); setOfflineResult(null); setOfflineDupWarning(null); setOfflineStockWarning(null);
    const r = await fetchApi(apiUrl("customer-orders/offline"), { method: "POST", headers: headers(), body: JSON.stringify(body) });
    const data = await r.json().catch(() => ({})) as { bill?: { bill_no?: string; totals?: { grand_total?: string }; document_url?: string }; detail?: Record<string, unknown> };
    setOfflineBusy(false);
    if (r.status === 409 && data.detail) {
      if (data.detail.duplicate) {
        setOfflineDupWarning({ message: String(data.detail.message || "Duplicate order detected."), pendingBody: { ...body, force_duplicate: true } });
        return;
      }
      if (data.detail.insufficient_stock) {
        const items = (data.detail.items as { name: string; need: number; have: number }[]) || [];
        setOfflineStockWarning({ items, pendingBody: { ...body, force_stock: true } });
        return;
      }
    }
    if (!r.ok) { showToast(formatApiError(data as Record<string, unknown>), false); return; }
    // Reset form for next order
    setOfflineCustomerId("");
    setOfflineItems([{ cid: "", qty: "", price: "" }]);
    setOfflineGst(false);
    setOfflineGstRate("18");
    setOfflineDiscount("");
    setOfflineFreight("");
    setOfflinePkg("");
    setOfflineNotes("");
    setOfflineNarration("");
    setOfflineAdditionalCharges([{ name: "", amount: "" }]);
    setOfflineFreightVendorId("");
    setOfflineShipType("");
    // Treat the bill response as a loosely-typed record so we can access extra fields
    const billAny = data.bill as Record<string, unknown>;
    const billTotals = (billAny?.totals ?? {}) as Record<string, unknown>;
    setOfflineResult({
      bill_no: typeof billAny?.bill_no === "string" ? billAny.bill_no : undefined,
      grand_total: (billTotals?.rounded_grand_total ?? billTotals?.grand_total) as string | undefined,
      document_url: typeof billAny?.document_url === "string" ? billAny.document_url : undefined,
      bill_id: typeof billAny?.id === "number" ? billAny.id : undefined,
    });
    showToast(billAny?.bill_no ? `Bill ${billAny.bill_no} created!` : "Order + Bill created!", true);
    void load();
  }

  async function submitOfflineOrder() {
    if (!offlineCustomerId) return showToast("Select a customer", false);
    const items = offlineItems
      .map(r => ({ catalog_product_id: Number(r.cid), quantity: Number(r.qty), unit_price: r.price ? Number(r.price) : undefined }))
      .filter(i => i.catalog_product_id > 0 && i.quantity > 0);
    if (!items.length) return showToast("Add at least one item", false);
    const body: Record<string, unknown> = {
      customer_id: Number(offlineCustomerId),
      items,
      gst_enabled: offlineGst,
      gst_rate_percent: offlineGst ? Number(offlineGstRate) : 0,
      notes: offlineNotes.trim() || null,
    };
    if (offlineDiscount.trim()) body.discount_percent = Number(offlineDiscount);
    if (offlineFreight.trim()) body.freight_charges = Number(offlineFreight);
    if (offlinePkg.trim()) body.packaging_charges = Number(offlinePkg);
    if (offlineFreightVendorId) body.freight_vendor_id = Number(offlineFreightVendorId);
    if (offlineSeriesId) body.bill_series_id = Number(offlineSeriesId);
    if (offlineNarration.trim()) body.narration = offlineNarration.trim();
    const validCharges = offlineAdditionalCharges.filter(c => c.name.trim() && c.amount.trim() && Number(c.amount) > 0);
    if (validCharges.length) body.additional_charges = validCharges.map(c => ({ name: c.name.trim(), amount: Number(c.amount) }));
    void submitOfflineOrderBody(body);
  }

  async function submitEditItems() {
    if (!selected || !editItemsList.length) return;
    const items = editItemsList
      .map(r => ({ catalog_product_id: Number(r.cid), quantity: Number(r.qty), unit_price: r.price ? Number(r.price) : undefined }))
      .filter(i => i.catalog_product_id > 0 && i.quantity > 0);
    if (!items.length) return showToast("Add at least one item", false);
    setEditItemsBusy(true);
    const r = await fetchApi(apiUrl(`customer-orders/${selected.id}/edit-items`), {
      method: "PATCH", headers: headers(), body: JSON.stringify({ items }),
    });
    const data = await r.json().catch(() => ({}));
    setEditItemsBusy(false);
    if (!r.ok) { showToast(formatApiError(data), false); return; }
    showToast("Order items updated!", true);
    setEditItemsMode(false);
    setEditBillMode(false);
    setSelected(data as CustomerOrderAdminPublic);
    // Refresh active bill and bill history
    const [billsR, billHistR] = await Promise.all([
      fetchApi(apiUrl("customer-bills"), { headers: headersAdmin() }),
      fetchApi(apiUrl(`customer-bills/order/${selected.id}/history`), { headers: headersAdmin() }),
    ]);
    if (billsR.ok) {
      const bills: CustomerBillPublic[] = await billsR.json();
      const b = bills.find((b) => b.customer_order_id === selected.id && (b.bill_status === "active" || !b.bill_status));
      setBillData(b ?? null);
    }
    if (billHistR.ok) {
      const hist: CustomerBillPublic[] = await billHistR.json();
      setBillHistory(hist);
    }
    void load();
  }

  async function submitEditBill() {
    if (!selected || !editBillList.length) return;
    const items = editBillList
      .map(r => ({ catalog_product_id: Number(r.cid), quantity: Number(r.qty), unit_price: r.price ? Number(r.price) : undefined }))
      .filter(i => i.catalog_product_id > 0 && i.quantity > 0);
    if (!items.length) return showToast("Add at least one item", false);
    setEditBillBusy(true);
    const r = await fetchApi(apiUrl(`customer-orders/${selected.id}/edit-items`), {
      method: "PATCH", headers: headers(), body: JSON.stringify({ items }),
    });
    const data = await r.json().catch(() => ({}));
    setEditBillBusy(false);
    if (!r.ok) { showToast(formatApiError(data), false); return; }
    showToast("Bill updated! History saved.", true);
    setEditBillMode(false);
    setSelected(data as CustomerOrderAdminPublic);
    const [billsR, billHistR] = await Promise.all([
      fetchApi(apiUrl("customer-bills"), { headers: headersAdmin() }),
      fetchApi(apiUrl(`customer-bills/order/${selected.id}/history`), { headers: headersAdmin() }),
    ]);
    if (billsR.ok) {
      const bills: CustomerBillPublic[] = await billsR.json();
      const b = bills.find((b) => b.customer_order_id === selected.id && (b.bill_status === "active" || !b.bill_status));
      setBillData(b ?? null);
    }
    if (billHistR.ok) setBillHistory(await billHistR.json());
    void load();
  }

  async function openOrder(o: CustomerOrderAdminPublic) {
    setSelected(o);
    setEditStatus(o.status);
    setSelectedFreightVendorId("");
    setEditItemsMode(false); setShowVersions(false);
    setBillMsg(""); setSaveMsg(""); setShowBillForm(false);
    setBillData(null); setShowBillModal(false); setCreditSummary(null);
    setBillSeriesId(""); setItemOverrides({}); setZeroRateConfirmed(false); setShowZeroRateBanner(false);
    setBillNarration(o.customer_notes?.trim() || "");
    setAdditionalCharges([]);
    setDrawerOpen(true);
    setEditBillMode(false); setShowBillHistory(false); setBillHistory([]);
    // Fetch existing bill, bill series, credit summary in parallel
    const [billsR, seriesR, creditR, billHistR] = await Promise.all([
      fetchApi(apiUrl("customer-bills"), { headers: headersAdmin() }),
      fetchApi(apiUrl("bill-series"), { headers: headersAdmin() }),
      o.customer_id ? fetchApi(apiUrl(`customers/${o.customer_id}/credit-summary`), { headers: headersAdmin() }) : Promise.resolve(null),
      fetchApi(apiUrl(`customer-bills/order/${o.id}/history`), { headers: headersAdmin() }),
    ]);
    if (billsR.ok) {
      const bills: CustomerBillPublic[] = await billsR.json();
      const b = bills.find((b) => b.customer_order_id === o.id && (b.bill_status === "active" || !b.bill_status));
      if (b) setBillData(b);
    }
    if (billHistR?.ok) {
      const hist: CustomerBillPublic[] = await billHistR.json();
      setBillHistory(hist);
    }
    if (seriesR.ok) {
      const sl: BillSeries[] = await seriesR.json();
      setBillSeriesList(sl.filter((s) => s.is_active && s.current_num < s.end_num));
    }
    if (creditR?.ok) setCreditSummary(await creditR.json());
  }

  async function saveOrder(overrideStatus?: string) {
    if (!selected) return;
    const targetStatus = overrideStatus ?? editStatus;
    setSaving(true); setSaveMsg("");
    const body: Record<string, unknown> = {
      status: overrideStatus ?? selected.status,
    };
    const r = await fetchApi(apiUrl(`customer-orders/${selected.id}`), { method: "PATCH", headers: headers(), body: JSON.stringify(body) });
    const data = await r.json().catch(() => ({}));
    setSaving(false);
    if (!r.ok) { setSaveMsg(formatApiError(data)); return; }
    const updated = data as CustomerOrderAdminPublic;
    setSelected(updated);
    setEditStatus(updated.status);
    showToast("Saved.", true);

    // If shipping with a selected freight vendor + freight amount, record ledger entry
    const finalStatus = overrideStatus ?? editStatus;
    if (finalStatus === "closed" && selectedFreightVendorId && billData) {
      const freightAmt = billData.totals?.freight_charges;
      if (freightAmt && Number(freightAmt) > 0) {
        await fetchApi(apiUrl("freight-vendors/ledger"), {
          method: "POST",
          headers: headers(),
          body: JSON.stringify({
            freight_vendor_id: Number(selectedFreightVendorId),
            entry_date: new Date().toISOString().slice(0, 10),
            entry_type: "charge",
            amount: Number(freightAmt),
            reference: `Order #${selected.id}`,
            notes: null,
          }),
        });
      }
    }

    void load();
  }


  function saveDraft() {
    if (!selected) return;
    const draft = { gstEnabled, gstRate, freight, packaging, discount, billSeriesId, billNarration, itemOverrides, partialBillQty };
    localStorage.setItem(`bill_draft_${selected.id}`, JSON.stringify(draft));
    showToast("Draft saved. You can reload it anytime.", true);
  }

  function loadDraft() {
    if (!selected) return;
    const raw = localStorage.getItem(`bill_draft_${selected.id}`);
    if (!raw) { showToast("No draft found for this order.", false); return; }
    try {
      const d = JSON.parse(raw);
      if (d.gstEnabled !== undefined) setGstEnabled(d.gstEnabled);
      if (d.gstRate) setGstRate(d.gstRate);
      if (d.freight) setFreight(d.freight);
      if (d.packaging) setPackaging(d.packaging);
      if (d.discount) setDiscount(d.discount);
      if (d.billSeriesId) setBillSeriesId(d.billSeriesId);
      if (d.billNarration) setBillNarration(d.billNarration);
      if (d.itemOverrides) setItemOverrides(d.itemOverrides);
      if (d.partialBillQty) setPartialBillQty(d.partialBillQty);
      showToast("Draft loaded.", true);
    } catch { showToast("Could not load draft.", false); }
  }

  function hasDraft() {
    if (!selected) return false;
    return !!localStorage.getItem(`bill_draft_${selected.id}`);
  }

  async function submitBillBody(body: Record<string, unknown>) {
    setBillBusy(true); setBillMsg(""); setStockWarning(null); setBillBodyPending(null);
    const r = await fetchApi(apiUrl("customer-bills/generate"), { method: "POST", headers: headers(), body: JSON.stringify(body) });
    const data = await r.json().catch(() => ({})) as Record<string, unknown>;
    setBillBusy(false);
    if (r.status === 409 && (data.detail as Record<string, unknown>)?.duplicate) {
      const detail = data.detail as Record<string, unknown>;
      const msg = String(detail.message || "Duplicate bill detected.");
      if (!window.confirm(`${msg}\n\nProceed anyway and create the bill?`)) return;
      void submitBillBody({ ...body, force_duplicate: true });
      return;
    }
    if (!r.ok) { setBillMsg(formatApiError(data)); return; }
    const bill = data as unknown as CustomerBillPublic;
    setBillData(bill);
    const billLabel = bill.bill_no ? `Bill ${bill.bill_no}` : `Bill #${bill.id}`;
    setBillMsg(`✓ ${billLabel} generated.`);
    setShowBillForm(false);
    if (selected) localStorage.removeItem(`bill_draft_${selected.id}`);
    void load();
    if (selected) {
      const updated = await fetchApi(apiUrl(`customer-orders/${selected.id}`), { headers: headers() });
      if (updated.ok) setSelected(await updated.json());
    }
    // Refresh bill history after generating bill
    if (selected) {
      const bhR = await fetchApi(apiUrl(`customer-bills/order/${selected.id}/history`), { headers: headersAdmin() });
      if (bhR.ok) setBillHistory(await bhR.json());
    }
  }

  async function generateBill() {
    if (!selected) return;

    // Zero-rate check: any item with price 0 (no override_price allowed now)
    const zeroItems = selected.items.filter((it) => Number(it.unit_price) === 0);
    if (zeroItems.length > 0 && !zeroRateConfirmed) {
      setShowZeroRateBanner(true);
      return;
    }

    setShowZeroRateBanner(false);
    const body: Record<string, unknown> = {
      customer_order_id: selected.id,
      gst_enabled: gstEnabled,
      gst_rate_percent: gstEnabled ? Number(gstRate) : 0,
    };
    if (freight.trim()) body.freight_charges = Number(freight);
    if (packaging.trim()) body.packaging_charges = Number(packaging);
    if (discount.trim()) body.discount_percent = Number(discount);
    if (billSeriesId) body.bill_series_id = Number(billSeriesId);
    if (billNarration.trim()) body.narration = billNarration.trim();
    const validAdditional = additionalCharges.filter(c => c.name.trim() && c.amount.trim() && Number(c.amount) > 0);
    if (validAdditional.length) body.additional_charges = validAdditional.map(c => ({ name: c.name.trim(), amount: Number(c.amount) }));

    // Only discount overrides — no price overrides since rate is fixed
    const overridesList = selected.items
      .filter((it) => {
        const ov = itemOverrides[it.catalog_product_id];
        return ov && ov.discount.trim();
      })
      .map((it) => {
        const ov = itemOverrides[it.catalog_product_id];
        return { catalog_product_id: it.catalog_product_id, discount_percent: Number(ov.discount) };
      });
    if (overridesList.length > 0) body.item_overrides = overridesList;

    // Include partial billing quantities if set
    const partialItems = selected.items
      .map(it => ({ catalog_product_id: it.catalog_product_id, quantity: Number(partialBillQty[it.catalog_product_id] ?? it.quantity) }))
      .filter(it => it.quantity > 0);
    const hasPartial = Object.values(partialBillQty).some(v => v.trim() !== "");
    if (hasPartial) body.bill_items = partialItems;

    // Stock check before billing
    setBillBusy(true);
    const itemsToCheck = hasPartial ? partialItems : selected.items.map(it => ({
      catalog_product_id: it.catalog_product_id,
      quantity: Number(partialBillQty[it.catalog_product_id] ?? it.quantity),
    }));
    const stockR = await fetchApi(apiUrl("inventory/stock-check"), {
      method: "POST", headers: headers(),
      body: JSON.stringify({ catalog_product_ids: itemsToCheck.map(i => i.catalog_product_id) }),
    }).catch(() => null);
    setBillBusy(false);

    if (stockR?.ok) {
      const stockData = await stockR.json() as Record<number, number>;
      const lowItems = itemsToCheck
        .map(it => {
          const have = stockData[it.catalog_product_id] ?? 0;
          const item = selected.items.find(i => i.catalog_product_id === it.catalog_product_id);
          return { name: String(item?.name || item?.our_product_id || it.catalog_product_id), need: it.quantity, have };
        })
        .filter(x => x.have < x.need);
      if (lowItems.length > 0) {
        setStockWarning({ items: lowItems });
        setBillBodyPending(body);
        return;
      }
    }

    void submitBillBody(body);
  }

  async function mergeSelectedOrders() {
    if (selectedForMerge.size < 2) return;
    const orderIds = [...selectedForMerge];
    // Validate same customer
    const selectedOrders = orders.filter((o) => orderIds.includes(o.id));
    const customerIds = new Set(selectedOrders.map((o) => o.customer_id));
    if (customerIds.size > 1) {
      showToast("Can only merge orders from the same customer.", false);
      return;
    }
    const customerId = [...customerIds][0];
    setMerging(true);
    const r = await fetchApi(apiUrl("customer-orders/merge"), {
      method: "POST",
      headers: headers(),
      body: JSON.stringify({ customer_id: customerId, order_ids: orderIds }),
    });
    const data = await r.json().catch(() => ({}));
    setMerging(false);
    if (!r.ok) { showToast(formatApiError(data), false); return; }
    showToast("Orders merged successfully.", true);
    setMergeMode(false);
    setSelectedForMerge(new Set());
    void load();
  }

  const filtered = orders.filter((o) => {
    let matchStatus = true;
    if (statusFilter === "received") matchStatus = o.status === "received";
    else if (statusFilter === "closed") matchStatus = o.status === "closed";
    else if (statusFilter) matchStatus = o.status === statusFilter;
    const q = search.toLowerCase();
    const matchSearch = !q || o.customer_name.toLowerCase().includes(q) || o.customer_phone.includes(q) || String(o.id).includes(q);
    return matchStatus && matchSearch;
  });

  const statusCounts = {
    received: orders.filter((o) => o.status === "received").length,
    billed: orders.filter((o) => o.status === "billed").length,
    closed: orders.filter((o) => o.status === "closed").length,
  };

  return (
    <div>
      {toast && (
        <div className={`fixed right-4 top-20 z-[200] rounded-lg px-4 py-3 text-sm font-medium shadow-lg ${toast.ok ? "bg-emerald-600 text-white" : "bg-red-600 text-white"}`}>
          {toast.msg}
        </div>
      )}

      {/* Status filter pills */}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        {[
          { id: "", label: "All", count: orders.length },
          { id: "received", label: "Received", count: statusCounts.received },
          { id: "billed",   label: "Billed",   count: statusCounts.billed },
          { id: "closed",   label: "Closed",   count: statusCounts.closed },
        ].map((s) => (
          <button
            key={s.id}
            type="button"
            onClick={() => setStatusFilter(s.id)}
            className={`rounded-full px-4 py-1.5 text-sm font-medium transition ${
              statusFilter === s.id
                ? "bg-blue-600 text-white shadow-sm"
                : "bg-white text-slate-600 shadow-sm ring-1 ring-slate-200 hover:bg-slate-50"
            }`}
          >
            {s.label} <span className="ml-1 opacity-70">({s.count})</span>
          </button>
        ))}
        <div className="ml-auto flex items-center gap-2">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search customer…"
            className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none"
          />
          <button type="button" onClick={() => void load()} className={BTN_SECONDARY}>↻</button>
          <button
            type="button"
            onClick={() => { setShowOfflineForm(v => !v); setOfflineResult(null); }}
            className={`inline-flex items-center gap-1.5 rounded-lg px-4 py-1.5 text-sm font-semibold transition ${showOfflineForm ? "bg-emerald-600 text-white" : "border border-slate-300 bg-white text-slate-700 hover:bg-slate-50"}`}
          >
            ⚡ Offline Order
          </button>
          <button
            type="button"
            onClick={() => { setMergeMode((v) => !v); setSelectedForMerge(new Set()); }}
            className={`inline-flex items-center gap-1.5 rounded-lg px-4 py-1.5 text-sm font-semibold transition ${mergeMode ? "bg-orange-500 text-white hover:bg-orange-600" : "border border-slate-300 bg-white text-slate-700 hover:bg-slate-50"}`}
          >
            {mergeMode ? "✕ Cancel Merge" : "⊞ Merge Orders"}
          </button>
        </div>
      </div>

      {/* Merge mode banner */}
      {mergeMode && (
        <div className="mb-4 flex items-center gap-3 rounded-xl border border-orange-200 bg-orange-50 px-4 py-3">
          <span className="text-sm text-orange-800 font-medium">Merge mode: select received orders from the same customer</span>
          <span className="ml-auto text-sm font-semibold text-orange-700">{selectedForMerge.size} selected</span>
          {selectedForMerge.size >= 2 && (
            <button
              type="button"
              disabled={merging}
              onClick={() => void mergeSelectedOrders()}
              className="inline-flex items-center gap-1.5 rounded-lg bg-orange-600 px-4 py-1.5 text-sm font-semibold text-white shadow-sm transition hover:bg-orange-700 disabled:opacity-50"
            >
              {merging ? "Merging…" : "Merge Selected"}
            </button>
          )}
        </div>
      )}

      {/* ── Offline Order form ── */}
      {showOfflineForm && (
        <div className="mb-4 rounded-2xl border border-emerald-200 bg-emerald-50 p-5 shadow-sm space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="font-bold text-emerald-800">⚡ Offline / Walk-in Order + Bill (1 step)</h3>
            <button onClick={() => { setShowOfflineForm(false); setOfflineResult(null); }} className="text-slate-400 hover:text-slate-600 text-lg">✕</button>
          </div>

          {offlineResult ? (
            <div className="rounded-xl border border-emerald-300 bg-white px-5 py-5 space-y-4 text-center shadow-sm">
              <div className="text-4xl">✅</div>
              <p className="font-bold text-emerald-700 text-lg">{offlineResult.bill_no ? `Bill ${offlineResult.bill_no} created!` : "Order + Bill created!"}</p>
              {offlineResult.grand_total && <p className="text-slate-600 text-sm">Grand Total: <strong>₹{offlineResult.grand_total}</strong></p>}
              <div className="flex flex-wrap justify-center gap-2 pt-1">
                {offlineResult.bill_id && (
                  <button
                    type="button"
                    onClick={() => triggerPrint(offlineResult.bill_id!, 1)}
                    className="inline-flex items-center gap-1 rounded-lg bg-slate-700 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800"
                  >
                    🖨️ Print Bill
                  </button>
                )}
                {offlineResult.document_url && (
                  <a href={offlineResult.document_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50">
                    ⬇ Download PDF
                  </a>
                )}
                <button type="button" onClick={() => setOfflineResult(null)} className="inline-flex items-center gap-1 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-700">
                  + New Order
                </button>
              </div>
            </div>
          ) : (
            <>

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div className="col-span-2">
              <label className={LABEL}>Customer *</label>
              <select value={offlineCustomerId} onChange={e => setOfflineCustomerId(e.target.value)} className={INPUT}>
                <option value="">— select —</option>
                {customers.map(c => <option key={c.id} value={c.id}>{c.company_name || c.name} {c.phone ? `(${c.phone})` : ""}</option>)}
              </select>
            </div>
            <div>
              <label className={LABEL}>Discount %</label>
              <input type="number" min="0" max="100" value={offlineDiscount} onChange={e => setOfflineDiscount(e.target.value)} placeholder="0" className={INPUT} />
            </div>
            <div className="flex items-end gap-2">
              <label className="flex items-center gap-1.5 text-sm cursor-pointer">
                <input type="checkbox" checked={offlineGst} onChange={e => setOfflineGst(e.target.checked)} className="h-4 w-4 rounded" />
                GST
              </label>
              {offlineGst && <input type="number" value={offlineGstRate} onChange={e => setOfflineGstRate(e.target.value)} className="w-16 rounded-lg border border-slate-300 px-2 py-2 text-sm" placeholder="18" />}
            </div>
            <div>
              <label className={LABEL}>Bill Series</label>
              <select value={offlineSeriesId} onChange={e => setOfflineSeriesId(e.target.value)} className={INPUT}>
                <option value="">(none)</option>
                {billSeriesList.map(s => <option key={s.id} value={s.id}>{s.name} – {s.prefix}</option>)}
              </select>
            </div>
            <div>
              <label className={LABEL}>Notes (internal)</label>
              <input value={offlineNotes} onChange={e => setOfflineNotes(e.target.value)} placeholder="Optional" className={INPUT} />
            </div>
            <div className="col-span-2 sm:col-span-4">
              <label className={LABEL}>Narration (printed on bill)</label>
              <input value={offlineNarration} onChange={e => setOfflineNarration(e.target.value)} placeholder="e.g. Against PO no. 123 / Payment by cash…" className={INPUT} />
            </div>
          </div>

          {/* Item rows */}
          <div>
            <label className={LABEL}>Items *</label>
            {offlineItems.map((row, idx) => (
              <div key={idx} className="mb-2 flex flex-wrap gap-2">
                <select value={row.cid}
                  onChange={async e => {
                    const newCid = e.target.value;
                    setOfflineItems(prev => {
                      const updated = prev.map((r, i) => i === idx ? { ...r, cid: newCid, price: catalog.find(c => String(c.id) === newCid)?.selling_price?.toString() || "" } : r);
                      // Auto-add new blank row if this was the last row
                      if (newCid && idx === prev.length - 1) {
                        updated.push({ cid: "", qty: "", price: "" });
                      }
                      return updated;
                    });
                    if (newCid && !(newCid in offlineStockMap)) {
                      const sr = await fetchApi(apiUrl("inventory/stock-check"), {
                        method: "POST", headers: headers(),
                        body: JSON.stringify({ catalog_product_ids: [Number(newCid)] }),
                      }).catch(() => null);
                      if (sr?.ok) {
                        const sd = await sr.json() as Record<string, number>;
                        setOfflineStockMap(m => ({ ...m, [newCid]: sd[Number(newCid)] ?? 0 }));
                      }
                    }
                  }}
                  className="min-w-0 flex-1 rounded-lg border border-slate-300 px-2 py-2 text-sm">
                  <option value="">— product —</option>
                  {catalog.map(c => {
                    const avail = stockMap[String(c.id)];
                    const stockLabel = avail !== undefined ? ` [${avail} avail]` : "";
                    return <option key={c.id} value={c.id}>{c.our_product_id} – {c.name}{stockLabel}</option>;
                  })}
                </select>
                <div className="flex flex-col justify-center">
                  <input type="number" min="1" placeholder="Qty" value={row.qty}
                    onChange={e => setOfflineItems(p => p.map((r, i) => i === idx ? { ...r, qty: e.target.value } : r))}
                    className="w-16 rounded-lg border border-slate-300 px-2 py-2 text-sm" />
                  {row.cid && row.cid in offlineStockMap && (
                    <span className={`text-xs text-center mt-0.5 font-medium ${offlineStockMap[row.cid] <= 0 ? "text-red-500" : offlineStockMap[row.cid] < 5 ? "text-amber-500" : "text-emerald-600"}`}>
                      {offlineStockMap[row.cid] <= 0 ? `${offlineStockMap[row.cid]} avail` : `${offlineStockMap[row.cid]} avail`}
                    </span>
                  )}
                </div>
                <input type="number" min="0" step="0.01" placeholder="Price" value={row.price}
                  onChange={e => setOfflineItems(p => p.map((r, i) => i === idx ? { ...r, price: e.target.value } : r))}
                  className="w-24 rounded-lg border border-slate-300 px-2 py-2 text-sm" />
                {offlineItems.length > 1 && (
                  <button type="button" onClick={() => setOfflineItems(p => p.filter((_, i) => i !== idx))} className="text-red-500 hover:text-red-700 text-lg">×</button>
                )}
              </div>
            ))}
            <button type="button" onClick={() => setOfflineItems(p => [...p, { cid: "", qty: "", price: "" }])}
              className="text-xs text-blue-600 hover:underline">+ Add item</button>
          </div>

          {/* Additional Charges */}
          <div>
            <label className={LABEL}>Additional Charges (e.g. VAT, Handling…)</label>
            {offlineAdditionalCharges.map((ac, idx) => (
              <div key={idx} className="mb-1.5 flex gap-2 items-center">
                <input
                  type="text"
                  placeholder="Charge name (e.g. VAT)"
                  value={ac.name}
                  onChange={e => setOfflineAdditionalCharges(p => p.map((c, i) => i === idx ? { ...c, name: e.target.value } : c))}
                  className="flex-1 rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
                />
                <input
                  type="number" min="0" step="0.01"
                  placeholder="Amount ₹"
                  value={ac.amount}
                  onChange={e => setOfflineAdditionalCharges(p => p.map((c, i) => i === idx ? { ...c, amount: e.target.value } : c))}
                  className="w-28 rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
                />
                <button type="button" onClick={() => setOfflineAdditionalCharges(p => p.filter((_, i) => i !== idx))} className="text-red-500 hover:text-red-700">×</button>
              </div>
            ))}
            <button type="button" onClick={() => setOfflineAdditionalCharges(p => [...p, { name: "", amount: "" }])} className="text-xs text-blue-600 hover:underline">+ Add charge</button>
          </div>

          {/* Shipping / Freight */}
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 space-y-3">
            <label className={LABEL}>Shipping / Freight</label>
            <div className="flex flex-wrap gap-3 items-end">
              <div>
                <label className="mb-1 block text-xs text-slate-500">Send via</label>
                <select value={offlineShipType} onChange={e => setOfflineShipType(e.target.value as "" | "bus" | "transport")} className="rounded-lg border border-slate-300 px-2 py-2 text-sm focus:border-blue-500 focus:outline-none">
                  <option value="">— none —</option>
                  <option value="bus">Bus</option>
                  <option value="transport">Transport</option>
                </select>
              </div>
              {offlineShipType && (
                <div>
                  <label className="mb-1 block text-xs text-slate-500">{offlineShipType === "bus" ? "Bus" : "Transport"} Charge ₹</label>
                  <input type="number" min="0" value={offlineFreight} onChange={e => setOfflineFreight(e.target.value)} placeholder="0" className="w-32 rounded-lg border border-slate-300 px-2 py-2 text-sm focus:border-blue-500 focus:outline-none" />
                </div>
              )}
              {offlineShipType && offlineFreight && Number(offlineFreight) > 0 && freightVendors.length > 0 && (
                <div>
                  <label className="mb-1 block text-xs text-slate-500">Agent</label>
                  <select value={offlineFreightVendorId} onChange={e => setOfflineFreightVendorId(e.target.value)} className="rounded-lg border border-slate-300 px-2 py-2 text-sm focus:border-blue-500 focus:outline-none">
                    <option value="">— optional —</option>
                    {freightVendors.map(fv => <option key={fv.id} value={fv.id}>{fv.name}</option>)}
                  </select>
                </div>
              )}
              <div>
                <label className="mb-1 block text-xs text-slate-500">Packaging ₹</label>
                <input type="number" min="0" value={offlinePkg} onChange={e => setOfflinePkg(e.target.value)} placeholder="0" className="w-28 rounded-lg border border-slate-300 px-2 py-2 text-sm focus:border-blue-500 focus:outline-none" />
              </div>
            </div>
          </div>

          {/* Live grand total */}
          {(() => {
            const itemsTotal = offlineItems
              .filter(r => r.cid && r.qty && r.price)
              .reduce((sum, r) => sum + Number(r.qty) * Number(r.price), 0);
            if (itemsTotal <= 0) return null;
            const disc = itemsTotal * (offlineDiscount ? Number(offlineDiscount) / 100 : 0);
            const afterDisc = itemsTotal - disc;
            const extraTotal = offlineAdditionalCharges
              .filter(c => c.name.trim() && c.amount.trim())
              .reduce((s, c) => s + Number(c.amount), 0);
            const gross = afterDisc + (offlineFreight ? Number(offlineFreight) : 0) + (offlinePkg ? Number(offlinePkg) : 0) + extraTotal;
            const rounded = Math.round(gross);
            const roundOff = rounded - gross;
            return (
              <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm">
                <div className="flex justify-between text-slate-600">
                  <span>Subtotal</span><span>₹{itemsTotal.toFixed(2)}</span>
                </div>
                {disc > 0 && <div className="flex justify-between text-slate-500"><span>Discount</span><span>-₹{disc.toFixed(2)}</span></div>}
                {offlineFreight && Number(offlineFreight) > 0 && <div className="flex justify-between text-slate-500"><span>{offlineShipType === "bus" ? "Bus charge" : offlineShipType === "transport" ? "Transport charge" : "Freight"}</span><span>₹{Number(offlineFreight).toFixed(2)}</span></div>}
                {offlinePkg && Number(offlinePkg) > 0 && <div className="flex justify-between text-slate-500"><span>Packaging</span><span>₹{Number(offlinePkg).toFixed(2)}</span></div>}
                {extraTotal > 0 && <div className="flex justify-between text-slate-500"><span>Other charges</span><span>₹{extraTotal.toFixed(2)}</span></div>}
                {Math.abs(roundOff) > 0.001 && <div className="flex justify-between text-slate-400"><span>Round off</span><span>{roundOff > 0 ? "+" : ""}₹{roundOff.toFixed(2)}</span></div>}
                <div className="mt-1 flex justify-between border-t border-slate-300 pt-1 font-bold text-slate-800">
                  <span>Grand Total</span><span>₹{rounded.toFixed(2)}</span>
                </div>
              </div>
            );
          })()}

          {offlineStockWarning ? (
            <div className="rounded-xl border border-red-300 bg-red-50 p-3 space-y-2">
              <div className="text-sm font-semibold text-red-700">⚠️ Insufficient Stock</div>
              <div className="text-xs text-red-600 space-y-0.5">
                {offlineStockWarning.items.map((it, i) => (
                  <div key={i}>
                    <strong>{it.name}</strong> — need <strong>{it.need}</strong>, have <strong className="text-red-700">{it.have}</strong>
                  </div>
                ))}
              </div>
              <p className="text-xs text-slate-500">Stock will go negative. Proceed anyway?</p>
              <div className="flex gap-2">
                <button type="button" onClick={() => void submitOfflineOrderBody(offlineStockWarning.pendingBody)} disabled={offlineBusy} className="rounded-lg bg-red-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-red-700 disabled:opacity-50">
                  {offlineBusy ? "Creating…" : "Proceed Anyway"}
                </button>
                <button type="button" onClick={() => setOfflineStockWarning(null)} className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-100">Cancel</button>
              </div>
            </div>
          ) : offlineDupWarning ? (
            <div className="rounded-xl border border-amber-300 bg-amber-50 p-3 space-y-2">
              <div className="text-sm font-semibold text-amber-800">⚠️ Duplicate Detected</div>
              <div className="text-xs text-amber-700">{offlineDupWarning.message}</div>
              <div className="flex gap-2">
                <button type="button" onClick={() => void submitOfflineOrderBody(offlineDupWarning.pendingBody)} disabled={offlineBusy} className="rounded-lg bg-amber-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-amber-700 disabled:opacity-50">
                  {offlineBusy ? "Creating…" : "Proceed Anyway"}
                </button>
                <button type="button" onClick={() => setOfflineDupWarning(null)} className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-100">Cancel</button>
              </div>
            </div>
          ) : (
            <button type="button" onClick={submitOfflineOrder} disabled={offlineBusy}
              className="inline-flex items-center gap-2 rounded-xl bg-emerald-600 px-6 py-2.5 text-sm font-bold text-white shadow hover:bg-emerald-700 disabled:opacity-50">
              {offlineBusy ? "Creating…" : "⚡ Create Order + Bill"}
            </button>
          )}
          </>
          )}
        </div>
      )}

      {loading ? (
        <div className="py-12 text-center text-slate-400">Loading…</div>
      ) : filtered.length === 0 ? (
        <div className="rounded-xl border-2 border-dashed border-slate-200 py-16 text-center text-slate-400">
          <div className="text-4xl">🛒</div>
          <div className="mt-2 font-medium">No orders</div>
        </div>
      ) : (
        <div className="space-y-2">
          {filtered.map((o) => (
            <div
              key={o.id}
              onClick={() => {
                if (mergeMode && o.status === "received") {
                  setSelectedForMerge((prev) => {
                    const next = new Set(prev);
                    if (next.has(o.id)) next.delete(o.id); else next.add(o.id);
                    return next;
                  });
                } else if (!mergeMode) {
                  void openOrder(o);
                }
              }}
              className={`cursor-pointer rounded-xl border bg-white p-4 shadow-sm transition hover:shadow-md ${
                mergeMode && selectedForMerge.has(o.id)
                  ? "border-orange-400 bg-orange-50"
                  : "border-slate-200 hover:border-blue-300"
              }`}
            >
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="flex items-center gap-2">
                    {mergeMode && o.status === "received" && (
                      <input
                        type="checkbox"
                        checked={selectedForMerge.has(o.id)}
                        readOnly
                        className="h-4 w-4 rounded border-slate-300"
                      />
                    )}
                    <span className="font-semibold text-slate-900">{o.customer_name}</span>
                    <span className="font-mono text-xs text-slate-400">{o.customer_phone}</span>
                    {statusBadge(o.status)}
                  </div>
                  <div className="mt-1 text-sm text-slate-500">
                    {o.items.length} item{o.items.length !== 1 ? "s" : ""}
                    {o.items.slice(0, 3).map((it) => ` · ${it.name}`).join("")}
                    {o.items.length > 3 ? ` +${o.items.length - 3} more` : ""}
                  </div>
                  {o.customer_notes && (
                    <div className="mt-1 rounded-md bg-amber-50 px-2 py-1 text-xs text-amber-700">
                      📝 {o.customer_notes}
                    </div>
                  )}
                </div>
                <div className="text-right shrink-0">
                  <div className="text-lg font-bold text-slate-900">₹{o.total_amount}</div>
                  <div className="text-xs text-slate-400">
                    #{o.id} · {new Date(o.created_at).toLocaleDateString(undefined, { dateStyle: "short" })}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Order detail drawer */}
      <Drawer
        open={drawerOpen && !!selected}
        onClose={() => setDrawerOpen(false)}
        title={selected ? `Order #${selected.id} — ${selected.customer_name}` : "Order"}
        subtitle={selected ? `${selected.customer_phone} · ₹${selected.total_amount}` : ""}
        width="max-w-xl"
        footer={
          <div className="flex flex-wrap items-center gap-3">
            {selected && ["received", "billed"].includes(selected.status) && !showBillForm && (
              <button type="button" onClick={async () => {
                  setShowBillForm(true); setPartialBillQty({});
                  if (selected) {
                    const ids = selected.items.map(it => it.catalog_product_id);
                    const sr = await fetchApi(apiUrl("inventory/stock-check"), { method: "POST", headers: headers(), body: JSON.stringify({ catalog_product_ids: ids }) }).catch(() => null);
                    if (sr?.ok) setBillStockMap(await sr.json());
                  }
                }} className="inline-flex items-center gap-1.5 rounded-lg bg-amber-500 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-amber-600">
                🧾 Generate Bill
              </button>
            )}
            {selected && selected.status === "billed" && (
              <button type="button" disabled={saving} onClick={() => void saveOrder("closed")} className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-emerald-700 disabled:opacity-50">
                {saving ? "…" : "✓ Mark Closed (Payment Received)"}
              </button>
            )}
            {saveMsg && <span className="text-sm text-red-600">{saveMsg}</span>}
          </div>
        }
      >
        {selected && (
          <div className="space-y-5">
            {/* Status — read-only, workflow driven */}
            <div className="flex items-center gap-3">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">Status</span>
              {statusBadge(selected.status)}
            </div>

            {/* Customer notes */}
            {selected.customer_notes && (
              <div className="rounded-xl bg-amber-50 p-3">
                <div className="text-xs font-semibold uppercase text-amber-600">Customer note</div>
                <div className="mt-1 text-sm text-amber-800">{selected.customer_notes}</div>
              </div>
            )}

            {/* Items */}
            <div>
              <div className="mb-2 flex items-center justify-between">
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">Items</span>
                <div className="flex gap-2">
                  <button type="button"
                    onClick={() => {
                      setEditItemsMode(v => !v);
                      setEditItemsList(selected.items.map(it => ({ cid: String(it.catalog_product_id), qty: String(it.quantity), price: it.unit_price })));
                      setShowVersions(false);
                    }}
                    className={`rounded-lg px-2 py-1 text-xs font-semibold transition ${editItemsMode ? "bg-blue-600 text-white" : "border border-slate-300 bg-white text-slate-600 hover:bg-slate-50"}`}>
                    ✏️ Edit Items
                  </button>
                  {selected.versions && selected.versions.length > 0 && (
                    <button type="button" onClick={() => setShowVersions(v => !v)}
                      className="rounded-lg border border-slate-300 bg-white px-2 py-1 text-xs font-semibold text-slate-600 hover:bg-slate-50">
                      🕐 History ({selected.versions.length})
                    </button>
                  )}
                </div>
              </div>

              {/* Edit items form */}
              {editItemsMode && (
                <div className="mb-3 rounded-xl border border-blue-200 bg-blue-50 p-3 space-y-2">
                  <p className="text-xs text-blue-700 font-medium">Editing items. If a bill exists, it will be regenerated automatically.</p>
                  {editItemsList.map((row, idx) => (
                    <div key={idx} className="flex gap-2 flex-col">
                      <div className="flex gap-2">
                      <select value={row.cid}
                        onChange={e => setEditItemsList(p => p.map((r, i) => i === idx ? { ...r, cid: e.target.value } : r))}
                        className="min-w-0 flex-1 rounded-lg border border-slate-300 px-2 py-1.5 text-sm">
                        <option value="">— product —</option>
                        {catalog.map(c => {
                          const avail = stockMap[String(c.id)];
                          const stockLabel = avail !== undefined ? ` [${avail} avail]` : "";
                          return <option key={c.id} value={c.id}>{c.our_product_id} – {c.name}{stockLabel}</option>;
                        })}
                      </select>
                      <input type="number" min="1" placeholder="Qty" value={row.qty}
                        onChange={e => setEditItemsList(p => p.map((r, i) => i === idx ? { ...r, qty: e.target.value } : r))}
                        className="w-14 rounded-lg border border-slate-300 px-2 py-1.5 text-sm" />
                      <input type="number" min="0" step="0.01" placeholder="Price" value={row.price}
                        onChange={e => setEditItemsList(p => p.map((r, i) => i === idx ? { ...r, price: e.target.value } : r))}
                        className="w-20 rounded-lg border border-slate-300 px-2 py-1.5 text-sm" />
                      <button type="button" onClick={() => setEditItemsList(p => p.filter((_, i) => i !== idx))} className="text-red-500 hover:text-red-700">×</button>
                      </div>
                      {row.cid && stockMap[row.cid] !== undefined && (
                        <span className={`text-xs font-medium ${stockMap[row.cid] <= 0 ? "text-red-500" : stockMap[row.cid] < 5 ? "text-amber-500" : "text-emerald-600"}`}>
                          Stock: {stockMap[row.cid]} avail
                        </span>
                      )}
                    </div>
                  ))}
                  <div className="flex gap-2">
                    <button type="button" onClick={() => setEditItemsList(p => [...p, { cid: "", qty: "", price: "" }])} className="text-xs text-blue-600 hover:underline">+ Add row</button>
                    <button type="button" onClick={submitEditItems} disabled={editItemsBusy}
                      className="ml-auto rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-bold text-white disabled:opacity-50">
                      {editItemsBusy ? "Saving…" : "Save Changes"}
                    </button>
                    <button type="button" onClick={() => setEditItemsMode(false)} className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs text-slate-600">Cancel</button>
                  </div>
                </div>
              )}

              {/* Version history */}
              {showVersions && selected.versions && (
                <div className="mb-3 rounded-xl border border-slate-200 bg-slate-50 divide-y divide-slate-100 overflow-hidden">
                  {[...selected.versions].reverse().map((v, i) => (
                    <div key={i} className="px-3 py-2.5 text-xs">
                      <div className="flex items-center justify-between">
                        <span className="font-semibold text-slate-700">v{v.version} · {v.event}</span>
                        <span className="text-slate-400">{v.timestamp ? new Date(v.timestamp).toLocaleString("en-IN") : ""}</span>
                      </div>
                      <div className="mt-1 text-slate-500">{v.items?.length || 0} items · ₹{v.total_amount}{v.bill_id ? ` · Bill #${v.bill_id}` : ""}</div>
                    </div>
                  ))}
                </div>
              )}

              <div className="overflow-hidden rounded-xl border border-slate-200">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-200 bg-slate-50 text-xs font-semibold uppercase text-slate-500">
                      <th className="px-3 py-2 text-left">Product</th>
                      <th className="px-3 py-2 text-right">Ordered</th>
                      <th className="px-3 py-2 text-right">Billed</th>
                      <th className="px-3 py-2 text-right">Remaining</th>
                      <th className="px-3 py-2 text-right">Price</th>
                      <th className="px-3 py-2 text-right">Total</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {selected.items.map((it) => {
                      const billed = it.qty_billed ?? 0;
                      const remaining = Math.max(0, it.quantity - billed);
                      return (
                        <tr key={it.catalog_product_id}>
                          <td className="px-3 py-2">
                            <div className="font-medium">{it.name}</div>
                            <div className="text-xs text-slate-400">{it.our_product_id}</div>
                          </td>
                          <td className="px-3 py-2 text-right">{it.quantity}</td>
                          <td className="px-3 py-2 text-right text-amber-600">{billed > 0 ? billed : "—"}</td>
                          <td className="px-3 py-2 text-right font-semibold text-emerald-700">{remaining}</td>
                          <td className="px-3 py-2 text-right">₹{it.unit_price}</td>
                          <td className="px-3 py-2 text-right font-medium">₹{(it.quantity * Number(it.unit_price)).toLocaleString("en-IN")}</td>
                        </tr>
                      );
                    })}
                    <tr className="border-t border-slate-200 bg-slate-50">
                      <td colSpan={5} className="px-3 py-2 text-right font-semibold">Order Total</td>
                      <td className="px-3 py-2 text-right font-bold text-slate-900">₹{selected.total_amount}</td>
                    </tr>
                    {selected.items.some(it => (it.qty_billed ?? 0) > 0) && (() => {
                      const remVal = selected.items.reduce((s, it) => s + Math.max(0, it.quantity - (it.qty_billed ?? 0)) * Number(it.unit_price), 0);
                      return (
                        <tr className="bg-amber-50">
                          <td colSpan={5} className="px-3 py-2 text-right text-xs font-semibold text-amber-700">Remaining to Bill</td>
                          <td className="px-3 py-2 text-right text-sm font-bold text-amber-700">₹{remVal.toLocaleString("en-IN", { minimumFractionDigits: 2 })}</td>
                        </tr>
                      );
                    })()}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Bill info if already billed */}
            {billData && (
              <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-xs font-semibold uppercase text-amber-600">
                      {billData.bill_no ? `Bill ${billData.bill_no}` : `Bill #${billData.id}`}
                    </div>
                    <button
                      type="button"
                      onClick={() => setShowBillModal(true)}
                      className="mt-0.5 text-xl font-bold text-amber-900 underline hover:text-amber-700"
                    >
                      ₹{billData.totals?.grand_total ?? selected?.total_amount}
                    </button>
                    <div className="text-xs text-amber-700">Click to view full breakdown</div>
                  </div>
                  <div className="flex items-center gap-2 flex-wrap">
                    <button
                      type="button"
                      onClick={() => {
                        setEditBillMode(v => !v);
                        setEditBillList(selected.items.map(it => ({ cid: String(it.catalog_product_id), qty: String(it.quantity), price: it.unit_price })));
                        setEditItemsMode(false);
                        setShowBillHistory(false);
                      }}
                      className={`rounded-lg px-2 py-1.5 text-xs font-semibold transition ${editBillMode ? "bg-amber-600 text-white" : "border border-amber-400 bg-white text-amber-700 hover:bg-amber-50"}`}
                    >
                      ✏️ Edit Bill
                    </button>
                    {billHistory.length > 1 && (
                      <button
                        type="button"
                        onClick={() => setShowBillHistory(v => !v)}
                        className="rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-50"
                      >
                        🕐 Bill History ({billHistory.length})
                      </button>
                    )}
                    <select
                      value={printCopies}
                      onChange={e => setPrintCopies(Number(e.target.value))}
                      className="rounded-lg border border-slate-300 px-2 py-1.5 text-xs font-semibold text-slate-700"
                    >
                      <option value={1}>1 copy (Original)</option>
                      <option value={2}>2 copies (+ Duplicate)</option>
                      <option value={3}>3 copies (+ Triplicate)</option>
                      <option value={4}>4 copies (+ Quadruplicate)</option>
                    </select>
                    <button
                      type="button"
                      disabled={printing}
                      onClick={() => triggerPrint(billData.id, printCopies)}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-slate-700 px-3 py-2 text-xs font-semibold text-white shadow-sm hover:bg-slate-800 disabled:opacity-50"
                    >
                      {printing ? "Opening…" : "🖨️ Print"}
                    </button>
                    <a
                      href={`${apiUrl(`customer-bills/${billData.id}/download`)}?x_admin_key=${encodeURIComponent(adminKey)}`}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1.5 rounded-lg bg-amber-600 px-3 py-2 text-xs font-semibold text-white shadow-sm hover:bg-amber-700"
                      onClick={(e) => { e.stopPropagation(); }}
                    >
                      ⬇ Download PDF
                    </a>
                  </div>
                </div>

                {/* Edit Bill form */}
                {editBillMode && (
                  <div className="rounded-lg border border-amber-300 bg-white p-3 space-y-2">
                    <p className="text-xs font-medium text-amber-700">Edit bill items. Order and inventory will be adjusted automatically. History is saved.</p>
                    {editBillList.map((row, idx) => (
                      <div key={idx} className="flex gap-2 items-start flex-col">
                        <div className="flex gap-2 items-center w-full">
                        <select value={row.cid}
                          onChange={e => setEditBillList(p => p.map((r, i) => i === idx ? { ...r, cid: e.target.value } : r))}
                          className="min-w-0 flex-1 rounded-lg border border-slate-300 px-2 py-1.5 text-sm">
                          <option value="">— product —</option>
                          {catalog.map(c => {
                            const avail = stockMap[String(c.id)];
                            const stockLabel = avail !== undefined ? ` [${avail} avail]` : "";
                            return <option key={c.id} value={c.id}>{c.our_product_id} – {c.name}{stockLabel}</option>;
                          })}
                        </select>
                        <div className="flex flex-col">
                          <span className="text-xs text-slate-400 text-center">Qty</span>
                          <input type="number" min="1" placeholder="Qty" value={row.qty}
                            onChange={e => setEditBillList(p => p.map((r, i) => i === idx ? { ...r, qty: e.target.value } : r))}
                            className="w-16 rounded-lg border border-slate-300 px-2 py-1.5 text-sm text-right" />
                        </div>
                        <div className="flex flex-col">
                          <span className="text-xs text-slate-400 text-center">Price ₹</span>
                          <input type="number" min="0" step="0.01" placeholder="Price" value={row.price}
                            onChange={e => setEditBillList(p => p.map((r, i) => i === idx ? { ...r, price: e.target.value } : r))}
                            className="w-22 rounded-lg border border-slate-300 px-2 py-1.5 text-sm text-right" />
                        </div>
                        <div className="flex flex-col">
                          <span className="text-xs text-slate-400 text-center">Line</span>
                          <span className="w-20 text-right text-sm font-medium text-slate-700 py-1.5 px-1">
                            {row.qty && row.price ? `₹${(Number(row.qty) * Number(row.price)).toFixed(2)}` : "—"}
                          </span>
                        </div>
                        <button type="button" onClick={() => setEditBillList(p => p.filter((_, i) => i !== idx))} className="mt-3 text-red-500 hover:text-red-700">×</button>
                        </div>
                        {row.cid && stockMap[row.cid] !== undefined && (
                          <span className={`text-xs font-medium ml-1 ${stockMap[row.cid] <= 0 ? "text-red-500" : stockMap[row.cid] < 5 ? "text-amber-500" : "text-emerald-600"}`}>
                            Stock: {stockMap[row.cid]} avail
                          </span>
                        )}
                      </div>
                    ))}
                    {editBillList.length > 0 && (
                      <div className="text-right text-sm font-bold text-slate-800 border-t border-amber-200 pt-1">
                        Subtotal: ₹{editBillList.reduce((s, r) => s + (Number(r.qty) || 0) * (Number(r.price) || 0), 0).toFixed(2)}
                      </div>
                    )}
                    <div className="flex gap-2 pt-1">
                      <button type="button" onClick={() => setEditBillList(p => [...p, { cid: "", qty: "", price: "" }])} className="text-xs text-blue-600 hover:underline">+ Add row</button>
                      <button type="button" onClick={submitEditBill} disabled={editBillBusy}
                        className="ml-auto rounded-lg bg-amber-600 px-3 py-1.5 text-xs font-bold text-white disabled:opacity-50">
                        {editBillBusy ? "Saving…" : "Save Bill Changes"}
                      </button>
                      <button type="button" onClick={() => setEditBillMode(false)} className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs text-slate-600">Cancel</button>
                    </div>
                  </div>
                )}

                {/* Bill history */}
                {showBillHistory && billHistory.length > 0 && (
                  <div className="rounded-lg border border-slate-200 bg-white divide-y divide-slate-100 overflow-hidden">
                    <div className="px-3 py-2 text-xs font-semibold uppercase text-slate-500 bg-slate-50">Bill History</div>
                    {billHistory.map((bh, i) => (
                      <div key={bh.id} className={`px-3 py-2 text-xs ${bh.bill_status === "active" ? "bg-emerald-50" : "text-slate-400"}`}>
                        <div className="flex items-center justify-between">
                          <span className={`font-semibold ${bh.bill_status === "active" ? "text-emerald-700" : "line-through"}`}>
                            {bh.bill_no ? `Bill ${bh.bill_no}` : `Bill #${bh.id}`}
                            {i === 0 ? " (latest)" : ""}
                          </span>
                          <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${bh.bill_status === "active" ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-500"}`}>
                            {bh.bill_status || "active"}
                          </span>
                        </div>
                        <div className="mt-0.5 flex gap-3">
                          <span>₹{bh.totals?.grand_total ?? "—"}</span>
                          {bh.cancelled_reason && <span className="text-red-500">Replaced by edit</span>}
                          {bh.created_at && <span>{new Date(bh.created_at).toLocaleString("en-IN")}</span>}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Credit summary */}
            {creditSummary && creditSummary.credit_limit !== null && (
              <div className={`rounded-xl border p-3 ${Number(creditSummary.remaining) < 0 ? "border-red-200 bg-red-50" : "border-emerald-200 bg-emerald-50"}`}>
                <div className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1">Credit position</div>
                <div className="grid grid-cols-3 gap-2 text-sm">
                  <div><div className="text-xs text-slate-400">Limit</div><div className="font-bold">₹{creditSummary.credit_limit}</div></div>
                  <div><div className="text-xs text-slate-400">Outstanding AR</div><div className="font-bold text-amber-700">₹{creditSummary.outstanding}</div></div>
                  <div><div className="text-xs text-slate-400">Remaining</div><div className={`font-bold ${Number(creditSummary.remaining) < 0 ? "text-red-600" : "text-emerald-700"}`}>₹{creditSummary.remaining}</div></div>
                </div>
              </div>
            )}

            {/* Bill form */}
            {/* Stock warning modal */}
            {stockWarning && (
              <div className="rounded-xl border border-red-300 bg-red-50 p-4 space-y-3">
                <div className="text-sm font-bold text-red-700">⚠️ Insufficient Stock</div>
                <div className="text-xs text-red-600 space-y-1">
                  {stockWarning.items.map((it, i) => (
                    <div key={i} className="flex items-center gap-2">
                      <span className="font-semibold">{it.name}</span>
                      <span>— need <strong>{it.need}</strong>, have <strong className="text-red-700">{it.have}</strong></span>
                    </div>
                  ))}
                </div>
                <div className="text-xs text-slate-500">Some items are low or out of stock. You can still proceed (stock will go negative) or save as draft.</div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => { if (billBodyPending) void submitBillBody(billBodyPending); }}
                    className="px-3 py-1.5 rounded-lg bg-red-600 text-white text-xs font-semibold hover:bg-red-700"
                  >Proceed Anyway</button>
                  <button
                    type="button"
                    onClick={() => { saveDraft(); setStockWarning(null); setBillBodyPending(null); }}
                    className="px-3 py-1.5 rounded-lg bg-slate-600 text-white text-xs font-semibold hover:bg-slate-700"
                  >Save as Draft</button>
                  <button
                    type="button"
                    onClick={() => { setStockWarning(null); setBillBodyPending(null); }}
                    className="px-3 py-1.5 rounded-lg border border-slate-300 text-slate-600 text-xs hover:bg-slate-100"
                  >Cancel</button>
                </div>
              </div>
            )}

            {showBillForm && selected && (
              // Full-page bill modal is rendered outside the drawer — see below
              null
            )}

            {/* Shipment info preserved for legacy orders */}

          </div>
        )}
      </Drawer>

      {/* Bill detail modal */}
      {showBillModal && billData && selected && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-lg rounded-2xl bg-white shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
              <div>
                <div className="text-base font-bold text-slate-900">Bill #{billData.id} — Order #{billData.customer_order_id}</div>
                <div className="text-sm text-slate-500">{selected.customer_name}</div>
              </div>
              <button type="button" onClick={() => setShowBillModal(false)} className="text-slate-400 hover:text-slate-600 text-xl">✕</button>
            </div>
            <div className="px-6 py-4 space-y-2">
              <div className="overflow-hidden rounded-xl border border-slate-200">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-200 bg-slate-50 text-xs font-semibold uppercase text-slate-500">
                      <th className="px-3 py-2 text-left">Item</th>
                      <th className="px-3 py-2 text-right">Qty</th>
                      <th className="px-3 py-2 text-right">Rate</th>
                      <th className="px-3 py-2 text-right">Total</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {selected.items.map((it) => (
                      <tr key={it.catalog_product_id}>
                        <td className="px-3 py-2"><div className="font-medium">{it.name}</div><div className="text-xs text-slate-400">{it.our_product_id}</div></td>
                        <td className="px-3 py-2 text-right">{it.quantity}</td>
                        <td className="px-3 py-2 text-right">₹{it.unit_price}</td>
                        <td className="px-3 py-2 text-right font-medium">₹{it.line_total}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 space-y-1.5 text-sm">
                {(billData.totals?.subtotal_inclusive ?? billData.totals?.subtotal) !== undefined && <div className="flex justify-between"><span className="text-slate-500">Subtotal</span><span>₹{String(billData.totals?.subtotal_inclusive ?? billData.totals?.subtotal ?? "")}</span></div>}
                {Number(billData.totals?.discount_amount ?? 0) > 0 && <div className="flex justify-between"><span className="text-slate-500">Discount</span><span className="text-red-600">−₹{billData.totals?.discount_amount}</span></div>}
                {Number(billData.totals?.freight_charges ?? 0) > 0 && <div className="flex justify-between"><span className="text-slate-500">Freight</span><span>₹{billData.totals?.freight_charges}</span></div>}
                {Number(billData.totals?.packaging_charges ?? 0) > 0 && <div className="flex justify-between"><span className="text-slate-500">Packaging</span><span>₹{billData.totals?.packaging_charges}</span></div>}
                {Number(billData.totals?.gst_amount ?? 0) > 0 && <div className="flex justify-between"><span className="text-slate-500">GST ({billData.gst_rate_percent ?? 0}%)</span><span>₹{billData.totals?.gst_amount}</span></div>}
                {Array.isArray(billData.totals?.additional_charges) && (billData.totals.additional_charges as {name:string;amount:string}[]).map((ac, i) => (
                  <div key={i} className="flex justify-between"><span className="text-slate-500">{ac.name}</span><span>₹{ac.amount}</span></div>
                ))}
                <div className="flex justify-between border-t border-slate-200 pt-1.5 font-bold text-slate-900"><span>Grand total</span><span>₹{billData.totals?.grand_total}</span></div>
              </div>
            </div>
            <div className="flex flex-wrap justify-end gap-3 border-t border-slate-200 px-6 py-4 items-center">
              <select
                value={printCopies}
                onChange={e => setPrintCopies(Number(e.target.value))}
                className="rounded-lg border border-slate-300 px-2 py-2 text-sm font-semibold text-slate-700"
              >
                <option value={1}>1 copy — Original</option>
                <option value={2}>2 copies — Duplicate</option>
                <option value={3}>3 copies — Triplicate</option>
                <option value={4}>4 copies — Quadruplicate</option>
              </select>
              <button
                type="button"
                disabled={printing}
                onClick={() => triggerPrint(billData.id, printCopies)}
                className={BTN_SECONDARY + " disabled:opacity-50"}
              >
                {printing ? "Opening…" : "🖨️ Print Bill"}
              </button>
              <a href={`${apiUrl(`customer-bills/${billData.id}/download`)}?x_admin_key=${encodeURIComponent(adminKey)}`} target="_blank" rel="noreferrer" className={BTN_PRIMARY}>⬇ Download PDF</a>
              <button type="button" onClick={() => setShowBillModal(false)} className={BTN_SECONDARY}>Close</button>
            </div>
          </div>
        </div>
      )}

      {/* ── Full-screen Generate Bill Modal ── */}
      {showBillForm && selected && (() => {
        const billItems = selected.items
          .filter(it => Math.max(0, it.quantity - (it.qty_billed ?? 0)) > 0);
        const overallDiscNum = Number(discount) || 0;
        const useOverallDisc = overallDiscNum > 0;

        const rows = billItems.map(it => {
          const remaining = Math.max(0, it.quantity - (it.qty_billed ?? 0));
          const deliverQty = Number(partialBillQty[it.catalog_product_id] ?? remaining) || remaining;
          const ov = itemOverrides[it.catalog_product_id];
          const basePrice = Number(it.unit_price); // rate is always fixed from the order
          const itemDiscPct = useOverallDisc ? 0 : (ov?.discount.trim() ? Number(ov.discount) : 0);
          const lineTotal = basePrice * deliverQty * (1 - itemDiscPct / 100);
          return { it, remaining, deliverQty, basePrice, itemDiscPct, lineTotal };
        });

        const itemsSubtotal = rows.reduce((s, r) => s + r.lineTotal, 0);
        const afterOverallDisc = useOverallDisc ? itemsSubtotal * (1 - overallDiscNum / 100) : itemsSubtotal;
        const freightNum = Number(freight) || 0;
        const packNum = Number(packaging) || 0;
        const extraNum = additionalCharges.reduce((s, c) => s + (Number(c.amount) || 0), 0);
        const preGst = afterOverallDisc + freightNum + packNum + extraNum;
        // GST is tax-inclusive: extracted from price, not added on top
        const gstRate_ = Number(gstRate) || 0;
        const gstNum = (gstEnabled && gstRate_ > 0) ? preGst - preGst / (1 + gstRate_ / 100) : 0;
        const grandTotal = preGst; // total does NOT change when GST enabled

        const fmt = (v: number) => v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

        return (
          <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 overflow-y-auto py-6 px-4">
            <div className="w-full max-w-4xl rounded-2xl bg-white shadow-2xl">
              {/* Header */}
              <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
                <div>
                  <h2 className="text-lg font-bold text-slate-900">Generate Bill</h2>
                  <p className="text-sm text-slate-500">Order #{selected.id} — {selected.customer_name}</p>
                </div>
                <div className="flex items-center gap-3">
                  {hasDraft() && <button type="button" onClick={loadDraft} className="text-xs text-blue-600 hover:underline">↓ Load Draft</button>}
                  <button type="button" onClick={saveDraft} className="text-xs text-slate-500 hover:text-slate-700">Save Draft</button>
                  <button type="button" onClick={() => { setShowBillForm(false); setPartialBillQty({}); }} className="text-slate-400 hover:text-slate-600 text-xl leading-none">✕</button>
                </div>
              </div>

              <div className="p-6 space-y-6">
                {/* Items table */}
                <div>
                  <div className="mb-2 flex items-center justify-between">
                    <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-500">Items</h3>
                    <p className="text-xs text-slate-400">Adjust &quot;Deliver Now&quot; for partial shipment · Leave blank = all remaining</p>
                  </div>
                  <div className="overflow-hidden rounded-xl border border-slate-200">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="bg-slate-900 text-white">
                          <th className="px-4 py-2.5 text-left font-semibold">Item</th>
                          <th className="px-3 py-2.5 text-right font-semibold">Ordered</th>
                          <th className="px-3 py-2.5 text-right font-semibold">Billed</th>
                          <th className="px-3 py-2.5 text-right font-semibold">Deliver Now</th>
                          <th className="px-3 py-2.5 text-right font-semibold">Rate ₹</th>
                          <th className="px-3 py-2.5 text-right font-semibold">Disc %</th>
                          <th className="px-3 py-2.5 text-right font-semibold">Amount ₹</th>
                        </tr>                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {rows.map(({ it, remaining, deliverQty, basePrice, itemDiscPct, lineTotal }, idx) => {
                          const ov = itemOverrides[it.catalog_product_id] ?? { enabled: false, discount: "" };
                          const avail = billStockMap[it.catalog_product_id];
                          const stockOk = avail === undefined || avail >= (Number(partialBillQty[it.catalog_product_id] ?? remaining) || remaining);
                          return (
                            <tr key={it.catalog_product_id} className={idx % 2 === 1 ? "bg-slate-50" : ""}>
                              <td className="px-4 py-2.5">
                                <div className="font-semibold text-slate-900">{it.our_product_id}</div>
                                <div className="text-xs text-slate-500">{it.name}</div>
                                {avail !== undefined && (
                                  <div className={`mt-0.5 text-xs font-medium ${stockOk ? "text-emerald-600" : "text-red-600"}`}>
                                    {stockOk ? `✓ ${avail} in stock` : `⚠ only ${avail} in stock`}
                                  </div>
                                )}
                              </td>
                              <td className="px-3 py-2.5 text-right tabular-nums text-slate-600">{it.quantity}</td>
                              <td className="px-3 py-2.5 text-right tabular-nums text-amber-600">{it.qty_billed ?? 0}</td>
                              <td className="px-3 py-2.5 text-right">
                                <input
                                  type="number" min="1" max={remaining}
                                  placeholder={String(remaining)}
                                  value={partialBillQty[it.catalog_product_id] ?? ""}
                                  onChange={e => setPartialBillQty(p => ({ ...p, [it.catalog_product_id]: e.target.value }))}
                                  className="w-20 rounded-lg border border-slate-300 px-2 py-1 text-right text-sm focus:border-blue-500 focus:outline-none"
                                />
                              </td>
                              <td className="px-3 py-2.5 text-right tabular-nums text-slate-700">₹{Number(it.unit_price).toLocaleString("en-IN")}</td>
                              <td className="px-3 py-2.5 text-right">
                                <input
                                  type="number" min="0" max="100" step="0.01"
                                  value={ov.discount}
                                  disabled={useOverallDisc}
                                  onChange={e => setItemOverrides(prev => ({ ...prev, [it.catalog_product_id]: { ...ov, enabled: true, discount: e.target.value } }))}
                                  placeholder="0"
                                  className="w-16 rounded-lg border border-slate-300 px-2 py-1 text-right text-sm focus:border-blue-500 focus:outline-none disabled:bg-slate-100 disabled:text-slate-400"
                                />
                              </td>
                              <td className="px-3 py-2.5 text-right font-semibold tabular-nums text-slate-900">₹{fmt(lineTotal)}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* Charges + discounts */}
                <div className="grid grid-cols-2 gap-4">
                  {/* Left: charges */}
                  <div className="space-y-3">
                    <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-500">Charges</h3>

                    {/* Freight agent */}
                    <div>
                      <label className={LABEL}>Freight Agent</label>
                      <select value={selectedFreightVendorId} onChange={e => setSelectedFreightVendorId(e.target.value)} className={INPUT}>
                        <option value="">— None —</option>
                        {freightVendors.map(fv => (
                          <option key={fv.id} value={fv.id}>{fv.name}{Number(fv.balance_due) > 0 ? ` (bal: ₹${fv.balance_due})` : ""}</option>
                        ))}
                      </select>
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className={LABEL}>Freight ₹</label>
                        <input value={freight} onChange={e => setFreight(e.target.value)} type="number" min="0" step="0.01" placeholder="0" className={INPUT} />
                      </div>
                      <div>
                        <label className={LABEL}>Packaging ₹</label>
                        <input value={packaging} onChange={e => setPackaging(e.target.value)} type="number" min="0" step="0.01" placeholder="0" className={INPUT} />
                      </div>
                    </div>

                    {/* Additional charges */}
                    <div>
                      <div className="mb-1 flex items-center justify-between">
                        <label className={LABEL}>Additional Charges</label>
                        <button type="button" onClick={() => setAdditionalCharges(p => [...p, { name: "", amount: "" }])} className="text-xs text-blue-600 hover:underline">+ Add</button>
                      </div>
                      {additionalCharges.map((ac, idx) => (
                        <div key={idx} className="mb-1.5 flex gap-2 items-center">
                          <input type="text" placeholder="Name (e.g. Handling)" value={ac.name}
                            onChange={e => setAdditionalCharges(p => p.map((c, i) => i === idx ? { ...c, name: e.target.value } : c))}
                            className="flex-1 rounded-lg border border-slate-300 px-2 py-1.5 text-sm focus:border-blue-500 focus:outline-none" />
                          <input type="number" min="0" step="0.01" placeholder="₹" value={ac.amount}
                            onChange={e => setAdditionalCharges(p => p.map((c, i) => i === idx ? { ...c, amount: e.target.value } : c))}
                            className="w-24 rounded-lg border border-slate-300 px-2 py-1.5 text-sm" />
                          <button type="button" onClick={() => setAdditionalCharges(p => p.filter((_, i) => i !== idx))} className="text-red-500 hover:text-red-700">×</button>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Right: discount + GST + summary */}
                  <div className="space-y-3">
                    <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-500">Discount &amp; Tax</h3>

                    <div>
                      <label className={LABEL}>Overall Bill Discount %</label>
                      <input value={discount} onChange={e => setDiscount(e.target.value)} type="number" min="0" max="100" step="0.01" placeholder="0 — or use per-item disc above" className={INPUT} />
                      {useOverallDisc && <p className="mt-0.5 text-xs text-amber-700">Per-item discounts disabled when overall discount is set</p>}
                    </div>

                    <div>
                      <label className="flex items-center gap-2 text-sm font-medium text-slate-700">
                        <input type="checkbox" checked={gstEnabled} onChange={e => setGstEnabled(e.target.checked)} className="h-4 w-4 rounded" />
                        GST inclusive (extract from price)
                      </label>
                      <p className="mt-0.5 text-xs text-slate-400">If item is ₹118 at 18% GST → taxable ₹100 + GST ₹18. Total stays ₹118.</p>
                      {gstEnabled && (
                        <div className="mt-1.5 flex items-center gap-2">
                          <input value={gstRate} onChange={e => setGstRate(e.target.value)} type="number" min="0" max="100" placeholder="18"
                            className="w-20 rounded-lg border border-slate-300 px-2 py-2 text-sm" />
                          <span className="text-sm text-slate-500">%</span>
                        </div>
                      )}
                    </div>

                    {/* Live summary */}
                    <div className="rounded-xl bg-slate-50 p-3 space-y-1.5 text-sm mt-2">
                      <div className="flex justify-between text-slate-600"><span>Items subtotal</span><span className="tabular-nums">₹{fmt(itemsSubtotal)}</span></div>
                      {useOverallDisc && <div className="flex justify-between text-amber-700"><span>Discount ({discount}%)</span><span className="tabular-nums">−₹{fmt(itemsSubtotal - afterOverallDisc)}</span></div>}
                      {freightNum > 0 && <div className="flex justify-between text-slate-600"><span>Freight</span><span className="tabular-nums">₹{fmt(freightNum)}</span></div>}
                      {packNum > 0 && <div className="flex justify-between text-slate-600"><span>Packaging</span><span className="tabular-nums">₹{fmt(packNum)}</span></div>}
                      {additionalCharges.filter(c => Number(c.amount) > 0).map((c, i) => (
                        <div key={i} className="flex justify-between text-slate-600"><span>{c.name || "Extra"}</span><span className="tabular-nums">₹{fmt(Number(c.amount))}</span></div>
                      ))}
                      {gstEnabled && gstNum > 0 && <div className="flex justify-between text-slate-600"><span>GST ({gstRate}%) <span className="text-xs text-slate-400">(included in above)</span></span><span className="tabular-nums">₹{fmt(gstNum)}</span></div>}
                      <div className="flex justify-between border-t border-slate-200 pt-1.5 font-bold text-slate-900 text-base"><span>Grand Total</span><span className="tabular-nums">₹{fmt(grandTotal)}</span></div>
                      {gstEnabled && gstNum > 0 && <div className="flex justify-between text-xs text-slate-400"><span>Taxable value (ex-GST)</span><span className="tabular-nums">₹{fmt(grandTotal - gstNum)}</span></div>}
                    </div>
                  </div>
                </div>

                {/* Bill series + narration */}
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className={LABEL}>Bill Series</label>
                    <select value={billSeriesId} onChange={e => setBillSeriesId(e.target.value)} className={INPUT}>
                      <option value="">(none)</option>
                      {billSeriesList.map(s => {
                        const exhausted = s.current_num >= s.end_num;
                        return (
                          <option key={s.id} value={s.id} disabled={exhausted}>
                            {s.name} — {s.prefix}{exhausted ? " (Exhausted)" : ""}
                          </option>
                        );
                      })}
                    </select>
                    {billSeriesId && (() => {
                      const s = billSeriesList.find(s => String(s.id) === billSeriesId);
                      if (!s) return null;
                      return s.current_num >= s.end_num
                        ? <p className="mt-0.5 text-xs font-semibold text-red-600">⚠ Series exhausted</p>
                        : <p className="mt-0.5 text-xs text-amber-700">Next: <strong>{s.prefix}{s.current_num + 1}</strong> ({s.end_num - s.current_num} left)</p>;
                    })()}
                  </div>
                  <div>
                    <label className={LABEL}>Narration (printed on bill)</label>
                    <input value={billNarration} onChange={e => setBillNarration(e.target.value)} placeholder="Auto-filled from customer note" className={INPUT} />
                  </div>
                </div>

                {/* Zero-rate warning */}
                {showZeroRateBanner && (
                  <div className="rounded-lg border border-red-200 bg-red-50 p-3">
                    <p className="text-sm font-medium text-red-800">⚠ Some items have ₹0 rate. Continue?</p>
                    <div className="mt-2 flex gap-2">
                      <button type="button" onClick={() => { setZeroRateConfirmed(true); setShowZeroRateBanner(false); void generateBill(); }} className="rounded-lg bg-red-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-red-700">Confirm</button>
                      <button type="button" onClick={() => setShowZeroRateBanner(false)} className="rounded-lg border border-red-200 px-3 py-1.5 text-xs font-medium text-red-700 hover:bg-red-100">Cancel</button>
                    </div>
                  </div>
                )}

                {billMsg && <p className="text-sm font-medium text-emerald-700">{billMsg}</p>}

                {/* Actions */}
                <div className="flex items-center gap-3 border-t border-slate-200 pt-4">
                  <button type="button" onClick={() => void generateBill()} disabled={billBusy} className="inline-flex items-center gap-1.5 rounded-xl bg-amber-500 px-6 py-2.5 text-sm font-bold text-white shadow-sm transition hover:bg-amber-600 disabled:opacity-50">
                    {billBusy ? "Generating…" : "🧾 Generate Bill & Send to Customer"}
                  </button>
                  <button type="button" onClick={() => { setShowBillForm(false); setPartialBillQty({}); }} className="rounded-xl border border-slate-300 px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50">
                    Cancel
                  </button>
                </div>
              </div>
            </div>
          </div>
        );
      })()}
    </div>
  );
}

// ─────────────────────────────── PURCHASE ORDERS ───────────────────────────────

