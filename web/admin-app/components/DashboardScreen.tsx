"use client";

import { useCallback, useEffect, useState } from "react";
import { apiUrl, fetchApi } from "@/lib/api";
import type { AuthState, CustomerOrderAdminPublic } from "@/lib/types";
import type { ErpMainTab } from "@/components/ErpAppShell";

interface VendorOrderLine {
  line_id: string;
  catalog_product_id: number;
  product_name: string;
  qty_ordered: number;
  qty_received: number;
  unit_price: number;
}

interface VendorOrder {
  id: number;
  vendor_id: number;
  vendor_name: string | null;
  status: "open" | "closed";
  items: VendorOrderLine[];
  notes: string | null;
  created_at: string;
  updated_at: string;
}

function fmtDate(iso: string) {
  try {
    return new Date(iso).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
  } catch { return iso; }
}

function pendingItems(vo: VendorOrder) {
  return vo.items.reduce((s, l) => s + Math.max(0, l.qty_ordered - l.qty_received), 0);
}

const BADGE: Record<string, string> = {
  open:      "bg-emerald-100 text-emerald-700",
  confirmed: "bg-blue-100 text-blue-700",
  billed:    "bg-indigo-100 text-indigo-700",
  shipped:   "bg-purple-100 text-purple-700",
  closed:    "bg-slate-100 text-slate-600",
  cancelled: "bg-red-100 text-red-500",
};

