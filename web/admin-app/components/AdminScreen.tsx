"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiUrl, authHeaders, fetchApi, formatApiError, jsonAuthHeaders } from "@/lib/api";
import type { AuthState } from "@/lib/types";
import type { AuditLogEntry, BillSeries } from "@/lib/types";

const INPUT = "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500";
const LABEL = "mb-1 block text-xs font-semibold text-slate-500 uppercase tracking-wider";
const BTN_PRIMARY = "inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-700 disabled:opacity-50";
const BTN_DANGER = "inline-flex items-center gap-1.5 rounded-lg border border-red-200 bg-red-50 px-3 py-1.5 text-xs font-medium text-red-600 transition hover:bg-red-100";
const BTN_SECONDARY = "inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm transition hover:bg-slate-50";
const CARD = "rounded-xl border border-slate-200 bg-white p-5 shadow-sm";

interface Props {
  adminKey: string;
  auth?: AuthState;
}

function hasPerm(auth: AuthState | undefined, perm: string): boolean {
  if (!auth || auth.type === "admin_key") return true;
  if (auth.type === "staff") {
    if (auth.staff.role === "admin") return true;
    return auth.staff.permissions.includes(perm);
  }
  return false;
}

export function AdminScreen({ adminKey, auth }: Props) {
  const _auth: AuthState = auth ?? (adminKey.trim() ? { type: "admin_key", key: adminKey } : { type: "none" });
  const canSetup = hasPerm(auth, "admin.setup");
  const canAudit = hasPerm(auth, "admin.audit");

  const [tab, setTab] = useState<"routes" | "categories" | "series" | "yeargroups" | "billseries" | "auditlog" | "appsettings">(
    canSetup ? "routes" : "auditlog"
  );
  const headersAdmin = () => authHeaders(_auth);
  const headersJson = () => jsonAuthHeaders(_auth);

  const availableTabs = [
    ...(canSetup ? [
      { id: "routes" as const,      label: "🗺️ Routes & Cities" },
      { id: "categories" as const,  label: "🏷️ Categories" },
      { id: "series" as const,      label: "📚 Series" },
      { id: "yeargroups" as const,  label: "📅 Year Groups" },
      { id: "billseries" as const,  label: "🧾 Bill Series" },
      { id: "appsettings" as const, label: "🔐 App Settings" },
    ] : []),
    ...(canAudit ? [{ id: "auditlog" as const, label: "📋 Audit Log" }] : []),
  ];

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-xl font-bold text-slate-800">Setup</h1>
        <p className="mt-1 text-sm text-slate-500">Manage lookup values — routes, cities, categories, series, year groups.</p>
      </div>

      <div className="mb-6 flex flex-wrap gap-2">
        {availableTabs.map((t) => (
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

      {tab === "routes" && canSetup && <RoutesAndCitiesTab headersAdmin={headersAdmin} headersJson={headersJson} adminKey={adminKey} />}
      {tab === "categories" && <SimpleListTab
        label="Category"
        icon="🏷️"
        listEndpoint="catalog/categories"
        listKey="categories"
        createEndpoint="catalog/categories"
        deleteEndpoint={(name) => `catalog/categories/${encodeURIComponent(name)}`}
        headersAdmin={headersAdmin}
        headersJson={headersJson}
      />}
      {tab === "series" && <SimpleListTab
        label="Series"
        icon="📚"
        listEndpoint="catalog/series"
        listKey="series"
        createEndpoint="catalog/series"
        deleteEndpoint={(name) => `catalog/series/${encodeURIComponent(name)}`}
        headersAdmin={headersAdmin}
        headersJson={headersJson}
      />}
      {tab === "yeargroups" && <YearGroupsTab headersAdmin={headersAdmin} headersJson={headersJson} />}
      {tab === "billseries" && <BillSeriesTab headersAdmin={headersAdmin} headersJson={headersJson} />}
      {tab === "appsettings" && canSetup && <AppSettingsTab headersJson={headersJson} />}
      {tab === "auditlog" && <AuditLogTab headersAdmin={headersAdmin} />}
    </div>
  );
}

// ─── Routes & Cities ─────────────────────────────────────────────────────────

interface RouteRow { id: number; name: string; notes?: string; is_active: boolean; }
interface CityRow { id: number; name: string; route_id?: number; is_active: boolean; }

function RoutesAndCitiesTab({
  headersAdmin,
  headersJson,
}: {
  headersAdmin: () => Record<string, string>;
  headersJson: () => Record<string, string>;
  adminKey: string;
}) {
  const [routes, setRoutes] = useState<RouteRow[]>([]);
  const [cities, setCities] = useState<CityRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null);
  const [newRoute, setNewRoute] = useState("");
  const [newCity, setNewCity] = useState("");
  const [newCityRoute, setNewCityRoute] = useState<string>("");

  const showToast = (msg: string, ok: boolean) => {
    setToast({ msg, ok });
    setTimeout(() => setToast(null), 3000);
  };

  const load = useCallback(async () => {
    setLoading(true);
    const [rr, cr] = await Promise.all([
      fetchApi(apiUrl("routes"), { headers: headersAdmin() }),
      fetchApi(apiUrl("cities"), { headers: headersAdmin() }),
    ]);
    if (rr.ok) setRoutes(await rr.json());
    if (cr.ok) setCities(await cr.json());
    setLoading(false);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { void load(); }, [load]);

  async function createRoute() {
    const n = newRoute.trim();
    if (!n) return;
    const r = await fetchApi(apiUrl("routes"), {
      method: "POST",
      headers: headersJson(),
      body: JSON.stringify({ name: n }),
    });
    if (r.ok) { setNewRoute(""); void load(); }
    else { const d = await r.json().catch(() => ({})); showToast(formatApiError(d), false); }
  }

  async function deleteRoute(id: number) {
    if (!confirm("Delete route? Cities linked to it will lose their route.")) return;
    const r = await fetchApi(apiUrl(`routes/${id}`), { method: "DELETE", headers: headersAdmin() });
    if (r.ok) void load();
    else showToast("Delete failed.", false);
  }

  async function createCity() {
    const n = newCity.trim();
    if (!n) return;
    const r = await fetchApi(apiUrl("cities"), {
      method: "POST",
      headers: headersJson(),
      body: JSON.stringify({ name: n, route_id: newCityRoute ? Number(newCityRoute) : null }),
    });
    if (r.ok) { setNewCity(""); setNewCityRoute(""); void load(); }
    else { const d = await r.json().catch(() => ({})); showToast(formatApiError(d), false); }
  }

  async function deleteCity(id: number) {
    if (!confirm("Delete this city?")) return;
    const r = await fetchApi(apiUrl(`cities/${id}`), { method: "DELETE", headers: headersAdmin() });
    if (r.ok) void load();
    else showToast("Delete failed.", false);
  }

  async function assignCityRoute(cityId: number, routeId: string) {
    const r = await fetchApi(apiUrl(`cities/${cityId}`), {
      method: "PATCH",
      headers: headersJson(),
      body: JSON.stringify({ route_id: routeId ? Number(routeId) : null }),
    });
    if (r.ok) void load();
    else showToast("Update failed.", false);
  }

  const routeName = (id?: number) => routes.find((r) => r.id === id)?.name ?? "—";

  return (
    <div className="space-y-6">
      {toast && (
        <div className={`fixed right-4 top-20 z-50 rounded-lg px-4 py-3 text-sm font-medium shadow-lg ${toast.ok ? "bg-emerald-600 text-white" : "bg-red-600 text-white"}`}>
          {toast.msg}
        </div>
      )}

      <div className="grid gap-6 md:grid-cols-2">
        {/* Routes */}
        <div className={CARD}>
          <h3 className="mb-4 text-base font-semibold text-slate-700">Routes</h3>
          <div className="mb-4 flex gap-2">
            <input value={newRoute} onChange={(e) => setNewRoute(e.target.value)} placeholder="New route name" className={INPUT} />
            <button type="button" onClick={() => void createRoute()} className={BTN_PRIMARY}>Add</button>
          </div>
          {loading ? <p className="text-sm text-slate-400">Loading…</p> : (
            <ul className="divide-y divide-slate-100">
              {routes.map((r) => (
                <li key={r.id} className="flex items-center justify-between py-2">
                  <span className="font-medium text-slate-700">{r.name}</span>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-slate-400">{cities.filter((c) => c.route_id === r.id).length} cities</span>
                    <button type="button" onClick={() => void deleteRoute(r.id)} className={BTN_DANGER}>Delete</button>
                  </div>
                </li>
              ))}
              {routes.length === 0 && <li className="py-4 text-center text-sm text-slate-400">No routes yet</li>}
            </ul>
          )}
        </div>

        {/* Cities */}
        <div className={CARD}>
          <h3 className="mb-4 text-base font-semibold text-slate-700">Cities</h3>
          <div className="mb-4 space-y-2">
            <input value={newCity} onChange={(e) => setNewCity(e.target.value)} placeholder="New city name" className={INPUT} />
            <select value={newCityRoute} onChange={(e) => setNewCityRoute(e.target.value)} className={INPUT}>
              <option value="">— no route —</option>
              {routes.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
            </select>
            <button type="button" onClick={() => void createCity()} className={BTN_PRIMARY}>Add City</button>
          </div>
          {loading ? <p className="text-sm text-slate-400">Loading…</p> : (
            <ul className="divide-y divide-slate-100">
              {cities.map((c) => (
                <li key={c.id} className="flex items-center gap-2 py-2">
                  <span className="flex-1 font-medium text-slate-700">{c.name}</span>
                  <select
                    value={c.route_id ?? ""}
                    onChange={(e) => void assignCityRoute(c.id, e.target.value)}
                    className="rounded border border-slate-200 bg-white px-2 py-1 text-xs text-slate-600"
                  >
                    <option value="">— no route —</option>
                    {routes.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
                  </select>
                  <span className="min-w-[60px] text-xs text-slate-400">{routeName(c.route_id)}</span>
                  <button type="button" onClick={() => void deleteCity(c.id)} className={BTN_DANGER}>✕</button>
                </li>
              ))}
              {cities.length === 0 && <li className="py-4 text-center text-sm text-slate-400">No cities yet</li>}
            </ul>
          )}
        </div>
      </div>

      {/* Route → Cities tree */}
      {routes.length > 0 && (
        <div className={CARD}>
          <h3 className="mb-4 text-base font-semibold text-slate-700">Route → Cities map</h3>
          <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-3">
            {routes.map((r) => {
              const rc = cities.filter((c) => c.route_id === r.id);
              return (
                <div key={r.id} className="rounded-lg border border-slate-100 bg-slate-50 p-3">
                  <p className="mb-1 font-semibold text-slate-700">{r.name}</p>
                  {rc.length === 0 ? (
                    <p className="text-xs text-slate-400">No cities assigned</p>
                  ) : (
                    <ul className="space-y-0.5">
                      {rc.map((c) => <li key={c.id} className="text-sm text-slate-600">• {c.name}</li>)}
                    </ul>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Simple List Tab (categories / series) ────────────────────────────────────

function SimpleListTab({
  label,
  icon,
  listEndpoint,
  listKey,
  createEndpoint,
  deleteEndpoint,
  headersAdmin,
  headersJson,
}: {
  label: string;
  icon: string;
  listEndpoint: string;
  listKey: string;
  createEndpoint: string;
  deleteEndpoint: (name: string) => string;
  headersAdmin: () => Record<string, string>;
  headersJson: () => Record<string, string>;
}) {
  const [items, setItems] = useState<string[]>([]);
  const [newItem, setNewItem] = useState("");
  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null);

  const showToast = (msg: string, ok: boolean) => {
    setToast({ msg, ok });
    setTimeout(() => setToast(null), 3000);
  };

  const load = useCallback(async () => {
    setLoading(true);
    const r = await fetchApi(apiUrl(listEndpoint), { headers: headersAdmin() });
    if (r.ok) {
      const d = await r.json();
      setItems(d[listKey] ?? []);
    }
    setLoading(false);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { void load(); }, [load]);

  async function create() {
    const n = newItem.trim();
    if (!n) return;
    const r = await fetchApi(apiUrl(createEndpoint), {
      method: "POST",
      headers: headersJson(),
      body: JSON.stringify({ name: n }),
    });
    if (r.ok) { setNewItem(""); void load(); }
    else {
      // For series/year-groups that don't have a create endpoint, just add locally
      setItems((prev) => [...new Set([...prev, n])].sort());
      setNewItem("");
    }
  }

  async function remove(name: string) {
    if (!confirm(`Delete "${name}"? Products using it keep it; only the label is removed.`)) return;
    const r = await fetchApi(apiUrl(deleteEndpoint(name)), { method: "DELETE", headers: headersAdmin() });
    if (r.ok) void load();
    else showToast("Delete failed (may be in use).", false);
  }

  return (
    <div className={`${CARD} max-w-lg`}>
      {toast && (
        <div className={`fixed right-4 top-20 z-50 rounded-lg px-4 py-3 text-sm font-medium shadow-lg ${toast.ok ? "bg-emerald-600 text-white" : "bg-red-600 text-white"}`}>
          {toast.msg}
        </div>
      )}
      <h3 className="mb-4 text-base font-semibold text-slate-700">{icon} {label} list</h3>
      <div className="mb-4 flex gap-2">
        <input
          value={newItem}
          onChange={(e) => setNewItem(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void create()}
          placeholder={`New ${label.toLowerCase()}…`}
          className={INPUT}
        />
        <button type="button" onClick={() => void create()} className={BTN_PRIMARY}>Add</button>
      </div>
      {loading ? <p className="text-sm text-slate-400">Loading…</p> : (
        <ul className="divide-y divide-slate-100">
          {items.map((item) => (
            <li key={item} className="flex items-center justify-between py-2">
              <span className="text-sm font-medium text-slate-700">{item}</span>
              <button type="button" onClick={() => void remove(item)} className={BTN_DANGER}>✕ Remove</button>
            </li>
          ))}
          {items.length === 0 && <li className="py-4 text-center text-sm text-slate-400">None yet</li>}
        </ul>
      )}
    </div>
  );
}

// ─── Year Groups ──────────────────────────────────────────────────────────────

function YearGroupsTab({
  headersAdmin,
  headersJson,
}: {
  headersAdmin: () => Record<string, string>;
  headersJson: () => Record<string, string>;
}) {
  const [items, setItems] = useState<string[]>([]);
  const [newItem, setNewItem] = useState("");

  const load = useCallback(async () => {
    const r = await fetchApi(apiUrl("catalog/year-groups"), { headers: headersAdmin() });
    if (r.ok) {
      const d = await r.json();
      setItems(d.year_groups ?? []);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { void load(); }, [load]);

  // Year groups are stored on products; we just maintain a local list for the dropdown
  // The canonical list comes from existing products via the year-groups endpoint
  function addLocal() {
    const n = newItem.trim();
    if (!n) return;
    setItems((prev) => [...new Set([...prev, n])].sort().reverse());
    setNewItem("");
  }

  // Suggest current year group
  const currentYear = new Date().getFullYear();
  const suggestedYearGroup = `${currentYear}-${String(currentYear + 1).slice(-2)}`;

  return (
    <div className={`${CARD} max-w-lg`}>
      <h3 className="mb-1 text-base font-semibold text-slate-700">📅 Year Groups</h3>
      <p className="mb-4 text-xs text-slate-500">
        Year groups (e.g., 2026-27) are set on products. The list here shows all year groups in use plus any you add.
        Current suggested: <span className="font-semibold text-blue-600">{suggestedYearGroup}</span>
      </p>
      <div className="mb-4 flex gap-2">
        <input
          value={newItem}
          onChange={(e) => setNewItem(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && addLocal()}
          placeholder={`e.g. ${suggestedYearGroup}`}
          className={INPUT}
        />
        <button type="button" onClick={addLocal} className={BTN_PRIMARY}>Add</button>
      </div>
      {!newItem && items.length === 0 && (
        <button
          type="button"
          onClick={() => { setNewItem(suggestedYearGroup); }}
          className="text-sm text-blue-600 underline"
        >
          Use {suggestedYearGroup}
        </button>
      )}
      <ul className="divide-y divide-slate-100">
        {items.map((item) => (
          <li key={item} className="flex items-center justify-between py-2">
            <span className="text-sm font-medium text-slate-700">{item}</span>
            {item === suggestedYearGroup && (
              <span className="rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700">Current</span>
            )}
          </li>
        ))}
        {items.length === 0 && <li className="py-4 text-center text-sm text-slate-400">No year groups yet</li>}
      </ul>
    </div>
  );
}

// ─── Bill Series ──────────────────────────────────────────────────────────────

function BillSeriesTab({
  headersAdmin,
  headersJson,
}: {
  headersAdmin: () => Record<string, string>;
  headersJson: () => Record<string, string>;
}) {
  const [series, setSeries] = useState<BillSeries[]>([]);
  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null);
  const [saving, setSaving] = useState(false);
  const [name, setName] = useState("");
  const [prefix, setPrefix] = useState("");
  const [startNum, setStartNum] = useState("1");
  const [endNum, setEndNum] = useState("500");

  const showToast = (msg: string, ok: boolean) => {
    setToast({ msg, ok });
    setTimeout(() => setToast(null), 3000);
  };

  const load = useCallback(async () => {
    setLoading(true);
    const r = await fetchApi(apiUrl("bill-series"), { headers: headersAdmin() });
    if (r.ok) setSeries(await r.json());
    setLoading(false);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { void load(); }, [load]);

  async function create(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setSaving(true);
    const body = { name: name.trim(), prefix: prefix.trim(), start_num: Number(startNum), end_num: Number(endNum) };
    const r = await fetchApi(apiUrl("bill-series"), { method: "POST", headers: headersJson(), body: JSON.stringify(body) });
    const data = await r.json().catch(() => ({}));
    setSaving(false);
    if (!r.ok) { showToast(formatApiError(data), false); return; }
    showToast("Bill series created.", true);
    setName(""); setPrefix(""); setStartNum("1"); setEndNum("500");
    void load();
  }

  async function deleteSeries(id: number) {
    if (!confirm("Soft-delete this bill series?")) return;
    const r = await fetchApi(apiUrl(`bill-series/${id}`), { method: "DELETE", headers: headersAdmin() });
    if (r.ok) { void load(); showToast("Deleted.", true); }
    else showToast("Delete failed.", false);
  }

  return (
    <div className="space-y-6 max-w-3xl">
      {toast && (
        <div className={`fixed right-4 top-20 z-50 rounded-lg px-4 py-3 text-sm font-medium shadow-lg ${toast.ok ? "bg-emerald-600 text-white" : "bg-red-600 text-white"}`}>
          {toast.msg}
        </div>
      )}

      <form onSubmit={create} className={CARD}>
        <h3 className="mb-4 text-base font-semibold text-slate-700">Create new bill series</h3>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <div>
            <label className={LABEL}>Name *</label>
            <input value={name} onChange={(e) => setName(e.target.value)} required placeholder="e.g. FY2026" className={INPUT} />
          </div>
          <div>
            <label className={LABEL}>Prefix *</label>
            <input value={prefix} onChange={(e) => setPrefix(e.target.value)} required placeholder="e.g. A" maxLength={10} className={INPUT} />
          </div>
          <div>
            <label className={LABEL}>Start #</label>
            <input value={startNum} onChange={(e) => setStartNum(e.target.value)} type="number" min="1" className={INPUT} />
          </div>
          <div>
            <label className={LABEL}>End #</label>
            <input value={endNum} onChange={(e) => setEndNum(e.target.value)} type="number" min="1" className={INPUT} />
          </div>
        </div>
        <div className="mt-4">
          <button type="submit" disabled={saving} className={BTN_PRIMARY}>{saving ? "Creating…" : "Create series"}</button>
        </div>
      </form>

      <div className={CARD}>
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-base font-semibold text-slate-700">Bill Series</h3>
          <button type="button" onClick={() => void load()} className={BTN_SECONDARY}>↻ Refresh</button>
        </div>
        {loading ? <p className="text-sm text-slate-400">Loading…</p> : (
          <div className="overflow-hidden rounded-xl border border-slate-200">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50 text-xs font-semibold uppercase text-slate-500">
                  <th className="px-4 py-3 text-left">Name</th>
                  <th className="px-4 py-3 text-left">Prefix</th>
                  <th className="px-4 py-3 text-left">Range</th>
                  <th className="px-4 py-3 text-right">Used</th>
                  <th className="px-4 py-3 text-left">Status</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {series.map((s) => {
                  const exhausted = s.current_num >= s.end_num;
                  return (
                    <tr key={s.id}>
                      <td className="px-4 py-3 font-medium">{s.name}</td>
                      <td className="px-4 py-3 font-mono text-blue-700">{s.prefix}</td>
                      <td className="px-4 py-3 text-slate-500">{s.start_num}–{s.end_num}</td>
                      <td className="px-4 py-3 text-right">{s.current_num - s.start_num + 1} / {s.end_num - s.start_num + 1}</td>
                      <td className="px-4 py-3">
                        {exhausted ? (
                          <span className="rounded-full bg-red-100 px-2.5 py-0.5 text-xs font-medium text-red-700">Exhausted</span>
                        ) : s.is_active ? (
                          <span className="rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs font-medium text-emerald-700">Active</span>
                        ) : (
                          <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-600">Inactive</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <button type="button" onClick={() => void deleteSeries(s.id)} className={BTN_DANGER}>Delete</button>
                      </td>
                    </tr>
                  );
                })}
                {series.length === 0 && (
                  <tr><td colSpan={6} className="px-4 py-8 text-center text-slate-400">No bill series yet.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Audit Log ────────────────────────────────────────────────────────────────

function AuditLogTab({
  headersAdmin,
}: {
  headersAdmin: () => Record<string, string>;
}) {
  const [entries, setEntries] = useState<AuditLogEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [entityFilter, setEntityFilter] = useState("");
  const [actionFilter, setActionFilter] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [autoRefresh, setAutoRefresh] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const r = await fetchApi(apiUrl("audit-log?limit=200"), { headers: headersAdmin() });
    if (r.ok) setEntries(await r.json());
    setLoading(false);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    if (autoRefresh) {
      timerRef.current = setInterval(() => void load(), 30000);
    } else {
      if (timerRef.current) clearInterval(timerRef.current);
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [autoRefresh, load]);

  const entityTypes = [...new Set(entries.map((e) => e.entity_type))].sort();
  const actions = [...new Set(entries.map((e) => e.action))].sort();

  const filtered = entries.filter((e) => {
    if (entityFilter && e.entity_type !== entityFilter) return false;
    if (actionFilter && e.action !== actionFilter) return false;
    if (dateFrom && e.created_at < dateFrom) return false;
    if (dateTo && e.created_at > dateTo + "T23:59:59") return false;
    return true;
  });

  function rowBg(action: string) {
    if (action === "DELETE") return "bg-red-50";
    if (action === "CREATE") return "bg-emerald-50";
    if (action === "UPDATE") return "bg-yellow-50";
    return "";
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <select value={entityFilter} onChange={(e) => setEntityFilter(e.target.value)} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm">
          <option value="">All entities</option>
          {entityTypes.map((et) => <option key={et} value={et}>{et}</option>)}
        </select>
        <select value={actionFilter} onChange={(e) => setActionFilter(e.target.value)} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm">
          <option value="">All actions</option>
          {actions.map((a) => <option key={a} value={a}>{a}</option>)}
        </select>
        <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm" />
        <span className="text-slate-400 text-sm">to</span>
        <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm" />
        <button type="button" onClick={() => void load()} className={BTN_SECONDARY}>↻ Refresh</button>
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input type="checkbox" checked={autoRefresh} onChange={(e) => setAutoRefresh(e.target.checked)} className="h-4 w-4 rounded" />
          Auto-refresh (30s)
        </label>
        {autoRefresh && <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700">● Live</span>}
      </div>

      {loading ? (
        <div className="py-12 text-center text-slate-400">Loading…</div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-xs font-semibold uppercase text-slate-500">
                <th className="px-4 py-3 text-left">Time</th>
                <th className="px-4 py-3 text-left">Action</th>
                <th className="px-4 py-3 text-left">Entity</th>
                <th className="px-4 py-3 text-left">ID</th>
                <th className="px-4 py-3 text-left">Description</th>
                <th className="px-4 py-3 text-left">By</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {filtered.map((e) => (
                <tr key={e.id} className={rowBg(e.action)}>
                  <td className="px-4 py-3 text-xs text-slate-500 whitespace-nowrap">
                    {new Date(e.created_at).toLocaleString("en-IN", { dateStyle: "short", timeStyle: "short" })}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                      e.action === "DELETE" ? "bg-red-100 text-red-700" :
                      e.action === "CREATE" ? "bg-emerald-100 text-emerald-700" :
                      e.action === "UPDATE" ? "bg-yellow-100 text-yellow-800" :
                      "bg-slate-100 text-slate-600"
                    }`}>{e.action}</span>
                  </td>
                  <td className="px-4 py-3 text-slate-600">{e.entity_type}</td>
                  <td className="px-4 py-3 font-mono text-slate-400">{e.entity_id ?? "—"}</td>
                  <td className="px-4 py-3 text-slate-700">{e.description}</td>
                  <td className="px-4 py-3 text-slate-400 text-xs">{e.performed_by ?? "—"}</td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr><td colSpan={6} className="px-4 py-8 text-center text-slate-400">No audit log entries.</td></tr>
              )}
            </tbody>
          </table>
          <div className="border-t border-slate-100 px-4 py-2 text-xs text-slate-400">
            {filtered.length} of {entries.length} entries
          </div>
        </div>
      )}
    </div>
  );
}


// ─────────────────────── APP SETTINGS TAB ───────────────────────────────────

function AppSettingsTab({ headersJson }: { headersJson: () => Record<string, string> }) {
  const [pin, setPin] = useState("");
  const [pinConfirm, setPinConfirm] = useState("");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null);
  const [currentPin, setCurrentPin] = useState<string | null>(null);

  useEffect(() => {
    fetchApi(apiUrl("app-settings"), { headers: headersJson() })
      .then(r => r.ok ? r.json() : null)
      .then((d: { cancel_order_pin?: string } | null) => { if (d) setCurrentPin(d.cancel_order_pin ?? null); })
      .catch(() => null);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function savePin() {
    if (!pin.trim()) return;
    if (!/^\d{4,}$/.test(pin)) { setMsg({ text: "PIN must be at least 4 digits", ok: false }); return; }
    if (pin !== pinConfirm) { setMsg({ text: "PINs do not match", ok: false }); return; }
    setSaving(true); setMsg(null);
    const r = await fetchApi(apiUrl("app-settings"), {
      method: "POST", headers: headersJson(),
      body: JSON.stringify({ cancel_order_pin: pin }),
    });
    const d = await r.json().catch(() => ({})) as { cancel_order_pin?: string };
    setSaving(false);
    if (!r.ok) { setMsg({ text: formatApiError(d as Record<string, unknown>), ok: false }); return; }
    setCurrentPin(d.cancel_order_pin ?? null);
    setPin(""); setPinConfirm("");
    setMsg({ text: "PIN updated successfully.", ok: true });
  }

  return (
    <div className="space-y-6 max-w-md">
      <div className={CARD}>
        <h3 className="mb-1 text-base font-semibold text-slate-700">🔐 Cancel Order PIN</h3>
        <p className="mb-4 text-sm text-slate-500">
          Required when cancelling a customer order. Default is 1234.{" "}
          {currentPin && <>Current PIN is <strong>{currentPin.length}</strong> digits.</>}
        </p>
        <div className="space-y-3">
          <div>
            <label className={LABEL}>New PIN (min 4 digits)</label>
            <input type="password" inputMode="numeric" value={pin} onChange={e => setPin(e.target.value)} placeholder="e.g. 1234" className={INPUT} />
          </div>
          <div>
            <label className={LABEL}>Confirm PIN</label>
            <input type="password" inputMode="numeric" value={pinConfirm} onChange={e => setPinConfirm(e.target.value)} placeholder="Repeat PIN" className={INPUT} />
          </div>
          {msg && <div className={`text-sm ${msg.ok ? "text-emerald-600" : "text-red-600"}`}>{msg.text}</div>}
          <button type="button" onClick={savePin} disabled={saving} className={BTN_PRIMARY}>
            {saving ? "Saving…" : "Save PIN"}
          </button>
        </div>
      </div>
    </div>
  );
}
