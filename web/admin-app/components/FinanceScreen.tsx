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
  const [tab, setTab] = useState<"payments" | "expenses" | "freight">("payments");

  return (
    <div>
      <div className="mb-6 flex gap-2">
        {([
          { id: "payments", label: "💳 Payments" },
          { id: "expenses", label: "🧾 Expenses" },
          { id: "freight",  label: "🚛 Freight" },
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
      ? `ar/customer/${selectedEntity}/pay`
      : `ap/vendor/${selectedEntity}/pay`;
    const r = await fetchApi(apiUrl(endpoint), { method: "POST", body: formData });
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
        <div className={`fixed right-4 top-20 z-50 rounded-lg px-4 py-3 text-sm font-medium shadow-lg ${toast.ok ? "bg-emerald-600 text-white" : "bg-red-600 text-white"}`}>
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
                      <tr key={b.id}>
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
        <div className={`fixed right-4 top-20 z-50 rounded-lg px-4 py-3 text-sm font-medium shadow-lg ${toast.ok ? "bg-emerald-600 text-white" : "bg-red-600 text-white"}`}>
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
      {toast && <div className={`fixed right-4 top-20 z-50 rounded-lg px-4 py-3 text-sm font-medium shadow-lg ${toast.ok ? "bg-emerald-600 text-white" : "bg-red-600 text-white"}`}>{toast.msg}</div>}
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