export function DashboardScreen({
  adminKey,
  auth,
  onNavigate,
}: {
  adminKey: string;
  auth: AuthState;
  onNavigate: (tab: ErpMainTab) => void;
}) {
  const h = (): Record<string, string> => {
    if (adminKey.trim()) return { "X-Admin-Key": adminKey.trim() };
    if (auth.type === "staff") return { Authorization: `Bearer ${auth.token}` };
    return {};
  };

  const [customerOrders, setCustomerOrders] = useState<CustomerOrderAdminPublic[]>([]);
  const [vendorOrders, setVendorOrders] = useState<VendorOrder[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const [cr, vr] = await Promise.all([
      fetchApi(apiUrl("customer-orders?limit=50&status=received"), { headers: h() }),
      fetchApi(apiUrl("vendor-orders"), { headers: h() }),
    ]);
    if (cr.ok) setCustomerOrders(await cr.json());
    if (vr.ok) setVendorOrders(await vr.json());
    setLoading(false);
  }, [adminKey]);

  useEffect(() => { void load(); }, [load]);

  const openCustomer = customerOrders.filter(o => ["received", "billed"].includes(o.status));
  const openVendor   = vendorOrders.filter(o => o.status === "open");

  const totalPendingValue = openCustomer.reduce((s, o) => s + Number(o.total_amount || 0), 0);
  const totalPendingVendorItems = openVendor.reduce((s, vo) => s + pendingItems(vo), 0);

  return (
    <div className="space-y-6">
      {/* Stat cards */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatCard label="Open Customer Orders" value={openCustomer.length} color="blue" onClick={() => onNavigate("orders")} />
        <StatCard label="Pending ₹ (customer)" value={`₹${Number(totalPendingValue).toLocaleString("en-IN")}`} color="indigo" onClick={() => onNavigate("orders")} />
        <StatCard label="Open Vendor Orders" value={openVendor.length} color="emerald" onClick={() => onNavigate("orders")} />
        <StatCard label="Pending Vendor Items" value={totalPendingVendorItems} color="amber" onClick={() => onNavigate("orders")} />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Open Customer Orders */}
        <section className="rounded-2xl border border-slate-200 bg-white shadow-sm overflow-hidden">
          <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50 px-4 py-3">
            <h2 className="text-sm font-bold text-slate-700">🛒 Open Customer Orders ({openCustomer.length})</h2>
            <button onClick={() => onNavigate("orders")} className="text-xs text-blue-600 hover:underline">View all →</button>
          </div>
          {loading ? (
            <div className="px-4 py-8 text-center text-sm text-slate-400">Loading…</div>
          ) : openCustomer.length === 0 ? (
            <div className="px-4 py-8 text-center text-sm text-slate-400">No open customer orders</div>
          ) : (
            <ul className="divide-y divide-slate-100 max-h-96 overflow-y-auto">
              {openCustomer.map(o => (
                <li key={o.id}
                  onClick={() => onNavigate("orders")}
                  className="cursor-pointer px-4 py-3 hover:bg-blue-50/40 transition">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold text-slate-800">{o.customer_name}</p>
                      <p className="text-xs text-slate-400">{fmtDate(o.updated_at)}</p>
                      <p className="mt-0.5 text-xs text-slate-500">{o.items.length} item{o.items.length !== 1 ? "s" : ""}</p>
                    </div>
                    <div className="flex flex-col items-end gap-1 shrink-0">
                      <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${BADGE[o.status] ?? "bg-slate-100 text-slate-600"}`}>
                        {o.status}
                      </span>
                      <span className="text-xs font-medium text-slate-700">₹{Number(o.total_amount).toLocaleString("en-IN")}</span>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* Open Vendor Orders */}
        <section className="rounded-2xl border border-slate-200 bg-white shadow-sm overflow-hidden">
          <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50 px-4 py-3">
            <h2 className="text-sm font-bold text-slate-700">📦 Open Vendor Orders ({openVendor.length})</h2>
            <button onClick={() => onNavigate("orders")} className="text-xs text-blue-600 hover:underline">View all →</button>
          </div>
          {loading ? (
            <div className="px-4 py-8 text-center text-sm text-slate-400">Loading…</div>
          ) : openVendor.length === 0 ? (
            <div className="px-4 py-8 text-center text-sm text-slate-400">No open vendor orders</div>
          ) : (
            <ul className="divide-y divide-slate-100 max-h-96 overflow-y-auto">
              {openVendor.map(vo => {
                const pending = pendingItems(vo);
                return (
                  <li key={vo.id}
                    onClick={() => onNavigate("orders")}
                    className="cursor-pointer px-4 py-3 hover:bg-emerald-50/40 transition">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-semibold text-slate-800">{vo.vendor_name || `Vendor #${vo.vendor_id}`}</p>
                        <p className="text-xs text-slate-400">{fmtDate(vo.updated_at)}</p>
                        <p className="mt-0.5 text-xs text-slate-500">{vo.items.length} line{vo.items.length !== 1 ? "s" : ""}</p>
                      </div>
                      <div className="flex flex-col items-end gap-1 shrink-0">
                        <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-700">open</span>
                        <span className="text-xs text-slate-500">{pending} pending item{pending !== 1 ? "s" : ""}</span>
                      </div>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      </div>

      <p className="text-right text-xs text-slate-400">
        Last refreshed: {new Date().toLocaleTimeString("en-IN")} ·{" "}
        <button onClick={() => void load()} className="text-blue-500 hover:underline">Refresh</button>
      </p>
    </div>
  );
}

function StatCard({
  label, value, color, onClick,
}: {
  label: string;
  value: string | number;
  color: "blue" | "indigo" | "emerald" | "amber";
  onClick: () => void;
}) {
  const bg = { blue: "from-blue-50 to-white border-blue-100", indigo: "from-indigo-50 to-white border-indigo-100", emerald: "from-emerald-50 to-white border-emerald-100", amber: "from-amber-50 to-white border-amber-100" }[color];
  const text = { blue: "text-blue-700", indigo: "text-indigo-700", emerald: "text-emerald-700", amber: "text-amber-700" }[color];
  return (
    <button type="button" onClick={onClick}
      className={`rounded-2xl border bg-gradient-to-br ${bg} p-4 text-left shadow-sm transition hover:shadow-md w-full`}>
      <p className="text-xs font-medium text-slate-500">{label}</p>
      <p className={`mt-1 text-2xl font-bold ${text}`}>{value}</p>
    </button>
  );
}
