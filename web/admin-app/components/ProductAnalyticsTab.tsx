"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiUrl, fetchApi, formatApiError } from "@/lib/api";
import type { CatalogProductPublic, CustomerOrderAdminPublic, InventoryRowPublic } from "@/lib/types";

// ─── Types ────────────────────────────────────────────────────────────────────
interface Props {
  adminKey: string;
  apiBase: string;
  invRows: InventoryRowPublic[];
  catalogRows: CatalogProductPublic[];
  vendorLabel: (id: number) => string;
}

interface BuyerEntry {
  customer_id: number;
  customer_name: string;
  units: number;
  revenue: number;
  order_count: number;
  last_at: string;
  orders: { order_id: number; date: string; qty: number; amount: number; status: string }[];
}

interface ProductStat {
  catalog_product_id: number;
  our_product_id: string;
  name: string;
  category: string;
  vendor_id: number;
  buying_price: number;
  quantity: number;
  stock_status: string;
  total_units_sold: number;
  total_revenue: number;
  order_count: number;
  last_sold_at: string | null;
  first_sold_at: string | null;
  buyers: BuyerEntry[];
  sell_rate_per_day: number;
  days_of_stock: number | null;
  monthly: Record<string, number>; // "YYYY-MM" → units
}

type AnalyticsTab = "overview" | "trend" | "customers" | "category" | "vendor" | "seasonal" | "abc" | "deadstock";

// ─── Helpers ─────────────────────────────────────────────────────────────────
function fmtDate(iso: string | null) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }); }
  catch { return iso; }
}
function fmtRupee(n: number) {
  return "₹" + n.toLocaleString("en-IN", { minimumFractionDigits: 0, maximumFractionDigits: 0 });
}
function isoToday() { return new Date().toISOString().slice(0, 10); }
function iso12MonthsAgo() {
  const d = new Date(); d.setFullYear(d.getFullYear() - 1);
  return d.toISOString().slice(0, 10);
}
function yyyyMM(iso: string) { return iso.slice(0, 7); }

function stockBadge(s: string) {
  if (s === "out_of_stock") return <span className="rounded bg-red-100 px-1.5 py-0.5 text-[10px] font-medium text-red-800">Out</span>;
  if (s === "low_stock") return <span className="rounded bg-yellow-100 px-1.5 py-0.5 text-[10px] font-medium text-yellow-800">Low</span>;
  return <span className="rounded bg-green-100 px-1.5 py-0.5 text-[10px] font-medium text-green-800">OK</span>;
}

