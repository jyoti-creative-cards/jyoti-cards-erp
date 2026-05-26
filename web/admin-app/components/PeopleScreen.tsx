"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Drawer } from "@/components/Drawer";
import { Badge, Field } from "@/components/erp-ui";
import { apiUrl, fetchApi, formatApiError } from "@/lib/api";
import type { CityPublic, CustomerPublic, RoutePublic, VendorPublic } from "@/lib/types";

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
}

export function PeopleScreen({ adminKey }: Props) {
  const [tab, setTab] = useState<"customers" | "vendors">("customers");

  const headers = () => {
    const h: Record<string, string> = { "Content-Type": "application/json" };
    if (adminKey.trim()) h["X-Admin-Key"] = adminKey.trim();
    return h;
  };
  const headersAdmin = (): Record<string, string> => adminKey.trim() ? { "X-Admin-Key": adminKey.trim() } : {};

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
      city: emptyToNull(fd.get("city")),
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
                  <td className="px-4 py-3 text-right">
                    <button
                      type="button"
                      onClick={(e) => { e.stopPropagation(); void delCustomer(c.id); }}
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
            {filtered.length} customer{filtered.length !== 1 ? "s" : ""}
          </div>
        </div>
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
              <label className={LABEL}>City (free text, if not in list)</label>
              <input name="city" defaultValue={editing?.city ?? ""} placeholder="e.g. Pune" className={INPUT} />
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
