"use client";

import { useCallback, useEffect, useState } from "react";
import { apiUrl, fetchApi, formatApiError } from "@/lib/api";
import type { ARInvoicePublic, APBillPublic, CustomerPublic, ExpensePublic, VendorPublic } from "@/lib/types";

const INPUT = "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500";
const LABEL = "mb-1 block text-xs font-semibold text-slate-500 uppercase tracking-wider";
const BTN_PRIMARY = "inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-700 disabled:opacity-50";
const BTN_SECONDARY = "inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm transition hover:bg-slate-50";

interface Props {
  adminKey: string;
}

export function FinanceScreen({ adminKey }: Props) {
  const [tab, setTab] = useState<"payments" | "expenses" | "freight" | "reports">("payments");

  return (
    <div>
      <div className="mb-6 flex gap-2 flex-wrap">
        {([
          { id: "payments", label: "💳 Payments" },
          { id: "expenses", label: "🧾 Expenses" },
          { id: "freight",  label: "🚛 Freight" },
          { id: "reports",  label: "📊 P&L / GL" },
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

      {tab === "payments" && <PaymentsTab adminKey={adminKey} />}
      {tab === "expenses" && <ExpensesTab adminKey={adminKey} />}
      {tab === "freight"  && <FreightTab  adminKey={adminKey} />}
      {tab === "reports"  && <ReportsTab  adminKey={adminKey} />}
    </div>
  );
}

// ─────────────────────────────── PAYMENTS ───────────────────────────────

function PaymentsTab({ adminKey }: { adminKey: string }) {
  const [mode, setMode] = useState<"ar" | "ap">("ar");
  const [customers, setCustomers] = useState<CustomerPublic[]>([]);
  const [vendors, setVendors] = useState<VendorPublic[]>([]);
  const [arInvoices, setArInvoices] = useState<ARInvoicePublic[]>([]);
  const [apBills, setApBills] = useState<APBillPublic[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedEntity, setSelectedEntity] = useState("");
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null);
  const [saving, setSaving] = useState(false);
  const [apDetailModal, setApDetailModal] = useState<{ id: number } | null>(null);
  const [apDetail, setApDetail] = useState<{ po_items: any[]; receipts: any[] } | null>(null);
  const [apDetailLoading, setApDetailLoading] = useState(false);

  const headers = () => {
    const h: Record<string, string> = { "Content-Type": "application/json" };
    if (adminKey.trim()) h["X-Admin-Key"] = adminKey.trim();
    return h;
  };
  const headersAdmin = (): Record<string, string> => adminKey.trim() ? { "X-Admin-Key": adminKey.trim() } : {};

  const showToast = (msg: string, ok: boolean) => { setToast({ msg, ok }); setTimeout(() => setToast(null), 3500); };

  async function openApDetail(apId: number) {
    setApDetailModal({ id: apId });
    setApDetailLoading(true);
    setApDetail(null);
    const r = await fetchApi(apiUrl(`accounting/ap/${apId}/receipt-details`), { headers: headersAdmin() });
    if (r.ok) setApDetail(await r.json());
    setApDetailLoading(false);
  }

  const load = useCallback(async () => {
    if (!adminKey.trim()) return;
    setLoading(true);
    const [cr, vr, ar, ap] = await Promise.all([
      fetchApi(apiUrl("customers"), { headers: headersAdmin() }),
      fetchApi(apiUrl("vendors"), { headers: headersAdmin() }),
      fetchApi(apiUrl("accounting/ar"), { headers: headersAdmin() }),
      fetchApi(apiUrl("accounting/ap"), { headers: headersAdmin() }),
    ]);
    if (cr.ok) setCustomers(await cr.json());
    if (vr.ok) setVendors(await vr.json());
    if (ar.ok) setArInvoices(await ar.json());
    if (ap.ok) setApBills(await ap.json());
    setLoading(false);
  }, [adminKey]);

  useEffect(() => { void load(); }, [load]);

  const customerName = (id: number) => customers.find((c) => c.id === id)?.name ?? `#${id}`;
  const vendorName = (id: number) => {
    const v = vendors.find((v) => v.id === id);
    return v?.company_name || v?.person_name || `#${id}`;
  };

  // AR: filter by customer if selected
  const filteredAR = arInvoices.filter((inv) =>
    !selectedEntity || String(inv.customer_id) === selectedEntity
  );
  const filteredAP = apBills.filter((b) =>
    !selectedEntity || String(b.vendor_id) === selectedEntity
  );

  const totalAR = filteredAR.reduce((s, i) => s + Number(i.balance), 0);
  const totalAP = filteredAP.reduce((s, b) => s + Number(b.balance), 0);

  async function recordPayment(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!selectedEntity) { showToast("Select a customer or vendor first.", false); return; }
    setSaving(true);
    const fd = new FormData(e.currentTarget);
    const formData = new FormData();
    formData.append("amount", String(fd.get("amount_paid")));
    if (fd.get("txn_id")) formData.append("transaction_id", String(fd.get("txn_id")));
    if (fd.get("payment_date")) formData.append("payment_date", String(fd.get("payment_date")));

    const endpoint = mode === "ar"
      ? `accounting/ar/customer/${selectedEntity}/pay`
      : `accounting/ap/vendor/${selectedEntity}/pay`;
    const r = await fetchApi(apiUrl(endpoint), { method: "POST", headers: headersAdmin(), body: formData });
    const data = await r.json().catch(() => ({}));
    setSaving(false);
    if (!r.ok) { showToast(formatApiError(data), false); return; }
    showToast("Payment recorded.", true);
    (e.target as HTMLFormElement).reset();
    void load();
  }

  return (
    <div>
      {toast && (
        <div className={`fixed right-4 top-20 z-[200] rounded-lg px-4 py-3 text-sm font-medium shadow-lg ${toast.ok ? "bg-emerald-600 text-white" : "bg-red-600 text-white"}`}>
          {toast.msg}
        </div>
      )}

      {/* AR / AP toggle */}
      <div className="mb-6 flex items-center gap-3">
        {[
          { id: "ar", label: "Receivables (from customers)" },
          { id: "ap", label: "Payables (to vendors)" },
        ].map((m) => (
          <button
            key={m.id}
            type="button"
            onClick={() => { setMode(m.id as "ar" | "ap"); setSelectedEntity(""); }}
            className={`rounded-lg px-4 py-2 text-sm font-semibold transition ${mode === m.id ? "bg-slate-900 text-white" : "border border-slate-300 bg-white text-slate-700 hover:bg-slate-50"}`}
          >
            {m.label}
          </button>
        ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-5">
        {/* Entity list */}
        <div className="lg:col-span-2">
          <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
            {mode === "ar" ? "Customers" : "Vendors"}
          </div>
          <div className="space-y-1 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
            <div
              onClick={() => setSelectedEntity("")}
              className={`cursor-pointer px-4 py-3 text-sm transition hover:bg-blue-50 ${!selectedEntity ? "bg-blue-600 text-white" : ""}`}
            >
              <div className="font-medium">All</div>
              <div className={`text-xs ${!selectedEntity ? "text-blue-100" : "text-slate-400"}`}>
                Outstanding: ₹{mode === "ar" ? totalAR.toFixed(2) : totalAP.toFixed(2)}
              </div>
            </div>
            {mode === "ar"
              ? customers.map((c) => {
                  const balance = arInvoices.filter((i) => i.customer_id === c.id).reduce((s, i) => s + Number(i.balance), 0);
                  if (balance <= 0) return null;
                  return (
                    <div key={c.id} onClick={() => setSelectedEntity(String(c.id))} className={`cursor-pointer border-t border-slate-100 px-4 py-3 text-sm transition hover:bg-blue-50 ${selectedEntity === String(c.id) ? "bg-blue-50" : ""}`}>
                      <div className="font-medium text-slate-800">{c.name}</div>
                      <div className="text-xs text-slate-400">₹{balance.toFixed(2)} outstanding</div>
                    </div>
                  );
                })
              : vendors.map((v) => {
                  const balance = apBills.filter((b) => b.vendor_id === v.id).reduce((s, b) => s + Number(b.balance), 0);
                  if (balance <= 0) return null;
                  return (
                    <div key={v.id} onClick={() => setSelectedEntity(String(v.id))} className={`cursor-pointer border-t border-slate-100 px-4 py-3 text-sm transition hover:bg-blue-50 ${selectedEntity === String(v.id) ? "bg-blue-50" : ""}`}>
                      <div className="font-medium text-slate-800">{v.company_name || v.person_name}</div>
                      <div className="text-xs text-slate-400">₹{balance.toFixed(2)} outstanding</div>
                    </div>
                  );
                })
            }
          </div>
        </div>

        {/* Invoice / Bill list */}
        <div className="lg:col-span-3 space-y-4">
          <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50 text-xs font-semibold uppercase text-slate-500">
                  <th className="px-4 py-2 text-left">{mode === "ar" ? "Customer" : "Vendor"}</th>
                  <th className="px-4 py-2 text-right">Total</th>
                  <th className="px-4 py-2 text-right">Paid</th>
                  <th className="px-4 py-2 text-right">Balance</th>
                  <th className="px-4 py-2 text-left">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {mode === "ar"
                  ? filteredAR.map((inv) => (
                      <tr key={inv.id}>
                        <td className="px-4 py-2 font-medium">{customerName(inv.customer_id)}</td>
                        <td className="px-4 py-2 text-right">₹{inv.amount}</td>
                        <td className="px-4 py-2 text-right text-emerald-600">₹{inv.amount_paid}</td>
                        <td className="px-4 py-2 text-right font-bold text-slate-900">₹{inv.balance}</td>
                        <td className="px-4 py-2">
                          <span className={`rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${inv.status === "paid" ? "bg-emerald-50 text-emerald-700 ring-emerald-200" : "bg-amber-50 text-amber-700 ring-amber-200"}`}>
                            {inv.status}
                          </span>
                        </td>
                      </tr>
                    ))
                  : filteredAP.map((b) => (
                      <tr key={b.id} onClick={() => openApDetail(b.id)} className="cursor-pointer hover:bg-blue-50">
                        <td className="px-4 py-2 font-medium">{vendorName(b.vendor_id)}</td>
                        <td className="px-4 py-2 text-right">₹{b.amount}</td>
                        <td className="px-4 py-2 text-right text-emerald-600">₹{b.amount_paid}</td>
                        <td className="px-4 py-2 text-right font-bold text-slate-900">₹{b.balance}</td>
                        <td className="px-4 py-2">
                          <span className={`rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${b.status === "paid" ? "bg-emerald-50 text-emerald-700 ring-emerald-200" : "bg-amber-50 text-amber-700 ring-amber-200"}`}>
                            {b.status}
                          </span>
                        </td>
                      </tr>
                    ))
                }
                {(mode === "ar" ? filteredAR : filteredAP).length === 0 && (
                  <tr><td colSpan={5} className="px-4 py-8 text-center text-slate-400">No open {mode === "ar" ? "receivables" : "payables"}.</td></tr>
                )}
              </tbody>
            </table>
          </div>

          {/* Record payment form */}
          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            {selectedEntity ? (
              <>
                <div className="mb-3 text-sm font-semibold text-slate-700">
                  Record payment for {mode === "ar"
                    ? customers.find((c) => String(c.id) === selectedEntity)?.name
                    : (() => { const v = vendors.find((v) => String(v.id) === selectedEntity); return v?.company_name || v?.person_name; })()
                  }
                </div>
                <div className="mb-3 rounded-lg bg-amber-50 border border-amber-200 px-3 py-2 text-sm">
                  Outstanding: <strong>₹{(mode === "ar" ? filteredAR : filteredAP).filter(x => x.status !== "paid").reduce((s, x) => s + Number(x.balance), 0).toFixed(2)}</strong>
                </div>
                <form onSubmit={recordPayment} className="grid grid-cols-2 gap-3">
                  <div>
                    <label className={LABEL}>Amount *</label>
                    <input name="amount_paid" type="number" required step="0.01" min="0.01" className={INPUT} />
                  </div>
                  <div>
                    <label className={LABEL}>Payment date *</label>
                    <input name="payment_date" type="date" required defaultValue={new Date().toISOString().slice(0, 10)} className={INPUT} />
                  </div>
                  <div className="col-span-2">
                    <label className={LABEL}>Transaction ID / reference</label>
                    <input name="txn_id" className={INPUT} placeholder="Optional UPI/cheque no." />
                  </div>
                  <div className="col-span-2">
                    <button type="submit" disabled={saving} className={BTN_PRIMARY}>
                      {saving ? "Saving…" : "Record payment"}
                    </button>
                  </div>
                </form>
              </>
            ) : (
              <div className="py-4 text-center text-sm text-slate-400">
                Select a {mode === "ar" ? "customer" : "vendor"} on the left to record a payment.
              </div>
            )}
          </div>
        </div>
      </div>

      {apDetailModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-2xl bg-white p-6 shadow-2xl">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-base font-bold text-slate-800">AP Bill Details</h3>
              <button type="button" onClick={() => { setApDetailModal(null); setApDetail(null); }} className="text-slate-400 hover:text-slate-600">✕</button>
            </div>
            {apDetailLoading ? (
              <div className="py-8 text-center text-slate-400">Loading…</div>
            ) : apDetail ? (
              <div className="space-y-4">
                <div>
                  <div className="mb-2 text-xs font-semibold uppercase text-slate-500">PO Items (Ordered)</div>
                  <table className="w-full text-sm border border-slate-200 rounded-lg overflow-hidden">
                    <thead><tr className="bg-slate-50 text-xs uppercase text-slate-500"><th className="px-3 py-2 text-left">Product ID</th><th className="px-3 py-2 text-right">Ordered</th></tr></thead>
                    <tbody className="divide-y divide-slate-100">
                      {(apDetail.po_items || []).map((item: any, i: number) => (
                        <tr key={i}><td className="px-3 py-2">{item.our_product_id || item.catalog_product_id}</td><td className="px-3 py-2 text-right">{item.quantity}</td></tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div>
                  <div className="mb-2 text-xs font-semibold uppercase text-slate-500">Receipts / Vendor Bills</div>
                  {(apDetail.receipts || []).length === 0 ? (
                    <div className="text-sm text-slate-400 py-4 text-center">No receipts found.</div>
                  ) : (
                    <div className="space-y-3">
                      {apDetail.receipts.map((r: any) => (
                        <div key={r.id} className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                          <div className="flex items-center gap-3 mb-2">
                            {r.vendor_bill_no && <span className="rounded-full bg-blue-100 px-3 py-0.5 text-xs font-semibold text-blue-700">Bill #{r.vendor_bill_no}</span>}
                            {r.receipt_number && <span className="text-xs text-slate-500">Receipt: {r.receipt_number}</span>}
                            <span className="ml-auto text-xs text-slate-400">{r.created_at ? new Date(r.created_at).toLocaleDateString("en-IN") : ""}</span>
                          </div>
                          <table className="w-full text-xs">
                            <thead><tr className="text-slate-500"><th className="text-left py-1">Product</th><th className="text-right py-1">Qty</th></tr></thead>
                            <tbody>
                              {(r.line_items || []).map((li: any, i: number) => (
                                <tr key={i}><td className="py-0.5">{li.catalog_product_id}</td><td className="text-right py-0.5">{li.quantity}</td></tr>
                              ))}
                            </tbody>
                          </table>
                          {r.note && <div className="mt-1 text-xs text-slate-500 italic">{r.note}</div>}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ) : (
              <div className="py-8 text-center text-slate-400">No details available.</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────── EXPENSES ───────────────────────────────

const EXPENSE_CATEGORIES = ["Rent", "Salary", "Transport", "Packaging", "Utilities", "Marketing", "Miscellaneous"];

type ExpenseRow = { date: string; category: string; description: string; amount: string; payment_mode: string; reference: string };
const blankRow = (): ExpenseRow => ({ date: new Date().toISOString().slice(0, 10), category: "", description: "", amount: "", payment_mode: "cash", reference: "" });

function ExpensesTab({ adminKey }: { adminKey: string }) {
  const [expenses, setExpenses] = useState<ExpensePublic[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null);
  const [rows, setRows] = useState<ExpenseRow[]>([blankRow()]);

  const headers = () => {
    const h: Record<string, string> = { "Content-Type": "application/json" };
    if (adminKey.trim()) h["X-Admin-Key"] = adminKey.trim();
    return h;
  };
  const headersAdmin = (): Record<string, string> => adminKey.trim() ? { "X-Admin-Key": adminKey.trim() } : {};

  const showToast = (msg: string, ok: boolean) => { setToast({ msg, ok }); setTimeout(() => setToast(null), 3500); };

  const load = useCallback(async () => {
    if (!adminKey.trim()) return;
    setLoading(true);
    const r = await fetchApi(apiUrl("expenses"), { headers: headersAdmin() });
    if (r.ok) setExpenses(await r.json());
    setLoading(false);
  }, [adminKey]);

  useEffect(() => { void load(); }, [load]);

  function updateRow(i: number, field: keyof ExpenseRow, val: string) {
    setRows((prev) => prev.map((r, j) => j === i ? { ...r, [field]: val } : r));
  }

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const valid = rows.filter((r) => r.category && Number(r.amount) > 0);
    if (!valid.length) { showToast("Add at least one expense with category and amount.", false); return; }
    setSaving(true);
    let saved = 0;
    for (const row of valid) {
      const body = { expense_date: row.date, category: row.category, description: row.description || null, amount: row.amount, payment_mode: row.payment_mode, reference: row.reference || null };
      const r = await fetchApi(apiUrl("expenses"), { method: "POST", headers: headers(), body: JSON.stringify(body) });
      if (r.ok) saved++;
    }
    setSaving(false);
    showToast(`${saved} expense${saved !== 1 ? "s" : ""} recorded.`, true);
    setRows([blankRow()]);
    void load();
  }

  const total = expenses.reduce((s, e) => s + Number(e.amount), 0);

  return (
    <div>
      {toast && (
        <div className={`fixed right-4 top-20 z-[200] rounded-lg px-4 py-3 text-sm font-medium shadow-lg ${toast.ok ? "bg-emerald-600 text-white" : "bg-red-600 text-white"}`}>
          {toast.msg}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-5">
        {/* Multi-row entry form */}
        <div className="lg:col-span-3">
          <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
            <div className="border-b border-slate-100 px-5 py-4">
              <div className="text-sm font-semibold text-slate-700">Record expenses</div>
              <div className="mt-0.5 text-xs text-slate-400">Add multiple rows and save all at once</div>
            </div>
            <form onSubmit={onSubmit}>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-100 bg-slate-50 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                      <th className="px-3 py-2 text-left">Date</th>
                      <th className="px-3 py-2 text-left">Category *</th>
                      <th className="px-3 py-2 text-left">Description</th>
                      <th className="px-3 py-2 text-right">Amount ₹ *</th>
                      <th className="px-3 py-2 text-left">Mode</th>
                      <th className="px-3 py-2 text-left">Ref.</th>
                      <th className="px-3 py-2" />
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row, i) => (
                      <tr key={i} className="border-b border-slate-100">
                        <td className="px-2 py-1.5">
                          <input type="date" value={row.date} onChange={(e) => updateRow(i, "date", e.target.value)}
                            className="w-32 rounded border border-slate-300 px-2 py-1 text-xs focus:border-blue-500 focus:outline-none" />
                        </td>
                        <td className="px-2 py-1.5">
                          <select value={row.category} onChange={(e) => updateRow(i, "category", e.target.value)}
                            className="w-32 rounded border border-slate-300 px-2 py-1 text-xs focus:border-blue-500 focus:outline-none">
                            <option value="">— select —</option>
                            {EXPENSE_CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
                          </select>
                        </td>
                        <td className="px-2 py-1.5">
                          <input value={row.description} onChange={(e) => updateRow(i, "description", e.target.value)}
                            placeholder="Optional" className="w-36 rounded border border-slate-300 px-2 py-1 text-xs focus:border-blue-500 focus:outline-none" />
                        </td>
                        <td className="px-2 py-1.5">
                          <input type="number" step="0.01" min="0.01" value={row.amount} onChange={(e) => updateRow(i, "amount", e.target.value)}
                            className="w-24 rounded border border-slate-300 px-2 py-1 text-right text-xs focus:border-blue-500 focus:outline-none" />
                        </td>
                        <td className="px-2 py-1.5">
                          <select value={row.payment_mode} onChange={(e) => updateRow(i, "payment_mode", e.target.value)}
                            className="w-24 rounded border border-slate-300 px-2 py-1 text-xs focus:border-blue-500 focus:outline-none">
                            <option value="cash">Cash</option>
                            <option value="upi">UPI</option>
                            <option value="bank_transfer">Bank</option>
                            <option value="cheque">Cheque</option>
                          </select>
                        </td>
                        <td className="px-2 py-1.5">
                          <input value={row.reference} onChange={(e) => updateRow(i, "reference", e.target.value)}
                            placeholder="Ref #" className="w-24 rounded border border-slate-300 px-2 py-1 text-xs focus:border-blue-500 focus:outline-none" />
                        </td>
                        <td className="px-2 py-1.5 text-center">
                          {rows.length > 1 && (
                            <button type="button" onClick={() => setRows((p) => p.filter((_, j) => j !== i))}
                              className="text-slate-300 hover:text-red-500">✕</button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="flex items-center gap-3 px-5 py-4">
                <button type="button" onClick={() => setRows((p) => [...p, blankRow()])}
                  className="text-sm text-blue-600 hover:underline">+ Add another row</button>
                <div className="ml-auto flex items-center gap-3">
                  {rows.filter((r) => Number(r.amount) > 0).length > 0 && (
                    <span className="text-sm text-slate-500">
                      Total: ₹{rows.filter((r) => Number(r.amount) > 0).reduce((s, r) => s + Number(r.amount), 0).toFixed(2)}
                    </span>
                  )}
                  <button type="submit" disabled={saving}
                    className={BTN_PRIMARY}>
                    {saving ? "Saving…" : `Save ${rows.filter((r) => r.category && Number(r.amount) > 0).length || ""} expense${rows.filter((r) => r.category && Number(r.amount) > 0).length !== 1 ? "s" : ""}`}
                  </button>
                </div>
              </div>
            </form>
          </div>
        </div>

        {/* Expense list */}
        <div className="lg:col-span-2">
          <div className="mb-3 flex items-center justify-between">
            <div className="text-sm font-semibold text-slate-700">History</div>
            <div className="rounded-lg bg-slate-100 px-3 py-1.5 text-sm font-semibold text-slate-700">
              ₹{total.toFixed(2)}
            </div>
          </div>
          {loading ? (
            <div className="py-8 text-center text-slate-400">Loading…</div>
          ) : expenses.length === 0 ? (
            <div className="rounded-xl border-2 border-dashed border-slate-200 py-12 text-center text-slate-400">
              <div className="text-3xl">🧾</div>
              <div className="mt-2 text-sm">No expenses yet</div>
            </div>
          ) : (
            <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-200 bg-slate-50 text-xs font-semibold uppercase text-slate-500">
                    <th className="px-3 py-2 text-left">Date</th>
                    <th className="px-3 py-2 text-left">Category</th>
                    <th className="px-3 py-2 text-right">Amount</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {expenses.map((exp) => (
                    <tr key={exp.id}>
                      <td className="px-3 py-2 text-xs text-slate-400">{exp.expense_date}</td>
                      <td className="px-3 py-2">
                        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">{exp.category}</span>
                        {exp.description && <div className="mt-0.5 text-xs text-slate-400">{exp.description}</div>}
                      </td>
                      <td className="px-3 py-2 text-right font-semibold text-slate-900">₹{exp.amount}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────── FREIGHT ───────────────────────────────

interface FreightVendorData { id: number; name: string; phone: string | null; notes: string | null; balance_due: string; }
interface FreightLedgerData { id: number; freight_vendor_id: number; entry_date: string; entry_type: string; amount: string; reference: string | null; notes: string | null; }

function FreightTab({ adminKey }: { adminKey: string }) {
  const [vendors, setVendors] = useState<FreightVendorData[]>([]);
  const [ledger, setLedger] = useState<FreightLedgerData[]>([]);
  const [selectedVendorId, setSelectedVendorId] = useState<number | null>(null);
  const [showAddVendor, setShowAddVendor] = useState(false);
  const [showAddEntry, setShowAddEntry] = useState(false);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null);

  const headers = () => {
    const h: Record<string, string> = { "Content-Type": "application/json" };
    if (adminKey.trim()) h["X-Admin-Key"] = adminKey.trim();
    return h;
  };
  const headersAdmin = (): Record<string, string> => adminKey.trim() ? { "X-Admin-Key": adminKey.trim() } : {};
  const showToast = (msg: string, ok: boolean) => { setToast({ msg, ok }); setTimeout(() => setToast(null), 3500); };

  const loadVendors = useCallback(async () => {
    if (!adminKey.trim()) return;
    const r = await fetchApi(apiUrl("freight-vendors"), { headers: headersAdmin() });
    if (r.ok) setVendors(await r.json());
  }, [adminKey]);

  const loadLedger = useCallback(async (vid: number) => {
    const r = await fetchApi(apiUrl(`freight-vendors/${vid}/ledger`), { headers: headersAdmin() });
    if (r.ok) setLedger(await r.json());
  }, [adminKey]);

  useEffect(() => { void loadVendors(); }, [loadVendors]);
  useEffect(() => {
    if (selectedVendorId !== null) void loadLedger(selectedVendorId);
    else setLedger([]);
  }, [selectedVendorId, loadLedger]);

  async function addVendor(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    setSaving(true);
    const r = await fetchApi(apiUrl("freight-vendors"), { method: "POST", headers: headers(), body: JSON.stringify({ name: fd.get("name"), phone: fd.get("phone") || null, notes: fd.get("notes") || null }) });
    setSaving(false);
    if (!r.ok) { showToast("Failed.", false); return; }
    showToast("Freight agent added.", true);
    setShowAddVendor(false);
    (e.target as HTMLFormElement).reset();
    void loadVendors();
  }

  async function addEntry(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!selectedVendorId) return;
    const fd = new FormData(e.currentTarget);
    setSaving(true);
    const r = await fetchApi(apiUrl("freight-vendors/ledger"), {
      method: "POST", headers: headers(),
      body: JSON.stringify({
        freight_vendor_id: selectedVendorId,
        entry_date: fd.get("entry_date"),
        entry_type: fd.get("entry_type"),
        amount: fd.get("amount"),
        reference: fd.get("reference") || null,
        notes: fd.get("notes") || null,
      }),
    });
    setSaving(false);
    if (!r.ok) { showToast("Failed.", false); return; }
    showToast("Entry recorded.", true);
    setShowAddEntry(false);
    (e.target as HTMLFormElement).reset();
    void loadVendors();
    void loadLedger(selectedVendorId);
  }

  const selectedVendor = vendors.find((v) => v.id === selectedVendorId);
  const totalCharged = ledger.filter((e) => e.entry_type === "charge").reduce((s, e) => s + Number(e.amount), 0);
  const totalPaid = ledger.filter((e) => e.entry_type === "payment").reduce((s, e) => s + Number(e.amount), 0);

  return (
    <div>
      {toast && <div className={`fixed right-4 top-20 z-[200] rounded-lg px-4 py-3 text-sm font-medium shadow-lg ${toast.ok ? "bg-emerald-600 text-white" : "bg-red-600 text-white"}`}>{toast.msg}</div>}
      <div className="grid gap-6 lg:grid-cols-3">
        {/* Vendor list */}
        <div>
          <div className="mb-3 flex items-center justify-between">
            <div className="text-sm font-semibold text-slate-700">Freight agents</div>
            <button type="button" onClick={() => setShowAddVendor(!showAddVendor)} className={BTN_PRIMARY}>+ Add</button>
          </div>
          {showAddVendor && (
            <form onSubmit={addVendor} className="mb-4 rounded-xl border border-slate-200 bg-white p-4 space-y-3">
              <div><label className={LABEL}>Name *</label><input name="name" required className={INPUT} placeholder="e.g. Vishnu Transport" /></div>
              <div><label className={LABEL}>Phone</label><input name="phone" className={INPUT} /></div>
              <div><label className={LABEL}>Notes</label><input name="notes" className={INPUT} /></div>
              <button type="submit" disabled={saving} className={BTN_PRIMARY}>{saving ? "Saving…" : "Add agent"}</button>
            </form>
          )}
          {vendors.length === 0 ? (
            <div className="rounded-xl border-2 border-dashed border-slate-200 py-8 text-center text-slate-400 text-sm">No freight agents yet</div>
          ) : (
            <div className="space-y-2">
              {vendors.map((v) => (
                <button key={v.id} type="button" onClick={() => setSelectedVendorId(selectedVendorId === v.id ? null : v.id)}
                  className={`w-full rounded-xl border p-3 text-left text-sm transition ${selectedVendorId === v.id ? "border-blue-300 bg-blue-50" : "border-slate-200 bg-white hover:border-blue-200 hover:bg-blue-50"}`}>
                  <div className="font-semibold text-slate-800">{v.name}</div>
                  {v.phone && <div className="text-xs text-slate-400">{v.phone}</div>}
                  <div className={`mt-1 text-sm font-bold ${Number(v.balance_due) > 0 ? "text-amber-700" : "text-slate-400"}`}>
                    {Number(v.balance_due) > 0 ? `Balance: ₹${v.balance_due}` : "Settled"}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Ledger */}
        <div className="lg:col-span-2">
          {!selectedVendor ? (
            <div className="rounded-xl border-2 border-dashed border-slate-200 py-16 text-center text-slate-400">
              <div className="text-4xl">🚛</div>
              <div className="mt-2 text-sm">Select a freight agent to view ledger</div>
            </div>
          ) : (
            <div>
              <div className="mb-3 flex items-center justify-between">
                <div>
                  <div className="text-base font-semibold text-slate-900">{selectedVendor.name}</div>
                  <div className="text-sm text-slate-500">
                    Charged: ₹{totalCharged.toFixed(2)} · Paid: ₹{totalPaid.toFixed(2)} ·{" "}
                    Balance: <span className={Number(selectedVendor.balance_due) > 0 ? "text-amber-700 font-bold" : "text-emerald-700 font-bold"}>₹{selectedVendor.balance_due}</span>
                  </div>
                </div>
                <button type="button" onClick={() => setShowAddEntry(!showAddEntry)} className={BTN_PRIMARY}>+ Record</button>
              </div>
              {showAddEntry && (
                <form onSubmit={addEntry} className="mb-4 grid grid-cols-2 gap-3 rounded-xl border border-slate-200 bg-white p-4">
                  <div><label className={LABEL}>Date *</label><input name="entry_date" type="date" required defaultValue={new Date().toISOString().slice(0, 10)} className={INPUT} /></div>
                  <div>
                    <label className={LABEL}>Type *</label>
                    <select name="entry_type" required className={INPUT}>
                      <option value="charge">Charge (we owe them)</option>
                      <option value="payment">Payment (we paid them)</option>
                    </select>
                  </div>
                  <div><label className={LABEL}>Amount ₹ *</label><input name="amount" type="number" required step="0.01" min="0.01" className={INPUT} /></div>
                  <div><label className={LABEL}>Reference</label><input name="reference" placeholder="e.g. Order #123" className={INPUT} /></div>
                  <div className="col-span-2"><label className={LABEL}>Notes</label><input name="notes" className={INPUT} /></div>
                  <div className="col-span-2"><button type="submit" disabled={saving} className={BTN_PRIMARY}>{saving ? "Saving…" : "Record entry"}</button></div>
                </form>
              )}
              {ledger.length === 0 ? (
                <div className="rounded-xl border-2 border-dashed border-slate-200 py-8 text-center text-slate-400 text-sm">No entries yet</div>
              ) : (
                <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-slate-200 bg-slate-50 text-xs font-semibold uppercase text-slate-500">
                        <th className="px-4 py-2 text-left">Date</th>
                        <th className="px-4 py-2 text-left">Type</th>
                        <th className="px-4 py-2 text-right">Amount</th>
                        <th className="px-4 py-2 text-left">Reference</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {ledger.map((entry) => (
                        <tr key={entry.id} className={entry.entry_type === "payment" ? "bg-emerald-50/40" : ""}>
                          <td className="px-4 py-2 text-xs text-slate-400">{entry.entry_date}</td>
                          <td className="px-4 py-2">
                            <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${entry.entry_type === "payment" ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700"}`}>
                              {entry.entry_type === "payment" ? "Payment" : "Charge"}
                            </span>
                          </td>
                          <td className={`px-4 py-2 text-right font-semibold ${entry.entry_type === "payment" ? "text-emerald-700" : "text-slate-900"}`}>
                            {entry.entry_type === "payment" ? "−" : "+"}₹{entry.amount}
                          </td>
                          <td className="px-4 py-2 text-slate-400 text-xs">{entry.reference ?? entry.notes ?? "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────── REPORTS (P&L / GL / Journal) ───────────────

interface PnLData { date_from: string; date_to: string; revenue_total: string; expense_total: string; net_pnl: string; }
interface GLRow { account_code: string; name: string; kind: string; debit_total: string; credit_total: string; }
interface JournalLine { account_code: string; debit: string; credit: string; }
interface JournalEntry { id: number; posted_at: string; memo: string; ref_type: string; ref_id: number | null; lines: JournalLine[]; }

function ReportsTab({ adminKey }: { adminKey: string }) {
  const headersAdmin = (): Record<string, string> => adminKey.trim() ? { "X-Admin-Key": adminKey.trim() } : {};

  const today = new Date().toISOString().slice(0, 10);
  const _fy = new Date();
  const _fiscalFrom = _fy.getMonth() >= 6
    ? new Date(_fy.getFullYear(), 6, 1)
    : new Date(_fy.getFullYear() - 1, 6, 1);
  const _fiscalTo = new Date(_fiscalFrom.getFullYear() + 1, 5, 30);
  const firstOfFiscal = _fiscalFrom.toISOString().slice(0, 10);
  const endOfFiscal = _fiscalTo.toISOString().slice(0, 10);

  const [dateFrom, setDateFrom] = useState(firstOfFiscal);
  const [dateTo, setDateTo]     = useState(endOfFiscal);
  const [view, setView]         = useState<"pnl" | "gl" | "journal">("pnl");
  const [loading, setLoading]   = useState(false);

  const [pnl,     setPnl]     = useState<PnLData | null>(null);
  const [gl,      setGl]      = useState<GLRow[]>([]);
  const [journal, setJournal] = useState<JournalEntry[]>([]);
  const [expandedJE, setExpandedJE] = useState<number | null>(null);

  async function load() {
    if (!dateFrom || !dateTo) return;
    setLoading(true);
    const qs = `?date_from=${dateFrom}&date_to=${dateTo}`;
    try {
      if (view === "pnl") {
        const r = await fetchApi(apiUrl(`accounting/pnl${qs}`), { headers: headersAdmin() });
        if (r.ok) setPnl(await r.json());
      } else if (view === "gl") {
        const r = await fetchApi(apiUrl(`accounting/gl${qs}`), { headers: headersAdmin() });
        if (r.ok) setGl(await r.json());
      } else {
        const r = await fetchApi(apiUrl(`accounting/journal${qs}&limit=500`), { headers: headersAdmin() });
        if (r.ok) setJournal(await r.json());
      }
    } finally { setLoading(false); }
  }

  useEffect(() => { void load(); }, [view, dateFrom, dateTo]);

  const fmt = (s: string | number) => `₹${Number(s).toLocaleString("en-IN", { minimumFractionDigits: 2 })}`;
  const fmtDate = (s: string) => new Date(s).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });

  const kindColor: Record<string, string> = { revenue: "#16a34a", expense: "#dc2626", asset: "#2563eb", liability: "#7c3aed", equity: "#0891b2" };

  return (
    <div>
      {/* Date range + sub-tabs */}
      <div className="mb-5 flex flex-wrap items-end gap-3">
        <div>
          <label className={LABEL}>From</label>
          <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} className={INPUT} style={{ width: 148 }} />
        </div>
        <div>
          <label className={LABEL}>To</label>
          <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} className={INPUT} style={{ width: 148 }} />
        </div>
        <div className="flex gap-2 pb-0.5">
          {(["pnl", "gl", "journal"] as const).map((v) => (
            <button key={v} type="button" onClick={() => setView(v)}
              className={`rounded-lg px-4 py-2 text-sm font-semibold transition ${view === v ? "bg-slate-900 text-white" : "border border-slate-300 bg-white text-slate-600 hover:bg-slate-50"}`}>
              {v === "pnl" ? "P&L" : v === "gl" ? "General Ledger" : "Journal"}
            </button>
          ))}
        </div>
      </div>

      {loading && <div className="py-16 text-center text-slate-400 text-sm">Loading…</div>}

      {/* ── P&L ── */}
      {!loading && view === "pnl" && pnl && (
        <div>
          <div className="mb-6 grid grid-cols-3 gap-4">
            {[
              { label: "Revenue", value: pnl.revenue_total, color: "#16a34a", bg: "#f0fdf4" },
              { label: "Expenses", value: pnl.expense_total, color: "#dc2626", bg: "#fff5f5" },
              { label: "Net Profit / Loss", value: pnl.net_pnl, color: Number(pnl.net_pnl) >= 0 ? "#16a34a" : "#dc2626", bg: "#f8fafc" },
            ].map((c) => (
              <div key={c.label} style={{ background: c.bg, border: "1px solid #e2e8f0", borderRadius: 12, padding: "20px 24px", textAlign: "center" }}>
                <div style={{ fontSize: 24, fontWeight: 800, color: c.color }}>{fmt(c.value)}</div>
                <div style={{ fontSize: 12, color: "#64748b", marginTop: 4, textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 600 }}>{c.label}</div>
              </div>
            ))}
          </div>
          <div style={{ background: "#f8fafc", borderRadius: 10, padding: "16px 20px", fontSize: 13, color: "#475569" }}>
            Period: {fmtDate(pnl.date_from)} — {fmtDate(pnl.date_to)}
          </div>
          <div className="mt-4 rounded-xl border border-slate-200 p-4">
            <div className="text-sm font-semibold text-slate-700 mb-3">Revenue breakdown</div>
            <table className="w-full text-sm">
              <tbody>
                <tr className="border-b border-slate-100">
                  <td className="py-2 text-slate-600">Customer Sales (billed orders)</td>
                  <td className="py-2 text-right font-semibold text-emerald-700">{fmt(pnl.revenue_total)}</td>
                </tr>
                <tr className="border-b border-slate-100">
                  <td className="py-2 text-slate-600">Total Expenses (indirect + COGS)</td>
                  <td className="py-2 text-right font-semibold text-red-600">{fmt(pnl.expense_total)}</td>
                </tr>
                <tr>
                  <td className="py-3 font-bold text-slate-800">Net Profit / Loss</td>
                  <td className={`py-3 text-right font-bold text-lg ${Number(pnl.net_pnl) >= 0 ? "text-emerald-700" : "text-red-600"}`}>{fmt(pnl.net_pnl)}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── General Ledger ── */}
      {!loading && view === "gl" && (
        <div className="rounded-xl border border-slate-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-50">
                {["Code", "Account", "Type", "Debit", "Credit", "Net"].map((h, i) => (
                  <th key={h} className={`px-4 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500 ${i >= 3 ? "text-right" : "text-left"}`}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {gl.map((row, i) => {
                const net = Number(row.debit_total) - Number(row.credit_total);
                return (
                  <tr key={i} className="border-t border-slate-100 hover:bg-slate-50">
                    <td className="px-4 py-2.5 font-mono text-xs text-slate-500">{row.account_code}</td>
                    <td className="px-4 py-2.5 font-medium text-slate-800">{row.name}</td>
                    <td className="px-4 py-2.5">
                      <span style={{ fontSize: 11, fontWeight: 600, color: kindColor[row.kind] ?? "#64748b", background: `${kindColor[row.kind] ?? "#64748b"}18`, borderRadius: 6, padding: "2px 8px", textTransform: "capitalize" }}>
                        {row.kind}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-right text-slate-700">{fmt(row.debit_total)}</td>
                    <td className="px-4 py-2.5 text-right text-slate-700">{fmt(row.credit_total)}</td>
                    <td className={`px-4 py-2.5 text-right font-semibold ${net >= 0 ? "text-slate-800" : "text-red-600"}`}>{fmt(Math.abs(net))}</td>
                  </tr>
                );
              })}
              {gl.length === 0 && (
                <tr><td colSpan={6} className="px-4 py-12 text-center text-slate-400">No GL activity in this period.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* ── Journal ── */}
      {!loading && view === "journal" && (
        <div className="space-y-2">
          {journal.length === 0 && <div className="py-12 text-center text-slate-400 text-sm">No journal entries in this period.</div>}
          {journal.map((je) => (
            <div key={je.id} className="rounded-xl border border-slate-200 overflow-hidden">
              <div
                className="flex items-center justify-between px-4 py-3 bg-slate-50 cursor-pointer hover:bg-slate-100"
                onClick={() => setExpandedJE(expandedJE === je.id ? null : je.id)}
              >
                <div className="flex items-center gap-3">
                  <span className="font-mono text-xs text-slate-400">#{je.id}</span>
                  <span className="text-sm font-medium text-slate-800">{je.memo || "(no memo)"}</span>
                  {je.ref_type && (
                    <span className="rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700">{je.ref_type}{je.ref_id ? ` #${je.ref_id}` : ""}</span>
                  )}
                </div>
                <div className="flex items-center gap-3 text-xs text-slate-500">
                  <span>{fmtDate(je.posted_at)}</span>
                  <span>{expandedJE === je.id ? "▲" : "▼"}</span>
                </div>
              </div>
              {expandedJE === je.id && (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-white border-t border-slate-100">
                      <th className="px-4 py-2 text-left text-xs font-semibold text-slate-500">Account</th>
                      <th className="px-4 py-2 text-right text-xs font-semibold text-slate-500">Debit</th>
                      <th className="px-4 py-2 text-right text-xs font-semibold text-slate-500">Credit</th>
                    </tr>
                  </thead>
                  <tbody>
                    {je.lines.map((ln, li) => (
                      <tr key={li} className="border-t border-slate-50">
                        <td className="px-4 py-2 font-mono text-xs text-slate-600">{ln.account_code}</td>
                        <td className="px-4 py-2 text-right text-slate-700">{Number(ln.debit) > 0 ? fmt(ln.debit) : "—"}</td>
                        <td className="px-4 py-2 text-right text-slate-700">{Number(ln.credit) > 0 ? fmt(ln.credit) : "—"}</td>
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