// Tiny inline bar — max 120px wide
function MiniBar({ value, max, color = "bg-blue-500" }: { value: number; max: number; color?: string }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div className="flex items-center gap-1.5">
      <div className="h-2 w-20 rounded-full bg-neutral-200">
        <div className={`h-2 rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[10px] text-neutral-500">{pct}%</span>
    </div>
  );
}

// Simple bar chart — each bucket is a column
function BarChart({
  data,
  labelKey,
  valueKey,
  color = "bg-blue-500",
  height = 80,
}: {
  data: Record<string, number>;
  labelKey?: string;
  valueKey?: string;
  color?: string;
  height?: number;
}) {
  const entries = Object.entries(data);
  if (!entries.length) return <p className="text-xs text-neutral-400">No data</p>;
  const max = Math.max(...entries.map(([, v]) => v), 1);
  return (
    <div className="overflow-x-auto">
      <div className="flex items-end gap-0.5" style={{ minWidth: entries.length * 28 }}>
        {entries.map(([k, v]) => (
          <div key={k} className="flex flex-col items-center" style={{ width: 28 }}>
            <span className="mb-0.5 text-[9px] text-neutral-600 font-medium">{v > 0 ? v : ""}</span>
            <div
              className={`w-5 rounded-t ${color}`}
              style={{ height: `${Math.max(2, Math.round((v / max) * height))}px` }}
              title={`${k}: ${v}`}
            />
            <span className="mt-0.5 text-[8px] text-neutral-400 rotate-[-45deg] origin-top-left whitespace-nowrap" style={{ display: "block", width: 20 }}>
              {k.slice(2)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Product detail panel (used in overview + trend + customers) ──────────────
function ProductDetailPanel({
  stat,
  vendorLabel,
  onClose,
  activeView,
  dateFrom,
  dateTo,
}: {
  stat: ProductStat;
  vendorLabel: (id: number) => string;
  onClose: () => void;
  activeView: "buyers" | "orders" | "trend";
  dateFrom: string;
  dateTo: string;
}) {
  const [view, setView] = useState<"buyers" | "orders" | "trend">(activeView);
  const allOrders = useMemo(
    () =>
      stat.buyers
        .flatMap((b) => b.orders.map((o) => ({ ...o, customer_name: b.customer_name })))
        .sort((a, b) => b.date.localeCompare(a.date)),
    [stat],
  );

  return (
    <div className="rounded-lg border border-blue-200 bg-blue-50 p-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-wide text-blue-400">Selected product</p>
          <h4 className="text-sm font-bold text-neutral-900">{stat.our_product_id} — {stat.name}</h4>
          <p className="text-xs text-neutral-500">{stat.category || "—"} · {vendorLabel(stat.vendor_id)}</p>
        </div>
        <button type="button" onClick={onClose}
          className="rounded border border-blue-200 bg-white px-2 py-1 text-xs text-blue-700 hover:bg-blue-100">✕ Close</button>
      </div>

      {/* KPI row */}
      <div className="mb-3 grid grid-cols-3 gap-2 sm:grid-cols-6">
        {[
          { l: "Stock", v: stat.quantity, sub: stockBadge(stat.stock_status) },
          { l: "Units sold", v: stat.total_units_sold, warn: stat.total_units_sold === 0 },
          { l: "Revenue", v: fmtRupee(stat.total_revenue) },
          { l: "Orders", v: stat.order_count },
          { l: "Rate/day", v: stat.sell_rate_per_day > 0 ? stat.sell_rate_per_day.toFixed(2) : "—" },
          {
            l: "Days left",
            v: stat.days_of_stock !== null ? `${stat.days_of_stock}d` : "—",
            danger: stat.days_of_stock !== null && stat.days_of_stock < 7,
            warn2: stat.days_of_stock !== null && stat.days_of_stock >= 7 && stat.days_of_stock < 30,
          },
        ].map((k) => (
          <div key={k.l} className={`rounded border px-2 py-1.5 ${k.danger ? "border-red-300 bg-red-50" : k.warn2 ? "border-yellow-300 bg-yellow-50" : "border-white bg-white"}`}>
            <p className="text-[9px] uppercase tracking-wide text-neutral-400">{k.l}</p>
            <p className={`text-sm font-bold ${k.danger ? "text-red-700" : k.warn2 ? "text-yellow-700" : k.warn ? "text-neutral-400" : "text-neutral-800"}`}>
              {typeof k.v === "number" ? k.v.toLocaleString("en-IN") : k.v}
            </p>
            {k.sub && <div className="mt-0.5">{k.sub}</div>}
          </div>
        ))}
      </div>

      {stat.buyers.length === 0 ? (
        <p className="rounded border border-yellow-200 bg-yellow-50 px-3 py-2 text-xs text-yellow-800">
          No sales in this date range ({dateFrom} to {dateTo}).
        </p>
      ) : (
        <>
          <div className="mb-2 flex gap-1 text-xs">
            {(["buyers", "orders", "trend"] as const).map((v) => (
              <button key={v} type="button" onClick={() => setView(v)}
                className={`rounded px-3 py-1 capitalize ${view === v ? "bg-blue-700 text-white" : "bg-white text-blue-700 border border-blue-300"}`}>
                {v === "buyers" ? `Buyers (${stat.buyers.length})` : v === "orders" ? `Orders (${allOrders.length})` : "Monthly trend"}
              </button>
            ))}
          </div>

          {view === "buyers" && (
            <div className="overflow-x-auto rounded border border-blue-200">
              <table className="w-full border-collapse text-xs">
                <thead>
                  <tr className="bg-blue-100">
                    <th className="px-3 py-1.5 text-left">Customer</th>
                    <th className="px-3 py-1.5 text-right">Orders</th>
                    <th className="px-3 py-1.5 text-right">Units</th>
                    <th className="px-3 py-1.5 text-right">Revenue</th>
                    <th className="px-3 py-1.5 text-left">% of sales</th>
                    <th className="px-3 py-1.5 text-left">Last order</th>
                  </tr>
                </thead>
                <tbody>
                  {stat.buyers.map((b) => (
                    <tr key={b.customer_id} className="border-t border-blue-100">
                      <td className="px-3 py-1.5 font-medium">{b.customer_name}</td>
                      <td className="px-3 py-1.5 text-right">{b.order_count}</td>
                      <td className="px-3 py-1.5 text-right font-semibold text-emerald-700">{b.units}</td>
                      <td className="px-3 py-1.5 text-right">{fmtRupee(b.revenue)}</td>
                      <td className="px-3 py-1.5"><MiniBar value={b.units} max={stat.total_units_sold} color="bg-blue-500" /></td>
                      <td className="px-3 py-1.5 text-neutral-500">{fmtDate(b.last_at)}</td>
                    </tr>
                  ))}
                  <tr className="border-t-2 border-blue-300 bg-blue-100 font-semibold text-xs">
                    <td className="px-3 py-1.5">Total</td>
                    <td className="px-3 py-1.5 text-right">{stat.order_count}</td>
                    <td className="px-3 py-1.5 text-right text-emerald-800">{stat.total_units_sold}</td>
                    <td className="px-3 py-1.5 text-right">{fmtRupee(stat.total_revenue)}</td>
                    <td colSpan={2} />
                  </tr>
                </tbody>
              </table>
            </div>
          )}

          {view === "orders" && (
            <div className="overflow-x-auto rounded border border-blue-200">
              <table className="w-full border-collapse text-xs">
                <thead>
                  <tr className="bg-blue-100">
                    <th className="px-3 py-1.5 text-left">Order #</th>
                    <th className="px-3 py-1.5 text-left">Date</th>
                    <th className="px-3 py-1.5 text-left">Customer</th>
                    <th className="px-3 py-1.5 text-right">Qty</th>
                    <th className="px-3 py-1.5 text-right">Amount</th>
                    <th className="px-3 py-1.5 text-left">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {allOrders.map((o) => (
                    <tr key={`${o.order_id}-${o.customer_name}`} className="border-t border-blue-100">
                      <td className="px-3 py-1.5 font-mono">#{o.order_id}</td>
                      <td className="px-3 py-1.5">{fmtDate(o.date)}</td>
                      <td className="px-3 py-1.5 font-medium">{o.customer_name}</td>
                      <td className="px-3 py-1.5 text-right font-semibold">{o.qty}</td>
                      <td className="px-3 py-1.5 text-right">{fmtRupee(o.amount)}</td>
                      <td className="px-3 py-1.5">
                        <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${o.status === "shipped" ? "bg-green-100 text-green-800" : o.status === "billed" ? "bg-blue-100 text-blue-800" : "bg-neutral-100 text-neutral-600"}`}>{o.status}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {view === "trend" && (
            <div>
              <p className="mb-2 text-xs text-neutral-500">Units sold per month</p>
              <BarChart data={stat.monthly} color="bg-blue-500" height={80} />
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────
export function ProductAnalyticsTab({ adminKey, invRows, catalogRows, vendorLabel }: Props) {
  const [orders, setOrders] = useState<CustomerOrderAdminPublic[]>([]);
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState("");
  const [lastLoaded, setLastLoaded] = useState<string | null>(null);

  const [activeTab, setActiveTab] = useState<AnalyticsTab>("overview");
  const [selectedId, setSelectedId] = useState<number | null>(null);

  // Date range
  const [dateFrom, setDateFrom] = useState(iso12MonthsAgo());
  const [dateTo, setDateTo] = useState(isoToday());

  // Overview filters
  const [filterVendor, setFilterVendor] = useState("");
  const [filterCategory, setFilterCategory] = useState("");
  const [filterQ, setFilterQ] = useState("");
  const [sortBy, setSortBy] = useState<"units_sold" | "revenue" | "stock" | "sell_rate" | "days_stock" | "last_sold">("units_sold");
  const [showOnlyActive, setShowOnlyActive] = useState(false);
  const [slowDays, setSlowDays] = useState(30);

  // Trend product picker
  const [trendProductId, setTrendProductId] = useState<number | null>(null);

  const headersAdmin = useCallback(() => ({ "Content-Type": "application/json", "X-Admin-Key": adminKey }), [adminKey]);

  const loadOrders = useCallback(async () => {
    if (!adminKey.trim()) return;
    setLoading(true); setMsg("");
    try {
      const r = await fetchApi(apiUrl("customer-orders"), { headers: headersAdmin() });
      if (!r.ok) { setMsg(formatApiError(await r.json().catch(() => ({})))); return; }
      const data = await r.json();
      setOrders(Array.isArray(data) ? data : []);
      setLastLoaded(new Date().toLocaleTimeString("en-IN"));
    } catch (e) { setMsg(String(e)); }
    finally { setLoading(false); }
  }, [adminKey, headersAdmin]);

  useEffect(() => { void loadOrders(); }, [loadOrders]);

  const fromMs = useMemo(() => (dateFrom ? new Date(dateFrom).getTime() : 0), [dateFrom]);
  const toMs = useMemo(() => (dateTo ? new Date(dateTo + "T23:59:59").getTime() : Infinity), [dateTo]);

  // ── Build stats ──────────────────────────────────────────────────────────────
  const { statsMap, allMonths } = useMemo(() => {
    const sm = new Map<number, ProductStat>();
    const monthSet = new Set<string>();
    const bpMap = new Map<number, number>(catalogRows.map((c) => [c.id, c.buying_price ?? 0]));

    for (const row of invRows) {
      sm.set(row.catalog_product_id, {
        catalog_product_id: row.catalog_product_id,
        our_product_id: row.our_product_id,
        name: row.name,
        category: row.category,
        vendor_id: row.vendor_id,
        buying_price: bpMap.get(row.catalog_product_id) ?? 0,
        quantity: row.quantity,
        stock_status: row.stock_status,
        total_units_sold: 0, total_revenue: 0, order_count: 0,
        last_sold_at: null, first_sold_at: null,
        buyers: [], sell_rate_per_day: 0, days_of_stock: null,
        monthly: {},
      });
    }

    const activeOrders = orders.filter(
      (o) => ["confirmed", "billed", "shipped"].includes(o.status) &&
        new Date(o.created_at).getTime() >= fromMs &&
        new Date(o.created_at).getTime() <= toMs,
    );

    const buyerAccum = new Map<number, Map<number, BuyerEntry>>();

    for (const order of activeOrders) {
      const mon = yyyyMM(order.created_at);
      monthSet.add(mon);
      for (const item of order.items) {
        const stat = sm.get(item.catalog_product_id);
        if (!stat) continue;
        const amount = parseFloat(item.line_total ?? "0");
        stat.total_units_sold += item.quantity;
        stat.total_revenue += amount;
        stat.order_count += 1;
        const at = order.created_at;
        if (!stat.last_sold_at || at > stat.last_sold_at) stat.last_sold_at = at;
        if (!stat.first_sold_at || at < stat.first_sold_at) stat.first_sold_at = at;
        stat.monthly[mon] = (stat.monthly[mon] ?? 0) + item.quantity;

        if (!buyerAccum.has(item.catalog_product_id)) buyerAccum.set(item.catalog_product_id, new Map());
        const bm = buyerAccum.get(item.catalog_product_id)!;
        const ex = bm.get(order.customer_id);
        const orderEntry = { order_id: order.id, date: order.created_at, qty: item.quantity, amount, status: order.status };
        if (ex) {
          ex.units += item.quantity; ex.revenue += amount; ex.order_count += 1;
          if (at > ex.last_at) ex.last_at = at;
          ex.orders.push(orderEntry);
        } else {
          bm.set(order.customer_id, { customer_id: order.customer_id, customer_name: order.customer_name ?? `#${order.customer_id}`, units: item.quantity, revenue: amount, order_count: 1, last_at: at, orders: [orderEntry] });
        }
      }
    }

    const rangeDays = Math.max(1, (toMs - fromMs) / 86400000);
    for (const [cid, stat] of sm) {
      const bmap = buyerAccum.get(cid);
      stat.buyers = bmap ? Array.from(bmap.values()).sort((a, b) => b.units - a.units) : [];
      stat.sell_rate_per_day = stat.total_units_sold / rangeDays;
      if (stat.sell_rate_per_day > 0) stat.days_of_stock = Math.round(stat.quantity / stat.sell_rate_per_day);
    }

    const sortedMonths = Array.from(monthSet).sort();
    return { statsMap: sm, allMonths: sortedMonths };
  }, [invRows, catalogRows, orders, fromMs, toMs]);

  const allStats = useMemo(() => Array.from(statsMap.values()), [statsMap]);
  const selectedStat = selectedId !== null ? (statsMap.get(selectedId) ?? null) : null;
  const trendStat = trendProductId !== null ? (statsMap.get(trendProductId) ?? null) : null;

  const now = Date.now();

  // ── Overview filtered/sorted list ───────────────────────────────────────────
  const overviewStats = useMemo(() => {
    let s = allStats;
    if (filterVendor) s = s.filter((x) => String(x.vendor_id) === filterVendor);
    if (filterCategory) s = s.filter((x) => x.category === filterCategory);
    if (filterQ.trim()) { const q = filterQ.toLowerCase(); s = s.filter((x) => x.our_product_id.toLowerCase().includes(q) || x.name.toLowerCase().includes(q)); }
    if (showOnlyActive) s = s.filter((x) => x.total_units_sold > 0);
    return [...s].sort((a, b) => {
      if (sortBy === "units_sold") return b.total_units_sold - a.total_units_sold;
      if (sortBy === "revenue") return b.total_revenue - a.total_revenue;
      if (sortBy === "stock") return b.quantity - a.quantity;
      if (sortBy === "sell_rate") return b.sell_rate_per_day - a.sell_rate_per_day;
      if (sortBy === "days_stock") return (a.days_of_stock ?? Infinity) - (b.days_of_stock ?? Infinity);
      if (sortBy === "last_sold") {
        if (!a.last_sold_at && !b.last_sold_at) return 0;
        if (!a.last_sold_at) return 1; if (!b.last_sold_at) return -1;
        return b.last_sold_at > a.last_sold_at ? 1 : -1;
      }
      return 0;
    });
  }, [allStats, filterVendor, filterCategory, filterQ, showOnlyActive, sortBy]);

  const categories = useMemo(() => Array.from(new Set(invRows.map((r) => r.category).filter(Boolean))).sort(), [invRows]);
  const vendors = useMemo(() => Array.from(new Set(invRows.map((r) => r.vendor_id))).sort((a, b) => a - b), [invRows]);

  const slowMoving = useMemo(() => allStats.filter((s) => s.quantity > 0 && (s.last_sold_at === null || (now - new Date(s.last_sold_at).getTime()) / 86400000 > slowDays)), [allStats, slowDays, now]);

  // ── ABC Classification — dynamic thresholds ─────────────────────────────────
  const [abcMetric, setAbcMetric] = useState<"revenue" | "units" | "orders">("revenue");
  const [abcThreshA, setAbcThreshA] = useState(80); // % cumulative for A
  const [abcThreshB, setAbcThreshB] = useState(95); // % cumulative for A+B

  const abcStats = useMemo(() => {
    const getValue = (s: ProductStat) =>
      abcMetric === "revenue" ? s.total_revenue : abcMetric === "units" ? s.total_units_sold : s.order_count;
    const sorted = [...allStats].sort((a, b) => getValue(b) - getValue(a));
    const total = sorted.reduce((s, x) => s + getValue(x), 0);
    let cum = 0;
    const tA = abcThreshA / 100;
    const tB = abcThreshB / 100;
    return sorted.map((s) => {
      cum += getValue(s);
      const pct = total > 0 ? cum / total : 0;
      const abc: "A" | "B" | "C" = pct <= tA ? "A" : pct <= tB ? "B" : "C";
      return { ...s, abc, metricValue: getValue(s) };
    });
  }, [allStats, abcMetric, abcThreshA, abcThreshB]);

  // ── Category performance ─────────────────────────────────────────────────────
  const categoryStats = useMemo(() => {
    const map = new Map<string, { units: number; revenue: number; products: number; stock_value: number }>();
    for (const s of allStats) {
      const cat = s.category || "Uncategorised";
      const ex = map.get(cat) ?? { units: 0, revenue: 0, products: 0, stock_value: 0 };
      ex.units += s.total_units_sold;
      ex.revenue += s.total_revenue;
      ex.products += 1;
      map.set(cat, ex);
    }
    return [...map.entries()].map(([cat, v]) => ({ cat, ...v })).sort((a, b) => b.revenue - a.revenue);
  }, [allStats]);

  // ── Vendor performance ───────────────────────────────────────────────────────
  const vendorStats = useMemo(() => {
    const map = new Map<number, { units: number; revenue: number; products: number; sold_products: number }>();
    for (const s of allStats) {
      const ex = map.get(s.vendor_id) ?? { units: 0, revenue: 0, products: 0, sold_products: 0 };
      ex.units += s.total_units_sold;
      ex.revenue += s.total_revenue;
      ex.products += 1;
      if (s.total_units_sold > 0) ex.sold_products += 1;
      map.set(s.vendor_id, ex);
    }
    return [...map.entries()].map(([vid, v]) => ({ vid, ...v })).sort((a, b) => b.revenue - a.revenue);
  }, [allStats]);

  // ── Seasonal pattern (monthly aggregated across all products) ────────────────
  const seasonalData = useMemo(() => {
    const monthly: Record<string, { units: number; revenue: number }> = {};
    for (const s of allStats) {
      for (const [mon, units] of Object.entries(s.monthly)) {
        if (!monthly[mon]) monthly[mon] = { units: 0, revenue: 0 };
        monthly[mon].units += units;
      }
    }
    // Also compute revenue per month from orders directly
    const activeOrders = orders.filter((o) => ["confirmed", "billed", "shipped"].includes(o.status) && new Date(o.created_at).getTime() >= fromMs && new Date(o.created_at).getTime() <= toMs);
    for (const o of activeOrders) {
      const mon = yyyyMM(o.created_at);
      if (!monthly[mon]) monthly[mon] = { units: 0, revenue: 0 };
      monthly[mon].revenue += parseFloat(o.total_amount ?? "0");
    }
    return Object.fromEntries(Object.entries(monthly).sort(([a], [b]) => a.localeCompare(b)));
  }, [allStats, orders, fromMs, toMs]);

  // ── Dead stock ───────────────────────────────────────────────────────────────
  const deadStockStats = useMemo(() => {
    return allStats
      .filter((s) => s.quantity > 0 && (s.last_sold_at === null || (now - new Date(s.last_sold_at).getTime()) / 86400000 > slowDays))
      .sort((a, b) => b.quantity - a.quantity);
  }, [allStats, slowDays, now]);

  const deadStockValue = useMemo(() => deadStockStats.reduce((sum, s) => sum + s.quantity * (s.buying_price || 0), 0), [deadStockStats]);

  // ── KPI summary ──────────────────────────────────────────────────────────────
  const totalRevenue = allStats.reduce((s, r) => s + r.total_revenue, 0);
  const totalUnitsSold = allStats.reduce((s, r) => s + r.total_units_sold, 0);
  const productsWithSales = allStats.filter((s) => s.total_units_sold > 0).length;

  const TAB_LABELS: { id: AnalyticsTab; label: string }[] = [
    { id: "overview", label: "Overview" },
    { id: "trend", label: "Trend" },
    { id: "customers", label: "Customers" },
    { id: "category", label: "Category" },
    { id: "vendor", label: "Vendor" },
    { id: "seasonal", label: "Seasonal" },
    { id: "abc", label: "ABC" },
    { id: "deadstock", label: "Dead Stock" },
  ];

  return (
    <div className="mt-2 space-y-4">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-neutral-800">Product Analytics</h3>
          <p className="text-xs text-neutral-500">{lastLoaded ? `Loaded ${lastLoaded} · ` : ""}{orders.length} orders · {invRows.length} products</p>
        </div>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1 text-xs text-neutral-600">
            From <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)}
              className="ml-1 rounded border border-neutral-300 bg-white px-2 py-1" />
          </label>
          <label className="flex items-center gap-1 text-xs text-neutral-600">
            To <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)}
              className="ml-1 rounded border border-neutral-300 bg-white px-2 py-1" />
          </label>
          <button type="button" onClick={() => void loadOrders()} disabled={loading}
            className="rounded border border-neutral-300 bg-white px-3 py-1.5 text-xs hover:bg-neutral-50 disabled:opacity-50">
            {loading ? "Loading…" : "↺ Refresh"}
          </button>
        </div>
      </div>

      {msg && <p className="rounded bg-red-50 px-3 py-2 text-sm text-red-700">{msg}</p>}

      {/* KPI bar */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          { l: "Total revenue", v: fmtRupee(totalRevenue) },
          { l: "Units sold", v: totalUnitsSold.toLocaleString("en-IN") },
          { l: "Products selling", v: `${productsWithSales} / ${allStats.length}` },
          { l: "Slow movers", v: slowMoving.length.toString(), warn: slowMoving.length > 0 },
        ].map((k) => (
          <div key={k.l} className={`rounded border px-3 py-2 ${k.warn ? "border-yellow-300 bg-yellow-50" : "border-neutral-200 bg-white"}`}>
            <p className="text-[10px] uppercase tracking-wide text-neutral-400">{k.l}</p>
            <p className={`text-lg font-bold ${k.warn ? "text-yellow-800" : "text-neutral-800"}`}>{k.v}</p>
          </div>
        ))}
      </div>

      {/* Tab bar */}
      <div className="flex flex-wrap gap-0.5 border-b border-neutral-200">
        {TAB_LABELS.map((t) => (
          <button key={t.id} type="button" onClick={() => setActiveTab(t.id)}
            className={`px-3 py-2 text-xs font-medium transition-colors ${activeTab === t.id ? "border-b-2 border-blue-600 text-blue-700" : "text-neutral-500 hover:text-neutral-800"}`}>
            {t.label}
          </button>
        ))}
      </div>

      {/* ══════════════ OVERVIEW TAB ══════════════ */}
      {activeTab === "overview" && (
        <div className="space-y-3">
          {/* Product picker */}
          <div className="rounded border border-neutral-200 bg-neutral-50 p-3">
            <label className="block text-xs font-semibold text-neutral-600 mb-1">View detail for a specific product</label>
            <div className="flex gap-2">
              <select value={selectedId ?? ""} onChange={(e) => setSelectedId(e.target.value ? Number(e.target.value) : null)}
                className="flex-1 rounded border border-neutral-300 bg-white px-2 py-1.5 text-sm">
                <option value="">— Select a product —</option>
                {invRows.slice().sort((a, b) => a.our_product_id.localeCompare(b.our_product_id)).map((p) => (
                  <option key={p.catalog_product_id} value={p.catalog_product_id}>{p.our_product_id} — {p.name}</option>
                ))}
              </select>
              {selectedId !== null && <button type="button" onClick={() => setSelectedId(null)} className="rounded border border-neutral-300 bg-white px-2 py-1 text-xs hover:bg-neutral-100">Clear</button>}
            </div>
          </div>

          {selectedStat && (
            <ProductDetailPanel stat={selectedStat} vendorLabel={vendorLabel} onClose={() => setSelectedId(null)} activeView="buyers" dateFrom={dateFrom} dateTo={dateTo} />
          )}

          {/* Filters */}
          <div className="flex flex-wrap items-end gap-2 rounded border border-neutral-200 bg-neutral-50 p-2 text-xs">
            <label className="block"><span className="text-neutral-500">Vendor</span>
              <select value={filterVendor} onChange={(e) => setFilterVendor(e.target.value)} className="mt-0.5 block rounded border border-neutral-300 bg-white px-2 py-1">
                <option value="">All</option>{vendors.map((v) => <option key={v} value={v}>{vendorLabel(v)}</option>)}
              </select>
            </label>
            <label className="block"><span className="text-neutral-500">Category</span>
              <select value={filterCategory} onChange={(e) => setFilterCategory(e.target.value)} className="mt-0.5 block rounded border border-neutral-300 bg-white px-2 py-1">
                <option value="">All</option>{categories.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </label>
            <label className="block flex-1 min-w-[8rem]"><span className="text-neutral-500">Search</span>
              <input value={filterQ} onChange={(e) => setFilterQ(e.target.value)} placeholder="SKU / name" className="mt-0.5 w-full rounded border border-neutral-300 bg-white px-2 py-1" />
            </label>
            <label className="block"><span className="text-neutral-500">Sort</span>
              <select value={sortBy} onChange={(e) => setSortBy(e.target.value as typeof sortBy)} className="mt-0.5 block rounded border border-neutral-300 bg-white px-2 py-1">
                <option value="units_sold">Units sold ↓</option>
                <option value="revenue">Revenue ↓</option>
                <option value="sell_rate">Rate/day ↓</option>
                <option value="days_stock">Days left ↑</option>
                <option value="stock">Stock qty ↓</option>
                <option value="last_sold">Last sold ↓</option>
              </select>
            </label>
            <label className="flex cursor-pointer items-center gap-1 mt-2">
              <input type="checkbox" checked={showOnlyActive} onChange={(e) => setShowOnlyActive(e.target.checked)} />
              <span className="text-neutral-500">Only with sales</span>
            </label>
          </div>

          {/* Slow movers */}
          {slowMoving.length > 0 && (
            <div className="rounded border border-yellow-300 bg-yellow-50 p-2">
              <p className="text-xs font-semibold text-yellow-900 mb-1">
                ⚠ {slowMoving.length} slow movers — no sale in
                <input type="number" min={1} value={slowDays} onChange={(e) => setSlowDays(parseInt(e.target.value) || 30)}
                  className="mx-1 w-10 rounded border border-yellow-300 px-1 py-0.5 text-center text-xs" /> days:
              </p>
              <div className="flex flex-wrap gap-1">
                {slowMoving.slice(0, 30).map((s) => (
                  <button key={s.catalog_product_id} type="button" onClick={() => setSelectedId(s.catalog_product_id)}
                    className="rounded bg-yellow-100 px-1.5 py-0.5 font-mono text-[11px] text-yellow-900 hover:bg-yellow-200">
                    {s.our_product_id} ({s.quantity})
                  </button>
                ))}
                {slowMoving.length > 30 && <span className="text-xs text-yellow-700">+{slowMoving.length - 30} more</span>}
              </div>
            </div>
          )}

          {/* Table */}
          <div className="overflow-x-auto rounded border border-neutral-200">
            <table className="w-full border-collapse text-xs">
              <thead>
                <tr className="bg-neutral-100 text-left">
                  {["SKU", "Name", "Category", "Vendor", "Stock", "Status", "Units sold", "Revenue", "Rate/day"].map((h) => (
                    <th key={h} className="border-b border-neutral-200 px-2 py-1.5 font-semibold">{h}</th>
                  ))}
                  <th className="border-b border-neutral-200 px-2 py-1.5 font-semibold" title="Current stock ÷ avg daily sell rate = how many days until you run out. Red &lt;7d, yellow &lt;30d.">
                    Days left ⓘ
                  </th>
                  <th className="border-b border-neutral-200 px-2 py-1.5 font-semibold">Last sold</th>
                </tr>
              </thead>
              <tbody>
                {overviewStats.length === 0 ? (
                  <tr><td colSpan={11} className="px-4 py-6 text-center text-neutral-400">{loading ? "Loading…" : "No products match filters."}</td></tr>
                ) : overviewStats.map((s) => {
                  const isSel = selectedId === s.catalog_product_id;
                  const isSlow = s.quantity > 0 && (s.last_sold_at === null || (now - new Date(s.last_sold_at).getTime()) / 86400000 > slowDays);
                  return (
                    <tr key={s.catalog_product_id} onClick={() => setSelectedId(isSel ? null : s.catalog_product_id)}
                      className={`cursor-pointer border-b border-neutral-100 ${isSel ? "bg-blue-100" : isSlow ? "bg-yellow-50 hover:bg-yellow-100" : "hover:bg-neutral-50"}`}>
                      <td className="px-2 py-1.5 font-mono text-[11px]">{s.our_product_id}</td>
                      <td className="max-w-[130px] truncate px-2 py-1.5 font-medium" title={s.name}>{s.name}</td>
                      <td className="px-2 py-1.5 text-neutral-500">{s.category || "—"}</td>
                      <td className="px-2 py-1.5 text-neutral-500">{vendorLabel(s.vendor_id)}</td>
                      <td className="px-2 py-1.5 text-right font-medium">{s.quantity}</td>
                      <td className="px-2 py-1.5">{stockBadge(s.stock_status)}</td>
                      <td className="px-2 py-1.5 text-right font-semibold">{s.total_units_sold > 0 ? <span className="text-emerald-700">{s.total_units_sold}</span> : <span className="text-neutral-400">0</span>}</td>
                      <td className="px-2 py-1.5 text-right">{s.total_revenue > 0 ? fmtRupee(s.total_revenue) : "—"}</td>
                      <td className="px-2 py-1.5 text-right">{s.sell_rate_per_day > 0 ? s.sell_rate_per_day.toFixed(2) : "—"}</td>
                      <td className="px-2 py-1.5 text-right">
                        {s.days_of_stock !== null ? (
                          <span className={s.days_of_stock < 7 ? "font-bold text-red-700" : s.days_of_stock < 30 ? "text-yellow-700" : "text-emerald-700"}>{s.days_of_stock}d</span>
                        ) : "—"}
                      </td>
                      <td className="px-2 py-1.5">{fmtDate(s.last_sold_at)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="text-[10px] text-neutral-400">Click a row to see full detail. {allMonths.length > 0 && `Data spans ${allMonths[0]} → ${allMonths[allMonths.length - 1]}.`}</p>
        </div>
      )}

      {/* ══════════════ TREND TAB ══════════════ */}
      {activeTab === "trend" && (
        <div className="space-y-4">
          <div className="rounded border border-neutral-200 bg-neutral-50 p-3">
            <label className="block text-xs font-semibold text-neutral-600 mb-1">Select product to view month-over-month trend</label>
            <select value={trendProductId ?? ""} onChange={(e) => setTrendProductId(e.target.value ? Number(e.target.value) : null)}
              className="w-full rounded border border-neutral-300 bg-white px-3 py-2 text-sm">
              <option value="">— Choose a product —</option>
              {invRows.slice().sort((a, b) => a.our_product_id.localeCompare(b.our_product_id)).map((p) => (
                <option key={p.catalog_product_id} value={p.catalog_product_id}>{p.our_product_id} — {p.name}</option>
              ))}
            </select>
          </div>

          {trendStat ? (
            <div className="space-y-3">
              <div className="flex flex-wrap gap-3">
                <div className="rounded border border-neutral-200 bg-white px-3 py-2"><p className="text-[10px] text-neutral-400 uppercase">Total units sold</p><p className="text-lg font-bold">{trendStat.total_units_sold}</p></div>
                <div className="rounded border border-neutral-200 bg-white px-3 py-2"><p className="text-[10px] text-neutral-400 uppercase">Revenue</p><p className="text-lg font-bold">{fmtRupee(trendStat.total_revenue)}</p></div>
                <div className="rounded border border-neutral-200 bg-white px-3 py-2"><p className="text-[10px] text-neutral-400 uppercase">Current stock</p><p className="text-lg font-bold">{trendStat.quantity}</p></div>
              </div>

              {Object.keys(trendStat.monthly).length > 0 ? (
                <div className="rounded border border-neutral-200 bg-white p-4">
                  <p className="mb-3 text-xs font-semibold text-neutral-700">Units sold per month — {trendStat.our_product_id}</p>
                  <BarChart data={trendStat.monthly} color="bg-blue-500" height={100} />
                  {/* Month/value table */}
                  <div className="mt-4 overflow-x-auto">
                    <table className="text-xs border-collapse">
                      <thead><tr className="bg-neutral-50">{Object.keys(trendStat.monthly).map((m) => <th key={m} className="border border-neutral-200 px-2 py-1">{m}</th>)}</tr></thead>
                      <tbody><tr>{Object.values(trendStat.monthly).map((v, i) => <td key={i} className="border border-neutral-200 px-2 py-1 text-center font-semibold text-blue-700">{v}</td>)}</tr></tbody>
                    </table>
                  </div>
                  {/* MoM change */}
                  {Object.keys(trendStat.monthly).length >= 2 && (() => {
                    const vals = Object.entries(trendStat.monthly).sort(([a], [b]) => a.localeCompare(b));
                    const last = vals[vals.length - 1][1];
                    const prev = vals[vals.length - 2][1];
                    const diff = last - prev;
                    const pct = prev > 0 ? ((diff / prev) * 100).toFixed(1) : null;
                    return (
                      <p className={`mt-2 text-xs font-medium ${diff >= 0 ? "text-emerald-700" : "text-red-700"}`}>
                        Month-on-month: {diff >= 0 ? "▲" : "▼"} {Math.abs(diff)} units {pct !== null ? `(${pct}%)` : ""} vs previous month
                      </p>
                    );
                  })()}
                </div>
              ) : (
                <p className="rounded border border-yellow-200 bg-yellow-50 p-3 text-xs text-yellow-800">No sales in this date range for {trendStat.name}.</p>
              )}

              <ProductDetailPanel stat={trendStat} vendorLabel={vendorLabel} onClose={() => setTrendProductId(null)} activeView="trend" dateFrom={dateFrom} dateTo={dateTo} />
            </div>
          ) : (
            <div className="rounded border border-neutral-200 bg-white p-4">
              <p className="mb-3 text-xs font-semibold text-neutral-700">All products — units sold per month</p>
              <BarChart data={Object.fromEntries(Object.entries(seasonalData).map(([m, v]) => [m, v.units]))} color="bg-blue-400" height={100} />
            </div>
          )}
        </div>
      )}

      {/* ══════════════ CUSTOMERS TAB ══════════════ */}
      {activeTab === "customers" && (
        <div className="space-y-3">
          {/* Top customers across all products */}
          {(() => {
            const custMap = new Map<number, { name: string; units: number; revenue: number; order_count: number; products: Set<number> }>();
            for (const s of allStats) {
              for (const b of s.buyers) {
                const ex = custMap.get(b.customer_id) ?? { name: b.customer_name, units: 0, revenue: 0, order_count: 0, products: new Set() };
                ex.units += b.units; ex.revenue += b.revenue; ex.order_count += b.order_count;
                ex.products.add(s.catalog_product_id);
                custMap.set(b.customer_id, ex);
              }
            }
            const rows = [...custMap.entries()].map(([id, v]) => ({ id, ...v, product_count: v.products.size })).sort((a, b) => b.revenue - a.revenue);
            const maxRev = rows[0]?.revenue ?? 1;
            return (
              <div className="overflow-x-auto rounded border border-neutral-200">
                <p className="bg-neutral-50 px-3 py-2 text-xs font-semibold text-neutral-700 border-b border-neutral-200">Top customers (all products, selected date range)</p>
                <table className="w-full border-collapse text-xs">
                  <thead>
                    <tr className="bg-neutral-100 text-left">
                      <th className="px-3 py-1.5 font-semibold">#</th>
                      <th className="px-3 py-1.5 font-semibold">Customer</th>
                      <th className="px-3 py-1.5 text-right font-semibold">Orders</th>
                      <th className="px-3 py-1.5 text-right font-semibold">Units bought</th>
                      <th className="px-3 py-1.5 text-right font-semibold">Revenue</th>
                      <th className="px-3 py-1.5 font-semibold">Share</th>
                      <th className="px-3 py-1.5 text-right font-semibold">Products</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.length === 0 ? (
                      <tr><td colSpan={7} className="px-4 py-6 text-center text-neutral-400">No orders in this period.</td></tr>
                    ) : rows.map((r, i) => (
                      <tr key={r.id} className="border-t border-neutral-100 hover:bg-neutral-50">
                        <td className="px-3 py-1.5 font-mono text-neutral-400">{i + 1}</td>
                        <td className="px-3 py-1.5 font-medium">{r.name}</td>
                        <td className="px-3 py-1.5 text-right">{r.order_count}</td>
                        <td className="px-3 py-1.5 text-right font-semibold text-emerald-700">{r.units}</td>
                        <td className="px-3 py-1.5 text-right font-semibold">{fmtRupee(r.revenue)}</td>
                        <td className="px-3 py-1.5"><MiniBar value={r.revenue} max={maxRev} color="bg-emerald-500" /></td>
                        <td className="px-3 py-1.5 text-right">{r.product_count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          })()}

          {/* Per-product top buyer */}
          <div className="overflow-x-auto rounded border border-neutral-200">
            <p className="bg-neutral-50 px-3 py-2 text-xs font-semibold text-neutral-700 border-b border-neutral-200">Top buyer per product</p>
            <table className="w-full border-collapse text-xs">
              <thead>
                <tr className="bg-neutral-100 text-left">
                  <th className="px-3 py-1.5 font-semibold">SKU</th>
                  <th className="px-3 py-1.5 font-semibold">Product</th>
                  <th className="px-3 py-1.5 font-semibold">Top buyer</th>
                  <th className="px-3 py-1.5 text-right font-semibold">Units</th>
                  <th className="px-3 py-1.5 font-semibold">% of product sales</th>
                  <th className="px-3 py-1.5 font-semibold">Total unique buyers</th>
                </tr>
              </thead>
              <tbody>
                {allStats.filter((s) => s.buyers.length > 0).sort((a, b) => b.total_units_sold - a.total_units_sold).map((s) => (
                  <tr key={s.catalog_product_id} className="border-t border-neutral-100 hover:bg-neutral-50">
                    <td className="px-3 py-1.5 font-mono text-[11px]">{s.our_product_id}</td>
                    <td className="max-w-[130px] truncate px-3 py-1.5" title={s.name}>{s.name}</td>
                    <td className="px-3 py-1.5 font-medium">{s.buyers[0].customer_name}</td>
                    <td className="px-3 py-1.5 text-right font-semibold text-emerald-700">{s.buyers[0].units}</td>
                    <td className="px-3 py-1.5"><MiniBar value={s.buyers[0].units} max={s.total_units_sold} color="bg-blue-500" /></td>
                    <td className="px-3 py-1.5 text-right">{s.buyers.length}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ══════════════ CATEGORY TAB ══════════════ */}
      {activeTab === "category" && (
        <div className="space-y-3">
          <div className="overflow-x-auto rounded border border-neutral-200">
            <table className="w-full border-collapse text-xs">
              <thead>
                <tr className="bg-neutral-100 text-left">
                  <th className="px-3 py-2 font-semibold">Category</th>
                  <th className="px-3 py-2 text-right font-semibold">Products</th>
                  <th className="px-3 py-2 text-right font-semibold">Units sold</th>
                  <th className="px-3 py-2 text-right font-semibold">Revenue</th>
                  <th className="px-3 py-2 font-semibold">Revenue share</th>
                </tr>
              </thead>
              <tbody>
                {categoryStats.map((c) => (
                  <tr key={c.cat} className="border-t border-neutral-100 hover:bg-neutral-50">
                    <td className="px-3 py-2 font-medium">{c.cat}</td>
                    <td className="px-3 py-2 text-right">{c.products}</td>
                    <td className="px-3 py-2 text-right font-semibold text-emerald-700">{c.units}</td>
                    <td className="px-3 py-2 text-right font-semibold">{fmtRupee(c.revenue)}</td>
                    <td className="px-3 py-2"><MiniBar value={c.revenue} max={categoryStats[0]?.revenue ?? 1} color="bg-purple-500" /></td>
                  </tr>
                ))}
                {categoryStats.length === 0 && <tr><td colSpan={5} className="px-4 py-6 text-center text-neutral-400">No data.</td></tr>}
              </tbody>
            </table>
          </div>
          {categoryStats.length > 0 && (
            <div className="rounded border border-neutral-200 bg-white p-4">
              <p className="mb-3 text-xs font-semibold text-neutral-700">Revenue by category</p>
              <BarChart data={Object.fromEntries(categoryStats.map((c) => [c.cat.slice(0, 10), c.revenue]))} color="bg-purple-400" height={80} />
            </div>
          )}
        </div>
      )}

      {/* ══════════════ VENDOR TAB ══════════════ */}
      {activeTab === "vendor" && (
        <div className="space-y-3">
          <div className="overflow-x-auto rounded border border-neutral-200">
            <table className="w-full border-collapse text-xs">
              <thead>
                <tr className="bg-neutral-100 text-left">
                  <th className="px-3 py-2 font-semibold">Vendor</th>
                  <th className="px-3 py-2 text-right font-semibold">Products</th>
                  <th className="px-3 py-2 text-right font-semibold">Products selling</th>
                  <th className="px-3 py-2 text-right font-semibold">Units sold</th>
                  <th className="px-3 py-2 text-right font-semibold">Revenue</th>
                  <th className="px-3 py-2 font-semibold">Revenue share</th>
                  <th className="px-3 py-2 text-right font-semibold">Sell-through %</th>
                </tr>
              </thead>
              <tbody>
                {vendorStats.map((v) => (
                  <tr key={v.vid} className="border-t border-neutral-100 hover:bg-neutral-50">
                    <td className="px-3 py-2 font-medium">{vendorLabel(v.vid)}</td>
                    <td className="px-3 py-2 text-right">{v.products}</td>
                    <td className="px-3 py-2 text-right text-emerald-700">{v.sold_products}</td>
                    <td className="px-3 py-2 text-right font-semibold text-emerald-700">{v.units}</td>
                    <td className="px-3 py-2 text-right font-semibold">{fmtRupee(v.revenue)}</td>
                    <td className="px-3 py-2"><MiniBar value={v.revenue} max={vendorStats[0]?.revenue ?? 1} color="bg-indigo-500" /></td>
                    <td className="px-3 py-2 text-right">{v.products > 0 ? Math.round((v.sold_products / v.products) * 100) : 0}%</td>
                  </tr>
                ))}
                {vendorStats.length === 0 && <tr><td colSpan={7} className="px-4 py-6 text-center text-neutral-400">No data.</td></tr>}
              </tbody>
            </table>
          </div>
          {vendorStats.length > 0 && (
            <div className="rounded border border-neutral-200 bg-white p-4">
              <p className="mb-3 text-xs font-semibold text-neutral-700">Revenue by vendor</p>
              <BarChart data={Object.fromEntries(vendorStats.map((v) => [vendorLabel(v.vid).slice(0, 10), v.revenue]))} color="bg-indigo-400" height={80} />
            </div>
          )}
        </div>
      )}

      {/* ══════════════ SEASONAL TAB ══════════════ */}
      {activeTab === "seasonal" && (
        <div className="space-y-4">
          <div className="rounded border border-neutral-200 bg-white p-4">
            <p className="mb-1 text-xs font-semibold text-neutral-700">Total units sold per month (all products)</p>
            <p className="mb-3 text-[10px] text-neutral-400">Use to identify peak and off-peak months</p>
            <BarChart data={Object.fromEntries(Object.entries(seasonalData).map(([m, v]) => [m, v.units]))} color="bg-blue-500" height={100} />
            {Object.keys(seasonalData).length === 0 && <p className="text-xs text-neutral-400">No data in selected range.</p>}
          </div>
          <div className="rounded border border-neutral-200 bg-white p-4">
            <p className="mb-1 text-xs font-semibold text-neutral-700">Revenue per month (₹)</p>
            <BarChart data={Object.fromEntries(Object.entries(seasonalData).map(([m, v]) => [m, Math.round(v.revenue)]))} color="bg-emerald-500" height={100} />
          </div>
          {/* Month table */}
          <div className="overflow-x-auto rounded border border-neutral-200">
            <table className="w-full border-collapse text-xs">
              <thead>
                <tr className="bg-neutral-100">
                  <th className="px-3 py-2 text-left font-semibold">Month</th>
                  <th className="px-3 py-2 text-right font-semibold">Units</th>
                  <th className="px-3 py-2 text-right font-semibold">Revenue</th>
                  <th className="px-3 py-2 font-semibold">Units trend</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(seasonalData).map(([m, v]) => (
                  <tr key={m} className="border-t border-neutral-100">
                    <td className="px-3 py-1.5 font-mono">{m}</td>
                    <td className="px-3 py-1.5 text-right font-semibold text-blue-700">{v.units}</td>
                    <td className="px-3 py-1.5 text-right">{fmtRupee(v.revenue)}</td>
                    <td className="px-3 py-1.5"><MiniBar value={v.units} max={Math.max(...Object.values(seasonalData).map((x) => x.units), 1)} color="bg-blue-500" /></td>
                  </tr>
                ))}
                {Object.keys(seasonalData).length === 0 && <tr><td colSpan={4} className="px-4 py-6 text-center text-neutral-400">No data.</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ══════════════ ABC TAB ══════════════ */}
      {activeTab === "abc" && (
        <div className="space-y-3">
          {/* Dynamic controls */}
          <div className="rounded border border-neutral-200 bg-neutral-50 p-3 space-y-3">
            <p className="text-xs font-semibold text-neutral-700">ABC segmentation rules</p>
            <div className="flex flex-wrap gap-4 text-xs">
              <label className="block">
                <span className="text-neutral-500">Classify by</span>
                <select value={abcMetric} onChange={(e) => setAbcMetric(e.target.value as typeof abcMetric)}
                  className="mt-0.5 block rounded border border-neutral-300 bg-white px-2 py-1.5">
                  <option value="revenue">Revenue (₹)</option>
                  <option value="units">Units sold</option>
                  <option value="orders">Number of orders</option>
                </select>
              </label>
              <label className="block">
                <span className="text-neutral-500">Class A — top</span>
                <div className="mt-0.5 flex items-center gap-1">
                  <input type="number" min={1} max={99} value={abcThreshA}
                    onChange={(e) => { const v = Math.min(parseInt(e.target.value) || 1, abcThreshB - 1); setAbcThreshA(v); }}
                    className="w-14 rounded border border-neutral-300 bg-white px-2 py-1.5 text-center font-semibold" />
                  <span className="text-neutral-400">% cumulative</span>
                </div>
              </label>
              <label className="block">
                <span className="text-neutral-500">Class A+B — top</span>
                <div className="mt-0.5 flex items-center gap-1">
                  <input type="number" min={abcThreshA + 1} max={99} value={abcThreshB}
                    onChange={(e) => { const v = Math.max(parseInt(e.target.value) || 2, abcThreshA + 1); setAbcThreshB(v); }}
                    className="w-14 rounded border border-neutral-300 bg-white px-2 py-1.5 text-center font-semibold" />
                  <span className="text-neutral-400">% cumulative</span>
                </div>
              </label>
            </div>
            <p className="text-[10px] text-neutral-400">
              A = products contributing the top {abcThreshA}% of {abcMetric} · B = next {abcThreshB - abcThreshA}% · C = remaining {100 - abcThreshB}%
            </p>
          </div>

          {/* Summary cards */}
          <div className="grid grid-cols-3 gap-3">
            {(["A", "B", "C"] as const).map((cls) => {
              const group = abcStats.filter((s) => s.abc === cls);
              const rev = group.reduce((s, x) => s + x.total_revenue, 0);
              const metricTotal = group.reduce((s, x) => s + x.metricValue, 0);
              const colors = { A: "border-emerald-300 bg-emerald-50", B: "border-blue-300 bg-blue-50", C: "border-neutral-200 bg-neutral-50" };
              const desc = {
                A: `Top ${abcThreshA}% ${abcMetric} — highest priority, keep in stock`,
                B: `${abcThreshA}–${abcThreshB}% ${abcMetric} — maintain stock levels`,
                C: `Bottom ${100 - abcThreshB}% ${abcMetric} — review, reduce or clear`,
              };
              return (
                <div key={cls} className={`rounded border p-3 ${colors[cls]}`}>
                  <p className="text-xl font-black text-neutral-700">Class {cls}</p>
                  <p className="text-[10px] text-neutral-500 mb-2 leading-tight">{desc[cls]}</p>
                  <p className="text-sm font-bold">{group.length} products</p>
                  <p className="text-xs text-neutral-600">{fmtRupee(rev)} revenue</p>
                  <p className="text-xs text-neutral-500">
                    {abcMetric === "units" ? `${metricTotal} units` : abcMetric === "orders" ? `${metricTotal} orders` : ""}
                  </p>
                </div>
              );
            })}
          </div>

          {/* Table */}
          <div className="overflow-x-auto rounded border border-neutral-200">
            <table className="w-full border-collapse text-xs">
              <thead>
                <tr className="bg-neutral-100 text-left">
                  <th className="px-3 py-2 font-semibold">Class</th>
                  <th className="px-3 py-2 font-semibold">SKU</th>
                  <th className="px-3 py-2 font-semibold">Name</th>
                  <th className="px-3 py-2 text-right font-semibold">
                    {abcMetric === "revenue" ? "Revenue" : abcMetric === "units" ? "Units sold" : "Orders"}
                  </th>
                  <th className="px-3 py-2 font-semibold">Cumulative share</th>
                  <th className="px-3 py-2 text-right font-semibold">Stock qty</th>
                  <th className="px-3 py-2 font-semibold" title="At current sell rate, how many days until this product runs out of stock">
                    Days of stock left ⓘ
                  </th>
                </tr>
              </thead>
              <tbody>
                {abcStats.map((s) => {
                  const badge = { A: "bg-emerald-100 text-emerald-800", B: "bg-blue-100 text-blue-800", C: "bg-neutral-100 text-neutral-600" };
                  return (
                    <tr key={s.catalog_product_id} className="border-t border-neutral-100 hover:bg-neutral-50">
                      <td className="px-3 py-1.5">
                        <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${badge[s.abc]}`}>{s.abc}</span>
                      </td>
                      <td className="px-3 py-1.5 font-mono text-[11px]">{s.our_product_id}</td>
                      <td className="max-w-[130px] truncate px-3 py-1.5" title={s.name}>{s.name}</td>
                      <td className="px-3 py-1.5 text-right font-semibold text-emerald-700">
                        {abcMetric === "revenue" ? fmtRupee(s.metricValue) : s.metricValue.toLocaleString("en-IN")}
                      </td>
                      <td className="px-3 py-1.5">
                        <MiniBar value={s.metricValue} max={abcStats[0]?.metricValue ?? 1}
                          color={s.abc === "A" ? "bg-emerald-500" : s.abc === "B" ? "bg-blue-400" : "bg-neutral-400"} />
                      </td>
                      <td className="px-3 py-1.5 text-right">{s.quantity}</td>
                      <td className="px-3 py-1.5">
                        {s.days_of_stock !== null ? (
                          <span className={s.days_of_stock < 7 ? "font-bold text-red-700" : s.days_of_stock < 30 ? "text-yellow-700" : "text-emerald-700"}>
                            {s.days_of_stock}d
                          </span>
                        ) : <span className="text-neutral-400">—</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="text-[10px] text-neutral-400">
            ⓘ <strong>Days of stock left</strong>: current stock ÷ average daily sell rate over the selected date range.
            E.g. 50 units in stock selling at 2/day = 25 days left. &ldquo;—&rdquo; means no sales recorded so rate cannot be computed.
          </p>
        </div>
      )}

      {/* ══════════════ DEAD STOCK TAB ══════════════ */}
      {activeTab === "deadstock" && (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-3">
            <div className="rounded border border-red-200 bg-red-50 px-4 py-3">
              <p className="text-[10px] uppercase text-red-400">Dead stock items</p>
              <p className="text-2xl font-black text-red-700">{deadStockStats.length}</p>
            </div>
            <div className="rounded border border-red-200 bg-red-50 px-4 py-3">
              <p className="text-[10px] uppercase text-red-400">Est. capital locked</p>
              <p className="text-2xl font-black text-red-700">{fmtRupee(deadStockValue)}</p>
              <p className="text-[10px] text-red-400">(at buying price)</p>
            </div>
            <div className="rounded border border-yellow-200 bg-yellow-50 px-4 py-3 flex items-center gap-2">
              <span className="text-xs text-neutral-600">No sale in</span>
              <input type="number" min={1} value={slowDays} onChange={(e) => setSlowDays(parseInt(e.target.value) || 30)}
                className="w-14 rounded border border-yellow-300 px-2 py-1 text-center text-sm font-semibold" />
              <span className="text-xs text-neutral-600">days</span>
            </div>
          </div>

          <div className="overflow-x-auto rounded border border-neutral-200">
            <table className="w-full border-collapse text-xs">
              <thead>
                <tr className="bg-neutral-100 text-left">
                  <th className="px-3 py-2 font-semibold">SKU</th>
                  <th className="px-3 py-2 font-semibold">Name</th>
                  <th className="px-3 py-2 font-semibold">Category</th>
                  <th className="px-3 py-2 font-semibold">Vendor</th>
                  <th className="px-3 py-2 text-right font-semibold">Stock qty</th>
                  <th className="px-3 py-2 text-right font-semibold">Capital locked</th>
                  <th className="px-3 py-2 font-semibold">Last sold</th>
                  <th className="px-3 py-2 text-right font-semibold">Days idle</th>
                </tr>
              </thead>
              <tbody>
                {deadStockStats.length === 0 ? (
                  <tr><td colSpan={8} className="px-4 py-6 text-center text-emerald-600 font-medium">No dead stock — all products sold recently 🎉</td></tr>
                ) : deadStockStats.map((s) => {
                  const daysIdle = s.last_sold_at ? Math.round((now - new Date(s.last_sold_at).getTime()) / 86400000) : null;
                  return (
                    <tr key={s.catalog_product_id} className="border-t border-neutral-100 hover:bg-red-50">
                      <td className="px-3 py-1.5 font-mono text-[11px]">{s.our_product_id}</td>
                      <td className="max-w-[130px] truncate px-3 py-1.5" title={s.name}>{s.name}</td>
                      <td className="px-3 py-1.5 text-neutral-500">{s.category || "—"}</td>
                      <td className="px-3 py-1.5 text-neutral-500">{vendorLabel(s.vendor_id)}</td>
                      <td className="px-3 py-1.5 text-right font-semibold">{s.quantity}</td>
                      <td className="px-3 py-1.5 text-right font-medium text-red-700">{s.buying_price > 0 ? fmtRupee(s.quantity * s.buying_price) : "—"}</td>
                      <td className="px-3 py-1.5">{fmtDate(s.last_sold_at)}</td>
                      <td className="px-3 py-1.5 text-right font-semibold text-red-600">{daysIdle !== null ? `${daysIdle}d` : "Never sold"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="text-[10px] text-neutral-400">Capital locked uses buying price from catalog. Items never sold in the selected date range are shown even if sold before.</p>
        </div>
      )}
    </div>
  );
}
