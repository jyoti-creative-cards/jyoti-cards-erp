"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Drawer } from "@/components/Drawer";
import { Badge, Field } from "@/components/erp-ui";
import { apiUrl, authHeaders, fetchApi, formatApiError, jsonAuthHeaders } from "@/lib/api";
import type { AuthState, CityPublic, CustomerPublic, RoutePublic, VendorPublic } from "@/lib/types";

interface StatementEntry {
  date: string;
  type: string;  // "bill" | "payment"
  reference?: string;
  description: string;
  debit: number | null;
  credit: number | null;
  balance: number;
  running_balance?: number | null;
  order_id?: number | null;
  order_status?: string | null;
  bill_id?: number | null;
  bill_no?: string | null;
}
interface CustomerStatementData {
  customer_id: number;
  name: string;
  phone: string;
  company_name: string | null;
  total_billed: number;
  total_paid: number;
  outstanding: number;
  entries: StatementEntry[];
}

const INPUT = "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500";
const LABEL = "mb-1 block text-xs font-semibold text-slate-500 uppercase tracking-wider";
const BTN_PRIMARY = "inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-700 disabled:opacity-50";
const BTN_SECONDARY = "inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm transition hover:bg-slate-50";

function emptyToNull(v: FormDataEntryValue | null): string | null {
  const s = String(v ?? "").trim();
  return s === "" ? null : s;
}

interface Props {
  adminKey: string;
  auth?: AuthState;
}

export function PeopleScreen({ adminKey, auth }: Props) {
  const [tab, setTab] = useState<"customers" | "vendors">("customers");

  const _auth: AuthState = auth ?? (adminKey.trim() ? { type: "admin_key", key: adminKey } : { type: "none" });
  const headers = () => jsonAuthHeaders(_auth);
  const headersAdmin = () => authHeaders(_auth);

  return (
    <div>
      {/* Tab bar */}
      <div className="mb-6 flex gap-2">
        {(["customers", "vendors"] as const).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={`rounded-full px-5 py-2 text-sm font-semibold transition ${
              tab === t ? "bg-blue-600 text-white shadow" : "bg-white text-slate-600 shadow-sm hover:bg-slate-50"
            }`}
          >
            {t === "customers" ? "👥 Customers" : "🏭 Vendors"}
          </button>
        ))}
      </div>

      {tab === "customers" ? (
        <CustomersTab headers={headers} headersAdmin={headersAdmin} adminKey={adminKey} />
      ) : (
        <VendorsTab headers={headers} headersAdmin={headersAdmin} adminKey={adminKey} />
      )}
    </div>
  );
}

// ─────────────────────────────── CUSTOMERS ───────────────────────────────

