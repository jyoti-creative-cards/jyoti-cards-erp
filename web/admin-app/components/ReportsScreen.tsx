"use client";

import { useEffect, useState } from "react";
import { apiUrl, fetchApi, formatApiError } from "@/lib/api";
import type { AuthState } from "@/lib/types";

interface Customer { id: number; name: string; company_name?: string }
interface Vendor   { id: number; name: string }
interface CatalogProduct { id: number; name: string; our_product_id: string }

interface Props { adminKey: string; auth: AuthState }

const REPORT_TYPES = [
  { value: "customer_sales",    label: "Customer Sales",     needsCustomer: true,  needsProduct: false, needsVendor: false },
  { value: "item_sales",        label: "Item Sales",         needsCustomer: false, needsProduct: true,  needsVendor: false },
  { value: "item_purchases",    label: "Item Purchases",     needsCustomer: false, needsProduct: true,  needsVendor: true  },
  { value: "overall_sales",     label: "Overall Sales",      needsCustomer: false, needsProduct: false, needsVendor: false },
  { value: "ar_summary",        label: "Accounts Receivable (AR)", needsCustomer: true,  needsProduct: false, needsVendor: false },
  { value: "ap_summary",        label: "Accounts Payable (AP)",    needsCustomer: false, needsProduct: false, needsVendor: true  },
];

