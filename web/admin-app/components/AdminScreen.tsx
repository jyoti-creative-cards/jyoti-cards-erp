"use client";

import { useCallback, useEffect, useState } from "react";
import { apiUrl, fetchApi, formatApiError } from "@/lib/api";

const INPUT = "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500";
const LABEL = "mb-1 block text-xs font-semibold text-slate-500 uppercase tracking-wider";
const BTN_PRIMARY = "inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-700 disabled:opacity-50";
const BTN_DANGER = "inline-flex items-center gap-1.5 rounded-lg border border-red-200 bg-red-50 px-3 py-1.5 text-xs font-medium text-red-600 transition hover:bg-red-100";
const CARD = "rounded-xl border border-slate-200 bg-white p-5 shadow-sm";

interface Props {
  adminKey: string;
}

export function AdminScreen({ adminKey }: Props) {
  const [tab, setTab] = useState<"routes" | "categories" | "series" | "yeargroups">("routes");
  const headersAdmin = (): Record<string, string> =>
    adminKey.trim() ? { "X-Admin-Key": adminKey.trim() } : {};
  const headersJson = (): Record<string, string> => ({
    "Content-Type": "application/json",
    ...(adminKey.trim() ? { "X-Admin-Key": adminKey.trim() } : {}),
  });

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-xl font-bold text-slate-800">Admin Setup</h1>
        <p className="mt-1 text-sm text-slate-500">Manage lookup values — routes, cities, categories, series, year groups.</p>
      </div>

      <div className="mb-6 flex flex-wrap gap-2">
        {([
          { id: "routes", label: "🗺️ Routes & Cities" },
          { id: "categories", label: "🏷️ Categories" },
          { id: "series", label: "📚 Series" },
          { id: "yeargroups", label: "📅 Year Groups" },
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

      {tab === "routes" && <RoutesAndCitiesTab headersAdmin={headersAdmin} headersJson={headersJson} adminKey={adminKey} />}
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