function CustomersTab({
  headers,
  headersAdmin,
  adminKey,
}: {
  headers: () => Record<string, string>;
  headersAdmin: () => Record<string, string>;
  adminKey: string;
}) {
  const [customers, setCustomers] = useState<CustomerPublic[]>([]);
  const [routes, setRoutes] = useState<RoutePublic[]>([]);
  const [cities, setCities] = useState<CityPublic[]>([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [routeFilter, setRouteFilter] = useState("");
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null);

  // Drawer
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editing, setEditing] = useState<CustomerPublic | null>(null); // null = create mode
  const [saving, setSaving] = useState(false);
  // Statement modal
  const [statementCustomer, setStatementCustomer] = useState<CustomerPublic | null>(null);
  // Controlled city/route for auto-select
  const [selectedCityId, setSelectedCityId] = useState<string>("");
  const [selectedRouteId, setSelectedRouteId] = useState<string>("");

  function openDrawer(c: CustomerPublic | null) {
    setEditing(c);
    setSelectedCityId(c?.city_id ? String(c.city_id) : "");
    setSelectedRouteId(c?.route_id ? String(c.route_id) : "");
    setDrawerOpen(true);
  }

  function onCityChange(cityId: string) {
    setSelectedCityId(cityId);
    if (cityId) {
      const city = cities.find((c) => String(c.id) === cityId);
      if (city?.route_id) setSelectedRouteId(String(city.route_id));
    }
  }

  const showToast = (msg: string, ok: boolean) => {
    setToast({ msg, ok });
    setTimeout(() => setToast(null), 3500);
  };

  const load = useCallback(async () => {
    if (!adminKey.trim()) return;
    setLoading(true);
    const [cr, rr, cir] = await Promise.all([
      fetchApi(apiUrl("customers"), { headers: headersAdmin() }),
      fetchApi(apiUrl("routes"), { headers: headersAdmin() }),
      fetchApi(apiUrl("cities"), { headers: headersAdmin() }),
    ]);
    if (cr.ok) setCustomers(await cr.json());
    if (rr.ok) setRoutes(await rr.json());
    if (cir.ok) setCities(await cir.json());
    setLoading(false);
  }, [adminKey]);

  useEffect(() => { void load(); }, [load]);

  const filtered = customers.filter((c) => {
    const q = search.toLowerCase();
    const matchSearch = !q || c.name.toLowerCase().includes(q) || c.phone.includes(q) || (c.alias ?? "").toLowerCase().includes(q);
    const matchRoute = !routeFilter || String(c.route_id) === routeFilter;
    return matchSearch && matchRoute;
  });

  async function onSave(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!adminKey.trim()) return;
    setSaving(true);
    const fd = new FormData(e.currentTarget);
    const body: Record<string, unknown> = {
      name: fd.get("name"),
      phone: fd.get("phone"),
      company_name: emptyToNull(fd.get("company_name")),
      alias: emptyToNull(fd.get("alias")),
      address: emptyToNull(fd.get("address")),
      secondary_phone: emptyToNull(fd.get("secondary_phone")),
      city_id: selectedCityId ? Number(selectedCityId) : null,
      route_id: selectedRouteId ? Number(selectedRouteId) : null,
      credit_limit: emptyToNull(fd.get("credit_limit")),
      credit_override: fd.get("credit_override") === "on",
    };
    const pw = fd.get("password");
    if (pw && String(pw).trim()) body.password = String(pw).trim();

    const url = editing ? apiUrl(`customers/${editing.id}`) : apiUrl("customers");
    const method = editing ? "PATCH" : "POST";
    const r = await fetchApi(url, { method, headers: headers(), body: JSON.stringify(body) });
    const data = await r.json().catch(() => ({}));
    setSaving(false);
    if (!r.ok) { showToast(formatApiError(data), false); return; }
    showToast(editing ? "Saved." : "Customer created.", true);
    setDrawerOpen(false);
    void load();
  }

  async function delCustomer(id: number) {
    if (!confirm("Delete this customer?")) return;
    const r = await fetchApi(apiUrl(`customers/${id}`), { method: "DELETE", headers: headersAdmin() });
    if (r.ok) { showToast("Deleted.", true); void load(); }
    else showToast("Delete failed.", false);
  }

  const routeName = (id: number | null) => routes.find((r) => r.id === id)?.name ?? "";
  const cityName = (id: number | null) => cities.find((c) => c.id === id)?.name ?? "";

  return (
    <div>
      {/* Toast */}
      {toast && (
        <div className={`fixed right-4 top-20 z-50 rounded-lg px-4 py-3 text-sm font-medium shadow-lg ${toast.ok ? "bg-emerald-600 text-white" : "bg-red-600 text-white"}`}>
          {toast.msg}
        </div>
      )}

      {/* Toolbar */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search name, phone, alias…"
          className="min-w-[200px] flex-1 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none"
        />
        <select
          value={routeFilter}
          onChange={(e) => setRouteFilter(e.target.value)}
          className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none"
        >
          <option value="">All routes</option>
          {routes.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
        </select>
        <button type="button" onClick={() => void load()} className={BTN_SECONDARY}>
          ↻ Refresh
        </button>
        <button type="button" onClick={() => openDrawer(null)} className={BTN_PRIMARY}>
          + New customer
        </button>
      </div>

      {/* Table */}
      {loading ? (
        <div className="py-16 text-center text-slate-400">Loading…</div>
      ) : filtered.length === 0 ? (
        <div className="rounded-xl border-2 border-dashed border-slate-200 py-16 text-center text-slate-400">
          <div className="text-4xl">👥</div>
          <div className="mt-2 font-medium">No customers yet</div>
          <button type="button" onClick={() => openDrawer(null)} className="mt-4 text-sm text-blue-600 underline">
            Add first customer
          </button>
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
                <th className="px-4 py-3 text-left">Name</th>
                <th className="px-4 py-3 text-left">Phone</th>
                <th className="px-4 py-3 text-left">Company</th>
                <th className="px-4 py-3 text-left">Route / City</th>
                <th className="px-4 py-3 text-left">Credit</th>
                <th className="px-4 py-3 text-right">Bills</th>
                <th className="px-4 py-3 text-right">Total Bought</th>
                <th className="px-4 py-3 text-left" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {filtered.map((c) => (
                <tr
                  key={c.id}
                  className="cursor-pointer transition hover:bg-blue-50/40"
                  onClick={() => { openDrawer(c); setDrawerOpen(true); }}
                >
                  <td className="px-4 py-3 font-medium text-slate-900">
                    {c.name}
                    {c.alias && <span className="ml-2 text-xs text-slate-400">({c.alias})</span>}
                  </td>
                  <td className="px-4 py-3 font-mono text-slate-600">{c.phone}</td>
                  <td className="px-4 py-3 text-slate-500">{c.company_name ?? "—"}</td>
                  <td className="px-4 py-3 text-slate-500">
                    {routeName(c.route_id) || cityName(c.city_id) || c.city || "—"}
                  </td>
                  <td className="px-4 py-3">
                    {c.credit_limit ? (
                      <span className="font-medium text-slate-700">₹{c.credit_limit}</span>
                    ) : <span className="text-slate-400">—</span>}
                  </td>
                  <td className="px-4 py-3 text-right text-slate-600">{c.invoice_count ?? "—"}</td>
                  <td className="px-4 py-3 text-right text-slate-600">
                    {c.total_billed ? `₹${Number(c.total_billed).toLocaleString("en-IN")}` : "—"}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-2">
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); setStatementCustomer(c); }}
                        className="text-xs text-blue-600 hover:underline"
                      >
                        Statement
                      </button>
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); void delCustomer(c.id); }}
                        className="text-xs text-red-500 hover:underline"
                      >
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="border-t border-slate-100 px-4 py-2 text-xs text-slate-400">
            {filtered.length} customer{filtered.length !== 1 ? "s" : ""}
          </div>
        </div>
      )}

      {statementCustomer && (
        <StatementModal
          customer={statementCustomer}
          headersAdmin={headersAdmin}
          adminKey={adminKey}
          onClose={() => setStatementCustomer(null)}
        />
      )}

      {/* Drawer */}
      <Drawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        title={editing ? editing.name : "New customer"}
        subtitle={editing ? `ID #${editing.id} · ${editing.phone}` : "Fill in the details below"}
        footer={
          <div className="flex items-center gap-3">
            <button type="submit" form="customer-form" disabled={saving} className={BTN_PRIMARY}>
              {saving ? "Saving…" : editing ? "Save changes" : "Create customer"}
            </button>
            <button type="button" onClick={() => setDrawerOpen(false)} className={BTN_SECONDARY}>Cancel</button>
          </div>
        }
      >
        <form id="customer-form" onSubmit={onSave} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="col-span-2">
              <label className={LABEL}>Full name *</label>
              <input name="name" required defaultValue={editing?.name ?? ""} className={INPUT} />
            </div>
            <div>
              <label className={LABEL}>Phone *</label>
              <input name="phone" required defaultValue={editing?.phone ?? ""} className={INPUT} />
            </div>
            <div>
              <label className={LABEL}>Secondary phone</label>
              <input name="secondary_phone" defaultValue={editing?.secondary_phone ?? ""} className={INPUT} />
            </div>
            <div className="col-span-2">
              <label className={LABEL}>Company name</label>
              <input name="company_name" defaultValue={editing?.company_name ?? ""} className={INPUT} />
            </div>
            <div className="col-span-2">
              <label className={LABEL}>Alias (for quick search)</label>
              <input name="alias" defaultValue={editing?.alias ?? ""} placeholder="e.g. nickname or short name" className={INPUT} />
            </div>
            <div className="col-span-2">
              <label className={LABEL}>Address</label>
              <input name="address" defaultValue={editing?.address ?? ""} className={INPUT} />
            </div>
            <div>
              <label className={LABEL}>Route</label>
              <select name="route_id" value={selectedRouteId} onChange={(e) => setSelectedRouteId(e.target.value)} className={INPUT}>
                <option value="">— none —</option>
                {routes.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
              </select>
            </div>
            <div>
              <label className={LABEL}>City</label>
              <select name="city_id" value={selectedCityId} onChange={(e) => onCityChange(e.target.value)} className={INPUT}>
                <option value="">— none —</option>
                {cities.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>
            <div>
              <label className={LABEL}>Credit limit (₹)</label>
              <input name="credit_limit" type="number" step="0.01" min="0" defaultValue={editing?.credit_limit ?? ""} placeholder="No limit" className={INPUT} />
            </div>
            <div className="col-span-2 flex items-center gap-2 rounded-lg bg-slate-50 p-3">
              <input name="credit_override" type="checkbox" defaultChecked={editing?.credit_override ?? false} className="h-4 w-4 rounded" />
              <span className="text-sm text-slate-700">Allow override — ignore credit limit</span>
            </div>
            {editing && (
              <div className="col-span-2">
                <label className={LABEL}>New password (leave blank to keep)</label>
                <input name="password" type="password" autoComplete="new-password" className={INPUT} />
              </div>
            )}
          </div>
        </form>

        {/* Routes & Cities quick-add (always accessible from customer context) */}
        <div className="mt-8 rounded-xl border border-slate-200 bg-slate-50 p-4">
          <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-500">Manage routes &amp; cities</p>
          <RouteCityQuickAdd routes={routes} cities={cities} headers={headers} onDone={() => void load()} />
        </div>
      </Drawer>
    </div>
  );
}

