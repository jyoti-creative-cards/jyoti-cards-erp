"use client";

import { useCallback, useEffect, useState } from "react";
import { apiUrl, fetchApi, formatApiError } from "@/lib/api";

const BTN_PRIMARY = "inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white shadow-sm transition hover:bg-blue-700 disabled:opacity-50";
const BTN_DANGER = "inline-flex items-center gap-1.5 rounded-lg border border-red-200 bg-red-50 px-3 py-1.5 text-xs font-medium text-red-600 transition hover:bg-red-100";
const BTN_SECONDARY = "inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 shadow-sm transition hover:bg-slate-50";

interface DeletedRecord {
  id: number;
  name?: string;
  company_name?: string;
  person_name?: string;
  customer_name?: string;
  deleted_at?: string;
  created_at?: string;
  status?: string;
}

interface TabConfig {
  id: "customers" | "vendors" | "orders" | "products";
  label: string;
  listEndpoint: string;
  restoreEndpoint: (id: number) => string;
  deleteEndpoint: (id: number) => string;
  nameOf: (r: DeletedRecord) => string;
}

const TABS: TabConfig[] = [
  {
    id: "customers",
    label: "👥 Customers",
    listEndpoint: "customers?deleted=true",
    restoreEndpoint: (id) => `customers/${id}/restore`,
    deleteEndpoint: (id) => `customers/${id}/permanent`,
    nameOf: (r) => r.name ?? r.company_name ?? `#${r.id}`,
  },
  {
    id: "vendors",
    label: "🏭 Vendors",
    listEndpoint: "vendors?deleted=true",
    restoreEndpoint: (id) => `vendors/${id}/restore`,
    deleteEndpoint: (id) => `vendors/${id}/permanent`,
    nameOf: (r) => r.company_name ?? r.person_name ?? `#${r.id}`,
  },
  {
    id: "orders",
    label: "🛒 Orders",
    listEndpoint: "customer-orders?deleted=true",
    restoreEndpoint: (id) => `customer-orders/${id}/restore`,
    deleteEndpoint: (id) => `customer-orders/${id}/permanent`,
    nameOf: (r) => r.customer_name ?? `Order #${r.id}`,
  },
  {
    id: "products",
    label: "📦 Products",
    listEndpoint: "catalog?deleted=true",
    restoreEndpoint: (id) => `catalog/${id}/restore`,
    deleteEndpoint: (id) => `catalog/${id}/permanent`,
    nameOf: (r) => r.name ?? `#${r.id}`,
  },
];

interface Props {
  adminKey: string;
}

export function RecycleBinScreen({ adminKey }: Props) {
  const [tab, setTab] = useState<TabConfig["id"]>("customers");

  const headersAdmin = (): Record<string, string> =>
    adminKey.trim() ? { "X-Admin-Key": adminKey.trim() } : {};
  const headersJson = (): Record<string, string> => ({
    "Content-Type": "application/json",
    ...(adminKey.trim() ? { "X-Admin-Key": adminKey.trim() } : {}),
  });

  const current = TABS.find((t) => t.id === tab)!;

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-xl font-bold text-slate-800">🗑️ Recycle Bin</h1>
        <p className="mt-1 text-sm text-slate-500">View and restore or permanently delete soft-deleted records.</p>
      </div>

      <div className="mb-6 flex flex-wrap gap-2">
        {TABS.map((t) => (
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

      <RecycleBinTab
        key={tab}
        config={current}
        headersAdmin={headersAdmin}
        headersJson={headersJson}
      />
    </div>
  );
}

function RecycleBinTab({
  config,
  headersAdmin,
  headersJson,
}: {
  config: TabConfig;
  headersAdmin: () => Record<string, string>;
  headersJson: () => Record<string, string>;
}) {
  const [records, setRecords] = useState<DeletedRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);

  const showToast = (msg: string, ok: boolean) => {
    setToast({ msg, ok });
    setTimeout(() => setToast(null), 3500);
  };

  const load = useCallback(async () => {
    setLoading(true);
    const r = await fetchApi(apiUrl(config.listEndpoint), { headers: headersAdmin() });
    if (r.ok) setRecords(await r.json());
    else setRecords([]);
    setLoading(false);
  }, [config.listEndpoint]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { void load(); }, [load]);

  async function restore(id: number) {
    const r = await fetchApi(apiUrl(config.restoreEndpoint(id)), { method: "POST", headers: headersJson() });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) { showToast(formatApiError(data), false); return; }
    showToast("Restored successfully.", true);
    void load();
  }

  async function permanentDelete(id: number) {
    const r = await fetchApi(apiUrl(config.deleteEndpoint(id)), { method: "DELETE", headers: headersAdmin() });
    const data = await r.json().catch(() => ({}));
    setConfirmDeleteId(null);
    if (!r.ok) { showToast(formatApiError(data), false); return; }
    showToast("Permanently deleted.", true);
    void load();
  }

  return (
    <div>
      {toast && (
        <div className={`fixed right-4 top-20 z-50 rounded-lg px-4 py-3 text-sm font-medium shadow-lg ${toast.ok ? "bg-emerald-600 text-white" : "bg-red-600 text-white"}`}>
          {toast.msg}
        </div>
      )}

      <div className="mb-4 flex items-center gap-2">
        <button type="button" onClick={() => void load()} className={BTN_SECONDARY}>↻ Refresh</button>
      </div>

      {loading ? (
        <div className="py-12 text-center text-slate-400">Loading…</div>
      ) : records.length === 0 ? (
        <div className="rounded-xl border-2 border-dashed border-slate-200 py-16 text-center text-slate-400">
          <div className="text-4xl">🗑️</div>
          <div className="mt-2 font-medium">Recycle bin is empty</div>
          <div className="mt-1 text-sm">No deleted {config.id} found.</div>
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-xs font-semibold uppercase text-slate-500">
                <th className="px-4 py-3 text-left">ID</th>
                <th className="px-4 py-3 text-left">Name</th>
                <th className="px-4 py-3 text-left">Deleted at</th>
                <th className="px-4 py-3 text-left">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {records.map((r) => (
                <tr key={r.id} className="transition hover:bg-slate-50">
                  <td className="px-4 py-3 font-mono text-slate-400">#{r.id}</td>
                  <td className="px-4 py-3 font-medium text-slate-800">{config.nameOf(r)}</td>
                  <td className="px-4 py-3 text-slate-400 text-xs">
                    {r.deleted_at
                      ? new Date(r.deleted_at).toLocaleString("en-IN", { dateStyle: "short", timeStyle: "short" })
                      : "—"}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <button type="button" onClick={() => void restore(r.id)} className={BTN_PRIMARY}>
                        ↩ Restore
                      </button>
                      {confirmDeleteId === r.id ? (
                        <div className="flex items-center gap-1">
                          <span className="text-xs text-red-700 font-medium">Sure?</span>
                          <button type="button" onClick={() => void permanentDelete(r.id)} className={BTN_DANGER}>Yes, delete forever</button>
                          <button type="button" onClick={() => setConfirmDeleteId(null)} className={BTN_SECONDARY}>Cancel</button>
                        </div>
                      ) : (
                        <button type="button" onClick={() => setConfirmDeleteId(r.id)} className={BTN_DANGER}>
                          🗑 Delete Forever
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="border-t border-slate-100 px-4 py-2 text-xs text-slate-400">
            {records.length} deleted record{records.length !== 1 ? "s" : ""}
          </div>
        </div>
      )}
    </div>
  );
}