const fmtMoney = (v: number) => `₹${v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

export function ReportsScreen({ adminKey, auth }: Props) {
  const headers = (): Record<string, string> => {
    const h: Record<string, string> = { "Content-Type": "application/json" };
    if (adminKey.trim()) h["X-Admin-Key"] = adminKey.trim();
    if (auth.type === "staff") h["Authorization"] = `Bearer ${auth.token}`;
    return h;
  };

  const [customers, setCustomers]   = useState<Customer[]>([]);
  const [vendors, setVendors]       = useState<Vendor[]>([]);
  const [products, setProducts]     = useState<CatalogProduct[]>([]);

  const [reportType, setReportType] = useState("customer_sales");
  const [customerId, setCustomerId] = useState("");
  const [vendorId, setVendorId]     = useState("");
  const [productId, setProductId]   = useState("");
  // Default to current fiscal year: July 1 → June 30
  const _today = new Date();
  const _fiscalStart = _today.getMonth() >= 6
    ? new Date(_today.getFullYear(), 6, 1)
    : new Date(_today.getFullYear() - 1, 6, 1);
  const _fiscalEnd = new Date(_fiscalStart.getFullYear() + 1, 5, 30);
  const [dateFrom, setDateFrom]     = useState(_fiscalStart.toISOString().slice(0, 10));
  const [dateTo, setDateTo]         = useState(_fiscalEnd.toISOString().slice(0, 10));
  const [loading, setLoading]       = useState(false);
  const [error, setError]           = useState("");
  const [result, setResult]         = useState<{ summary: Record<string, unknown>; rows: Record<string, unknown>[] } | null>(null);

  const meta = REPORT_TYPES.find(r => r.value === reportType)!;

  useEffect(() => {
    void Promise.all([
      fetchApi(apiUrl("customers"), { headers: headers() }).then(r => r.ok ? r.json() : []),
      fetchApi(apiUrl("vendors"),   { headers: headers() }).then(r => r.ok ? r.json() : []),
      fetchApi(apiUrl("catalog?all_catalog=true"), { headers: headers() }).then(r => r.ok ? r.json() : []),
    ]).then(([c, v, p]) => {
      setCustomers(c as Customer[]);
      setVendors(v as Vendor[]);
      setProducts((p as CatalogProduct[]));
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function run() {
    setLoading(true); setError(""); setResult(null);
    const body: Record<string, unknown> = { report_type: reportType };
    if (customerId) body.customer_id = Number(customerId);
    if (vendorId)   body.vendor_id   = Number(vendorId);
    if (productId)  body.catalog_product_id = Number(productId);
    if (dateFrom)   body.date_from = dateFrom;
    if (dateTo)     body.date_to   = dateTo;

    const r = await fetchApi(apiUrl("reports/query"), { method: "POST", headers: headers(), body: JSON.stringify(body) });
    const data = await r.json().catch(() => ({}));
    setLoading(false);
    if (!r.ok) { setError(formatApiError(data)); return; }
    setResult(data as { summary: Record<string, unknown>; rows: Record<string, unknown>[] });
  }

  const summaryKeys = result ? Object.entries(result.summary).filter(([, v]) => !Array.isArray(v)) : [];
  const topCustomers = result ? (result.summary.top_customers as {name: string; amount: number}[] | undefined) : null;
  const cols = result?.rows[0] ? Object.keys(result.rows[0]) : [];

  return (
    <div className="space-y-6 p-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-slate-900">Reports</h2>
          <p className="text-sm text-slate-500">Select report type, filters, and date range</p>
        </div>
      </div>

      {/* Controls */}
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm space-y-4">
        {/* Report type */}
        <div>
          <label className="mb-1 block text-xs font-semibold uppercase tracking-wider text-slate-500">Report Type</label>
          <div className="flex flex-wrap gap-2">
            {REPORT_TYPES.map(rt => (
              <button
                key={rt.value}
                type="button"
                onClick={() => { setReportType(rt.value); setResult(null); }}
                className={`rounded-full px-3 py-1.5 text-xs font-semibold border transition ${
                  reportType === rt.value
                    ? "bg-blue-600 text-white border-blue-600"
                    : "bg-white text-slate-600 border-slate-300 hover:bg-slate-50"
                }`}
              >{rt.label}</button>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {/* Customer filter */}
          {meta.needsCustomer && (
            <div>
              <label className="mb-1 block text-xs font-semibold uppercase tracking-wider text-slate-500">Customer</label>
              <select
                value={customerId}
                onChange={e => setCustomerId(e.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              >
                <option value="">All customers</option>
                {customers.map(c => <option key={c.id} value={c.id}>{c.company_name || c.name}</option>)}
              </select>
            </div>
          )}

          {/* Vendor filter */}
          {meta.needsVendor && (
            <div>
              <label className="mb-1 block text-xs font-semibold uppercase tracking-wider text-slate-500">Vendor</label>
              <select
                value={vendorId}
                onChange={e => setVendorId(e.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              >
                <option value="">All vendors</option>
                {vendors.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}
              </select>
            </div>
          )}

          {/* Product filter */}
          {meta.needsProduct && (
            <div>
              <label className="mb-1 block text-xs font-semibold uppercase tracking-wider text-slate-500">Product</label>
              <select
                value={productId}
                onChange={e => setProductId(e.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              >
                <option value="">— Select product —</option>
                {products.map(p => <option key={p.id} value={p.id}>{p.name} ({p.our_product_id})</option>)}
              </select>
            </div>
          )}

          {/* Date from */}
          <div>
            <label className="mb-1 block text-xs font-semibold uppercase tracking-wider text-slate-500">From Date</label>
            <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
          </div>

          {/* Date to */}
          <div>
            <label className="mb-1 block text-xs font-semibold uppercase tracking-wider text-slate-500">To Date</label>
            <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
          </div>
        </div>

        <button
          type="button"
          onClick={run}
          disabled={loading}
          className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 disabled:opacity-50"
        >
          {loading ? "Running…" : "Run Report"}
        </button>
        {error && <div className="text-sm text-red-600">{error}</div>}
      </div>

      {/* Results */}
      {result && (
        <div className="space-y-4">
          {/* Summary cards */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {summaryKeys.map(([k, v]) => {
              const isAmount = k.includes("amount") || k.includes("billed") || k.includes("paid") || k.includes("outstanding");
              const display = isAmount ? fmtMoney(Number(v)) : String(v);
              const label = k.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
              return (
                <div key={k} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm text-center">
                  <div className="text-xl font-bold text-slate-900">{display}</div>
                  <div className="text-xs text-slate-500 mt-1">{label}</div>
                </div>
              );
            })}
          </div>

          {/* Top customers (for overall_sales) */}
          {topCustomers && topCustomers.length > 0 && (
            <div className="rounded-2xl border border-slate-200 bg-white shadow-sm overflow-hidden">
              <div className="px-4 py-3 bg-slate-50 text-xs font-semibold uppercase tracking-wider text-slate-500 border-b border-slate-200">Top Customers</div>
              <table className="w-full text-sm">
                <thead><tr className="text-xs text-slate-500 bg-slate-50">
                  <th className="px-4 py-2 text-left">Customer</th>
                  <th className="px-4 py-2 text-right">Total</th>
                </tr></thead>
                <tbody>
                  {topCustomers.map((tc, i) => (
                    <tr key={i} className="border-t border-slate-100 hover:bg-slate-50">
                      <td className="px-4 py-2">{tc.name}</td>
                      <td className="px-4 py-2 text-right font-semibold">{fmtMoney(tc.amount)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Detail rows */}
          {result.rows.length > 0 ? (
            <div className="rounded-2xl border border-slate-200 bg-white shadow-sm overflow-x-auto">
              <div className="flex items-center justify-between px-4 py-3 bg-slate-50 border-b border-slate-200">
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                  {result.rows.length} records
                </span>
              </div>
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-slate-500 bg-slate-50">
                    {cols.map(c => (
                      <th key={c} className="px-4 py-2 text-left font-semibold capitalize">{c.replace(/_/g, " ")}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.rows.map((row, i) => (
                    <tr key={i} className="border-t border-slate-100 hover:bg-slate-50 transition">
                      {cols.map(c => {
                        const val = row[c];
                        const isAmt = c === "amount" || c === "paid" || c === "outstanding" || c === "unit_price";
                        return (
                          <td key={c} className={`px-4 py-2 ${isAmt ? "text-right font-mono" : ""}`}>
                            {isAmt ? fmtMoney(Number(val)) : String(val ?? "—")}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="rounded-2xl border border-slate-200 bg-white p-8 text-center text-sm text-slate-400 shadow-sm">
              No records found for the selected filters.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