// ─────────────────────────────── STATEMENT MODAL ───────────────────────────────

function StatementModal({
  customer,
  headersAdmin,
  adminKey,
  onClose,
}: {
  customer: CustomerPublic;
  headersAdmin: () => Record<string, string>;
  adminKey: string;
  onClose: () => void;
}) {
  const [data, setData] = useState<CustomerStatementData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [orderDetail, setOrderDetail] = useState<Record<string, unknown> | null>(null);
  const [orderLoading, setOrderLoading] = useState(false);
  const [entryFilter, setEntryFilter] = useState<"all" | "bills" | "receipts">("all");

  function loadStatement(filter: "all" | "bills" | "receipts") {
    setLoading(true);
    setError("");
    fetchApi(apiUrl(`customers/${customer.id}/statement?filter=${filter}`), { headers: headersAdmin() })
      .then(async (r) => {
        if (!r.ok) { setError("Failed to load statement."); return; }
        setData(await r.json());
      })
      .catch(() => setError("Network error."))
      .finally(() => setLoading(false));
  }

  useEffect(() => { loadStatement("all"); }, [customer.id]); // eslint-disable-line react-hooks/exhaustive-deps

  function downloadPdf() {
    const key = adminKey.trim();
    const url = apiUrl(`customers/${customer.id}/statement/pdf`) + (key ? `?api_key=${encodeURIComponent(key)}` : "");
    window.open(url, "_blank");
  }

  function openOrderDetail(orderId: number) {
    setOrderLoading(true);
    fetchApi(apiUrl(`customer-orders/${orderId}`), { headers: headersAdmin() })
      .then(async (r) => { if (r.ok) setOrderDetail(await r.json()); })
      .catch(() => {})
      .finally(() => setOrderLoading(false));
  }

  const fmt = (n: number | null | undefined) =>
    n != null ? `₹${Number(n).toLocaleString("en-IN")}` : "—";

  const statusColor: Record<string, string> = {
    confirmed: "#2563eb", billed: "#7c3aed", shipped: "#16a34a", cancelled: "#dc2626",
  };

  return (
    <div
      style={{ position: "fixed", inset: 0, zIndex: 60, display: "flex", alignItems: "center", justifyContent: "center", background: "rgba(0,0,0,0.45)" }}
      onClick={onClose}
    >
      <div
        style={{ background: "#fff", borderRadius: 16, width: "min(860px, 95vw)", maxHeight: "90vh", display: "flex", flexDirection: "column", overflow: "hidden", boxShadow: "0 25px 50px rgba(0,0,0,0.25)" }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div style={{ padding: "20px 24px 16px", borderBottom: "1px solid #e2e8f0", display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
          <div>
            <div style={{ fontSize: 17, fontWeight: 700, color: "#0f172a" }}>{customer.name}</div>
            <div style={{ fontSize: 12, color: "#64748b", marginTop: 2 }}>
              {customer.phone}{customer.company_name ? ` · ${customer.company_name}` : ""}
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <button
              type="button"
              onClick={downloadPdf}
              style={{ fontSize: 12, fontWeight: 600, background: "#374151", color: "#fff", border: "none", borderRadius: 8, padding: "7px 14px", cursor: "pointer" }}
            >
              🖨️ Print Statement
            </button>
            <button
              type="button"
              onClick={downloadPdf}
              style={{ fontSize: 12, fontWeight: 600, background: "#1d4ed8", color: "#fff", border: "none", borderRadius: 8, padding: "7px 14px", cursor: "pointer" }}
            >
              ⬇ Download PDF
            </button>
            <button type="button" onClick={onClose} style={{ fontSize: 20, lineHeight: 1, background: "none", border: "none", cursor: "pointer", color: "#94a3b8", padding: "2px 6px" }}>✕</button>
          </div>
        </div>

        {/* Body */}
        <div style={{ overflowY: "auto", flex: 1, padding: "16px 24px" }}>
          {loading && <div style={{ textAlign: "center", padding: "48px 0", color: "#94a3b8" }}>Loading…</div>}
          {error && <div style={{ textAlign: "center", padding: "48px 0", color: "#ef4444" }}>{error}</div>}
          {data && !loading && (
            <>
              {/* Summary cards */}
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 12, marginBottom: 20 }}>
                {[
                  { label: "Total Billed", value: fmt(data.total_billed), color: "#1e293b" },
                  { label: "Total Paid", value: fmt(data.total_paid), color: "#16a34a" },
                  { label: "Outstanding", value: fmt(data.outstanding), color: data.outstanding > 0 ? "#dc2626" : "#16a34a" },
                ].map((s) => (
                  <div key={s.label} style={{ background: "#f8fafc", borderRadius: 10, padding: "14px 16px", textAlign: "center", border: "1px solid #e2e8f0" }}>
                    <div style={{ fontSize: 20, fontWeight: 700, color: s.color }}>{s.value}</div>
                    <div style={{ fontSize: 11, color: "#64748b", marginTop: 3, textTransform: "uppercase", letterSpacing: "0.05em" }}>{s.label}</div>
                  </div>
                ))}
              </div>

              {/* Filter tabs */}
              <div style={{ display: "flex", gap: 6, marginBottom: 14 }}>
                {(["all", "bills", "receipts"] as const).map((f) => (
                  <button
                    key={f}
                    type="button"
                    onClick={() => { setEntryFilter(f); loadStatement(f); }}
                    style={{
                      padding: "5px 14px", borderRadius: 20, fontSize: 12, fontWeight: 600,
                      cursor: "pointer", border: "none",
                      background: entryFilter === f ? "#1d4ed8" : "#f1f5f9",
                      color: entryFilter === f ? "#fff" : "#475569",
                    }}
                  >
                    {f === "all" ? "All" : f === "bills" ? "Sales (Bills)" : "Receipts (Payments)"}
                  </button>
                ))}
              </div>

              <div style={{ fontSize: 11, color: "#94a3b8", marginBottom: 8 }}>
                💡 Click any bill row to see order details
              </div>

              {/* Entries table */}
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                <thead>
                  <tr style={{ background: "#f8fafc", borderBottom: "1px solid #e2e8f0" }}>
                    {["Date", "Type", "Description", "Debit (₹)", "Credit (₹)", "Balance (₹)"].map((h, i) => (
                      <th key={h} style={{ padding: "8px 12px", textAlign: i >= 3 ? "right" : "left", fontSize: 11, fontWeight: 600, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.05em" }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.entries.map((en, i) => (
                    <tr
                      key={i}
                      onClick={() => en.order_id && openOrderDetail(en.order_id)}
                      style={{
                        borderBottom: "1px solid #f1f5f9",
                        background: en.debit ? "#fff5f5" : en.credit ? "#f0fdf4" : undefined,
                        cursor: en.order_id ? "pointer" : "default",
                      }}
                      title={en.order_id ? "Click to view order details" : undefined}
                    >
                      <td style={{ padding: "8px 12px", color: "#64748b", whiteSpace: "nowrap" }}>
                        {new Date(en.date).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" })}
                      </td>
                      <td style={{ padding: "8px 12px" }}>
                        {en.type === "bill" ? (
                          <span style={{ fontSize: 11, fontWeight: 600, background: "#dbeafe", color: "#1d4ed8", borderRadius: 6, padding: "2px 8px" }}>
                            {en.bill_no ? `Bill ${en.bill_no}` : "Sale"}
                          </span>
                        ) : (
                          <span style={{ color: "#16a34a", fontWeight: 600, fontSize: 12, background: "#dcfce7", borderRadius: 6, padding: "2px 8px" }}>Payment</span>
                        )}
                      </td>
                      <td style={{ padding: "8px 12px", color: "#1e293b" }}>
                        {en.description}
                        {en.order_id && <span style={{ color: "#94a3b8", fontSize: 11, marginLeft: 6 }}>→ view</span>}
                      </td>
                      <td style={{ padding: "8px 12px", textAlign: "right", color: en.debit ? "#dc2626" : "#94a3b8", fontWeight: en.debit ? 600 : 400 }}>
                        {en.debit ? fmt(en.debit) : "—"}
                      </td>
                      <td style={{ padding: "8px 12px", textAlign: "right", color: en.credit ? "#16a34a" : "#94a3b8", fontWeight: en.credit ? 600 : 400 }}>
                        {en.credit ? fmt(en.credit) : "—"}
                      </td>
                      <td style={{ padding: "8px 12px", textAlign: "right", fontWeight: 700, color: "#0f172a" }}>
                        {fmt(en.running_balance ?? en.balance)}
                      </td>
                    </tr>
                  ))}
                  {data.entries.length === 0 && (
                    <tr><td colSpan={6} style={{ padding: "48px 0", textAlign: "center", color: "#94a3b8" }}>No transactions yet.</td></tr>
                  )}
                </tbody>
              </table>
            </>
          )}
        </div>
      </div>

      {/* Order detail popup */}
      {(orderLoading || orderDetail) && (
        <div
          style={{ position: "fixed", inset: 0, zIndex: 70, display: "flex", alignItems: "center", justifyContent: "center", background: "rgba(0,0,0,0.5)" }}
          onClick={() => { setOrderDetail(null); setOrderLoading(false); }}
        >
          <div
            style={{ background: "#fff", borderRadius: 14, width: "min(560px, 95vw)", maxHeight: "85vh", overflow: "auto", boxShadow: "0 20px 40px rgba(0,0,0,0.3)", padding: 0 }}
            onClick={(e) => e.stopPropagation()}
          >
            {orderLoading && <div style={{ padding: "48px 0", textAlign: "center", color: "#94a3b8" }}>Loading order…</div>}
            {orderDetail && !orderLoading && (() => {
              const o = orderDetail as Record<string, unknown>;
              const items = Array.isArray(o.items) ? o.items as Record<string, unknown>[] : [];
              const st = String(o.status ?? "");
              return (
                <>
                  <div style={{ padding: "16px 20px 12px", borderBottom: "1px solid #e2e8f0", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <div>
                      <div style={{ fontWeight: 700, fontSize: 15, color: "#0f172a" }}>Order #{String(o.id)}</div>
                      <span style={{ fontSize: 11, fontWeight: 600, background: `${statusColor[st] ?? "#64748b"}18`, color: statusColor[st] ?? "#64748b", borderRadius: 6, padding: "2px 8px", textTransform: "capitalize", marginTop: 4, display: "inline-block" }}>{st}</span>
                    </div>
                    <button onClick={() => { setOrderDetail(null); setOrderLoading(false); }} style={{ background: "none", border: "none", fontSize: 20, cursor: "pointer", color: "#94a3b8" }}>✕</button>
                  </div>
                  <div style={{ padding: "16px 20px" }}>
                    <div style={{ fontSize: 12, color: "#64748b", marginBottom: 12 }}>
                      {o.created_at ? new Date(String(o.created_at)).toLocaleString("en-IN") : ""}
                      {o.notes ? ` · Notes: ${String(o.notes)}` : ""}
                    </div>
                    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                      <thead>
                        <tr style={{ background: "#f8fafc" }}>
                          {["Item", "Qty", "Rate", "Total"].map((h, i) => (
                            <th key={h} style={{ padding: "6px 10px", textAlign: i > 0 ? "right" : "left", fontSize: 11, fontWeight: 600, color: "#64748b", borderBottom: "1px solid #e2e8f0" }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {items.map((it, idx) => (
                          <tr key={idx} style={{ borderBottom: "1px solid #f1f5f9" }}>
                            <td style={{ padding: "7px 10px", color: "#1e293b" }}>{String(it.name ?? it.our_product_id ?? it.catalog_product_id)}</td>
                            <td style={{ padding: "7px 10px", textAlign: "right", color: "#475569" }}>{String(it.quantity)}</td>
                            <td style={{ padding: "7px 10px", textAlign: "right", color: "#475569" }}>₹{Number(it.unit_price ?? it.selling_price ?? 0).toLocaleString("en-IN")}</td>
                            <td style={{ padding: "7px 10px", textAlign: "right", fontWeight: 600, color: "#0f172a" }}>₹{Number(it.line_total ?? 0).toLocaleString("en-IN")}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <div style={{ marginTop: 12, textAlign: "right", fontWeight: 700, fontSize: 15, color: "#0f172a" }}>
                      Total: ₹{Number(o.total_amount ?? 0).toLocaleString("en-IN")}
                    </div>
                    {!!o.shipment_receipt && (
                      <div style={{ marginTop: 8, fontSize: 12, color: "#64748b" }}>
                        📦 Shipment: {String(o.shipment_receipt)}{o.shipment_contact ? ` · ${String(o.shipment_contact)}` : ""}
                        {o.shipment_notes ? ` · ${String(o.shipment_notes)}` : ""}
                      </div>
                    )}
                  </div>
                </>
              );
            })()}
          </div>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────── VENDORS ───────────────────────────────

function VendorsTab({
  headers,
  headersAdmin,
  adminKey,
}: {
  headers: () => Record<string, string>;
  headersAdmin: () => Record<string, string>;
  adminKey: string;
}) {
  const [vendors, setVendors] = useState<VendorPublic[]>([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editing, setEditing] = useState<VendorPublic | null>(null);
  const [saving, setSaving] = useState(false);

  const showToast = (msg: string, ok: boolean) => {
    setToast({ msg, ok });
    setTimeout(() => setToast(null), 3500);
  };

  const load = useCallback(async () => {
    if (!adminKey.trim()) return;
    setLoading(true);
    const r = await fetchApi(apiUrl("vendors"), { headers: headersAdmin() });
    if (r.ok) setVendors(await r.json());
    setLoading(false);
  }, [adminKey]);

  useEffect(() => { void load(); }, [load]);

  const filtered = vendors.filter((v) => {
    const q = search.toLowerCase();
    return !q || v.person_name.toLowerCase().includes(q) || v.phone.includes(q) || (v.company_name ?? "").toLowerCase().includes(q) || (v.alias ?? "").toLowerCase().includes(q);
  });

  async function onSave(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!adminKey.trim()) return;
    setSaving(true);
    const fd = new FormData(e.currentTarget);
    const body = {
      person_name: fd.get("person_name"),
      phone: fd.get("phone"),
      company_name: emptyToNull(fd.get("company_name")),
      alias: emptyToNull(fd.get("alias")),
      secondary_phone: emptyToNull(fd.get("secondary_phone")),
      address: emptyToNull(fd.get("address")),
      billing_percentage: emptyToNull(fd.get("billing_percentage")) ? Number(fd.get("billing_percentage")) : null,
      city: emptyToNull(fd.get("city")),
    };
    const url = editing ? apiUrl(`vendors/${editing.id}`) : apiUrl("vendors");
    const method = editing ? "PUT" : "POST";
    const r = await fetchApi(url, { method, headers: headers(), body: JSON.stringify(body) });
    const data = await r.json().catch(() => ({}));
    setSaving(false);
    if (!r.ok) { showToast(formatApiError(data), false); return; }
    showToast(editing ? "Saved." : "Vendor created.", true);
    setDrawerOpen(false);
    void load();
  }

  async function delVendor(id: number) {
    if (!confirm("Delete this vendor?")) return;
    const r = await fetchApi(apiUrl(`vendors/${id}`), { method: "DELETE", headers: headersAdmin() });
    if (r.ok) { showToast("Deleted.", true); void load(); }
    else showToast("Delete failed.", false);
  }

  return (
    <div>
      {toast && (
        <div className={`fixed right-4 top-20 z-50 rounded-lg px-4 py-3 text-sm font-medium shadow-lg ${toast.ok ? "bg-emerald-600 text-white" : "bg-red-600 text-white"}`}>
          {toast.msg}
        </div>
      )}

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search name, phone, company, alias…"
          className="min-w-[200px] flex-1 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none"
        />
        <button type="button" onClick={() => void load()} className={BTN_SECONDARY}>↻ Refresh</button>
        <button type="button" onClick={() => { setEditing(null); setDrawerOpen(true); }} className={BTN_PRIMARY}>
          + New vendor
        </button>
      </div>

      {loading ? (
        <div className="py-16 text-center text-slate-400">Loading…</div>
      ) : filtered.length === 0 ? (
        <div className="rounded-xl border-2 border-dashed border-slate-200 py-16 text-center text-slate-400">
          <div className="text-4xl">🏭</div>
          <div className="mt-2 font-medium">No vendors yet</div>
          <button type="button" onClick={() => { setEditing(null); setDrawerOpen(true); }} className="mt-4 text-sm text-blue-600 underline">
            Add first vendor
          </button>
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
                <th className="px-4 py-3 text-left">Name</th>
                <th className="px-4 py-3 text-left">Phone</th>
                <th className="px-4 py-3 text-left">Company</th>
                <th className="px-4 py-3 text-left">City</th>
                <th className="px-4 py-3 text-left">Bill %</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {filtered.map((v) => (
                <tr
                  key={v.id}
                  className="cursor-pointer transition hover:bg-blue-50/40"
                  onClick={() => { setEditing(v); setDrawerOpen(true); }}
                >
                  <td className="px-4 py-3 font-medium text-slate-900">
                    {v.person_name}
                    {v.alias && <span className="ml-2 text-xs text-slate-400">({v.alias})</span>}
                  </td>
                  <td className="px-4 py-3 font-mono text-slate-600">{v.phone}</td>
                  <td className="px-4 py-3 text-slate-500">{v.company_name ?? "—"}</td>
                  <td className="px-4 py-3 text-slate-500">{v.city ?? "—"}</td>
                  <td className="px-4 py-3 text-slate-500">{v.billing_percentage != null ? `${v.billing_percentage}%` : "—"}</td>
                  <td className="px-4 py-3 text-right">
                    <button
                      type="button"
                      onClick={(e) => { e.stopPropagation(); void delVendor(v.id); }}
                      className="text-xs text-red-500 hover:underline"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="border-t border-slate-100 px-4 py-2 text-xs text-slate-400">
            {filtered.length} vendor{filtered.length !== 1 ? "s" : ""}
          </div>
        </div>
      )}

      <Drawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        title={editing ? editing.person_name : "New vendor"}
        subtitle={editing ? `ID #${editing.id} · ${editing.phone}` : "Fill in the details below"}
        footer={
          <div className="flex gap-3">
            <button type="submit" form="vendor-form" disabled={saving} className={BTN_PRIMARY}>
              {saving ? "Saving…" : editing ? "Save changes" : "Create vendor"}
            </button>
            <button type="button" onClick={() => setDrawerOpen(false)} className={BTN_SECONDARY}>Cancel</button>
          </div>
        }
      >
        <form id="vendor-form" onSubmit={onSave} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="col-span-2">
              <label className={LABEL}>Person name *</label>
              <input name="person_name" required defaultValue={editing?.person_name ?? ""} className={INPUT} />
            </div>
            <div>
              <label className={LABEL}>Phone *</label>
              <input name="phone" required defaultValue={editing?.phone ?? ""} className={INPUT} />
            </div>
            <div>
              <label className={LABEL}>Secondary phone</label>
              <input name="secondary_phone" defaultValue={editing?.secondary_phone ?? ""} className={INPUT} />
            </div>
            <div className="col-span-2">
              <label className={LABEL}>Company name</label>
              <input name="company_name" defaultValue={editing?.company_name ?? ""} className={INPUT} />
            </div>
            <div className="col-span-2">
              <label className={LABEL}>Alias (for quick search)</label>
              <input name="alias" defaultValue={editing?.alias ?? ""} className={INPUT} />
            </div>
            <div className="col-span-2">
              <label className={LABEL}>Address</label>
              <textarea name="address" rows={2} defaultValue={editing?.address ?? ""} className={INPUT} />
            </div>
            <div>
              <label className={LABEL}>City</label>
              <input name="city" defaultValue={editing?.city ?? ""} className={INPUT} />
            </div>
            <div>
              <label className={LABEL}>Billing %</label>
              <input name="billing_percentage" type="number" min={0} max={100} defaultValue={editing?.billing_percentage ?? ""} placeholder="e.g. 2" className={INPUT} />
            </div>
          </div>
        </form>
      </Drawer>
    </div>
  );
}

// ─────────────── Route & City quick-add (inside customer drawer) ──────────────

function RouteCityQuickAdd({
  routes,
  cities,
  headers,
  onDone,
}: {
  routes: RoutePublic[];
  cities: CityPublic[];
  headers: () => Record<string, string>;
  onDone: () => void;
}) {
  const [mode, setMode] = useState<"route" | "city" | null>(null);
  const [saving, setSaving] = useState(false);

  async function addRoute(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setSaving(true);
    const fd = new FormData(e.currentTarget);
    const r = await fetchApi(apiUrl("routes"), { method: "POST", headers: headers(), body: JSON.stringify({ name: fd.get("name"), notes: null }) });
    setSaving(false);
    if (r.ok) { (e.target as HTMLFormElement).reset(); setMode(null); onDone(); }
  }

  async function addCity(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setSaving(true);
    const fd = new FormData(e.currentTarget);
    const route_id = fd.get("route_id") ? Number(fd.get("route_id")) : null;
    const r = await fetchApi(apiUrl("cities"), { method: "POST", headers: headers(), body: JSON.stringify({ name: fd.get("name"), route_id }) });
    setSaving(false);
    if (r.ok) { (e.target as HTMLFormElement).reset(); setMode(null); onDone(); }
  }

  return (
    <div className="space-y-2">
      <div className="flex gap-2">
        <button type="button" onClick={() => setMode(mode === "route" ? null : "route")} className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50">
          + Add route
        </button>
        <button type="button" onClick={() => setMode(mode === "city" ? null : "city")} className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50">
          + Add city
        </button>
      </div>

      {mode === "route" && (
        <form onSubmit={addRoute} className="flex gap-2">
          <input name="name" required placeholder="Route name" className="flex-1 rounded border border-slate-300 px-2 py-1.5 text-xs" />
          <button type="submit" disabled={saving} className="rounded bg-blue-600 px-3 py-1.5 text-xs text-white disabled:opacity-50">Save</button>
        </form>
      )}
      {mode === "city" && (
        <form onSubmit={addCity} className="flex gap-2">
          <input name="name" required placeholder="City name" className="flex-1 rounded border border-slate-300 px-2 py-1.5 text-xs" />
          <select name="route_id" className="rounded border border-slate-300 px-2 py-1.5 text-xs">
            <option value="">— route —</option>
            {routes.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
          </select>
          <button type="submit" disabled={saving} className="rounded bg-blue-600 px-3 py-1.5 text-xs text-white disabled:opacity-50">Save</button>
        </form>
      )}

      {(routes.length > 0 || cities.length > 0) && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {routes.map((r) => (
            <span key={r.id} className="rounded-full bg-blue-100 px-2 py-0.5 text-[10px] font-medium text-blue-700">📍 {r.name}</span>
          ))}
          {cities.map((c) => (
            <span key={c.id} className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-600">🏙 {c.name}</span>
          ))}
        </div>
      )}
    </div>
  );
}
