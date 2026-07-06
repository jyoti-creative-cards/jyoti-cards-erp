"use client";

import { useCallback, useEffect, useState } from "react";
import { apiUrl, authHeaders, fetchApi, formatApiError, jsonAuthHeaders } from "@/lib/api";
import type { AuthState, CreditNotePublicFull, CustomerPublic } from "@/lib/types";

const INPUT = "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500";
const LABEL = "mb-1 block text-xs font-semibold text-slate-500 uppercase tracking-wider";
const BTN = "inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 disabled:opacity-50";
const BTN_SM = "rounded px-2 py-1 text-xs font-medium";

const STATUS_COLORS: Record<string, string> = {
  open:     "bg-amber-100 text-amber-700",
  applied:  "bg-blue-100 text-blue-700",
  paid_out: "bg-emerald-100 text-emerald-700",
};

interface OrderItem {
  catalog_product_id: number;
  product_name: string;
  quantity: number;
  unit_price: number;
}

interface OrderData {
  id: number;
  status: string;
  items: OrderItem[];
  total_amount: string;
  created_at: string;
}

interface Props { auth: AuthState; canEdit: boolean; }

export function ReturnsScreen({ auth, canEdit }: Props) {
  const [notes, setNotes] = useState<CreditNotePublicFull[]>([]);
  const [customers, setCustomers] = useState<CustomerPublic[]>([]);
  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [filterCustomer, setFilterCustomer] = useState("");
  const [filterStatus, setFilterStatus] = useState("");

  // Create form state
  const [formCustomerId, setFormCustomerId] = useState("");
  const [formOrderId, setFormOrderId] = useState("");
  const [formOrder, setFormOrder] = useState<OrderData | null>(null);
  const [formReason, setFormReason] = useState("");
  const [formRefundMethod, setFormRefundMethod] = useState("credit");
  const [formReturnLines, setFormReturnLines] = useState<{ catalog_product_id: number; name: string; max: number; qty: number }[]>([]);
  const [saving, setSaving] = useState(false);

  const showToast = (msg: string, ok: boolean) => { setToast({ msg, ok }); setTimeout(() => setToast(null), 4000); };

  const load = useCallback(async () => {
    if (auth.type === "none") return;
    setLoading(true);
    const h = authHeaders(auth);
    const params = new URLSearchParams();
    if (filterCustomer) params.set("customer_id", filterCustomer);
    if (filterStatus) params.set("status", filterStatus);
    const [nr, cr] = await Promise.all([
      fetchApi(`${apiUrl("credit-notes")}?${params.toString()}`, { headers: h }),
      fetchApi(apiUrl("customers"), { headers: h }),
    ]);
    if (nr.ok) setNotes(await nr.json());
    if (cr.ok) setCustomers(await cr.json());
    setLoading(false);
  }, [auth, filterCustomer, filterStatus]);

  useEffect(() => { void load(); }, [load]);

  async function loadOrder() {
    if (!formOrderId.trim()) return;
    const r = await fetchApi(apiUrl(`customer-orders/${formOrderId}`), { headers: authHeaders(auth) });
    if (!r.ok) { showToast("Order not found", false); setFormOrder(null); return; }
    const data = await r.json() as OrderData;
    setFormOrder(data);
    setFormReturnLines(
      (data.items || []).map((it: OrderItem) => ({
        catalog_product_id: it.catalog_product_id,
        name: it.product_name || String(it.catalog_product_id),
        max: it.quantity,
        qty: it.quantity,
      }))
    );
  }

  async function submitReturn(e: React.FormEvent) {
    e.preventDefault();
    if (!formOrder || !formCustomerId) return;
    const lines = formReturnLines.filter(l => l.qty > 0);
    if (!lines.length) { showToast("Select at least 1 item", false); return; }
    setSaving(true);
    const body = {
      customer_id: Number(formCustomerId),
      customer_order_id: formOrder.id,
      reason: formReason || null,
      refund_method: formRefundMethod,
      return_items: lines.map(l => ({ catalog_product_id: l.catalog_product_id, quantity: l.qty })),
    };
    const r = await fetchApi(apiUrl("credit-notes"), { method: "POST", headers: jsonAuthHeaders(auth), body: JSON.stringify(body) });
    const data = await r.json().catch(() => ({}));
    setSaving(false);
    if (!r.ok) { showToast(formatApiError(data), false); return; }
    showToast("Credit note created.", true);
    setShowForm(false);
    resetForm();
    void load();
  }

  function resetForm() {
    setFormCustomerId(""); setFormOrderId(""); setFormOrder(null);
    setFormReason(""); setFormRefundMethod("credit"); setFormReturnLines([]);
  }

  async function applyNote(note: CreditNotePublicFull) {
    const billId = prompt("Enter Bill ID to apply this credit note against:");
    if (!billId) return;
    const r = await fetchApi(apiUrl(`credit-notes/${note.id}/apply`), {
      method: "POST", headers: jsonAuthHeaders(auth), body: JSON.stringify({ bill_id: Number(billId) }),
    });
    if (r.ok) { showToast("Applied to bill.", true); void load(); }
    else showToast(formatApiError(await r.json().catch(() => ({}))), false);
  }

  async function payoutNote(note: CreditNotePublicFull) {
    const n = prompt("Payout note (optional):");
    const r = await fetchApi(apiUrl(`credit-notes/${note.id}/payout`), {
      method: "POST", headers: jsonAuthHeaders(auth), body: JSON.stringify({ note: n }),
    });
    if (r.ok) { showToast("Marked as paid out.", true); void load(); }
    else showToast(formatApiError(await r.json().catch(() => ({}))), false);
  }

  async function deleteNote(id: number) {
    if (!confirm("Delete this credit note? Stock will be re-deducted.")) return;
    const r = await fetchApi(apiUrl(`credit-notes/${id}`), { method: "DELETE", headers: authHeaders(auth) });
    if (r.ok || r.status === 204) { showToast("Deleted.", true); void load(); }
    else showToast(formatApiError(await r.json().catch(() => ({}))), false);
  }

  const customerName = (id: number) => {
    const c = customers.find(c => c.id === id);
    return c ? (c.company_name || c.name) : `#${id}`;
  };

  return (
    <div>
      {toast && (
        <div className={`fixed right-4 top-20 z-[200] rounded-lg px-4 py-3 text-sm font-medium shadow-lg ${toast.ok ? "bg-emerald-600 text-white" : "bg-red-600 text-white"}`}>
          {toast.msg}
        </div>
      )}

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <h2 className="text-lg font-semibold text-slate-800">Returns &amp; Credit Notes</h2>
        <div className="ml-auto flex gap-2">
          <select value={filterCustomer} onChange={e => setFilterCustomer(e.target.value)} className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm">
            <option value="">All customers</option>
            {customers.map(c => <option key={c.id} value={c.id}>{c.company_name || c.name}</option>)}
          </select>
          <select value={filterStatus} onChange={e => setFilterStatus(e.target.value)} className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm">
            <option value="">All statuses</option>
            <option value="open">Open</option>
            <option value="applied">Applied</option>
            <option value="paid_out">Paid out</option>
          </select>
          {canEdit && (
            <button type="button" onClick={() => { setShowForm(v => !v); resetForm(); }} className={BTN}>
              {showForm ? "Cancel" : "+ Issue Credit Note"}
            </button>
          )}
        </div>
      </div>

      {/* Create form */}
      {showForm && (
        <form onSubmit={submitReturn} className="mb-6 rounded-xl border border-slate-200 bg-slate-50 p-5">
          <h3 className="mb-4 font-semibold text-slate-800">Issue Credit Note (Return)</h3>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <div>
              <label className={LABEL}>Customer *</label>
              <select required value={formCustomerId} onChange={e => setFormCustomerId(e.target.value)} className={INPUT}>
                <option value="">Select customer</option>
                {customers.map(c => <option key={c.id} value={c.id}>{c.company_name || c.name}</option>)}
              </select>
            </div>
            <div>
              <label className={LABEL}>Order ID *</label>
              <div className="flex gap-2">
                <input value={formOrderId} onChange={e => setFormOrderId(e.target.value)} placeholder="Enter order ID" className={INPUT} />
                <button type="button" onClick={loadOrder} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm hover:bg-slate-50">Load</button>
              </div>
            </div>
            <div>
              <label className={LABEL}>Refund method</label>
              <select value={formRefundMethod} onChange={e => setFormRefundMethod(e.target.value)} className={INPUT}>
                <option value="credit">Credit balance (use against future bill)</option>
                <option value="payout">Cash / bank payout</option>
              </select>
            </div>
            <div className="sm:col-span-2 lg:col-span-3">
              <label className={LABEL}>Reason</label>
              <input value={formReason} onChange={e => setFormReason(e.target.value)} placeholder="e.g. Damaged goods, wrong item…" className={INPUT} />
            </div>
          </div>

          {formOrder && (
            <div className="mt-4">
              <p className="mb-2 text-sm font-medium text-slate-700">Select items to return (set qty to 0 to skip):</p>
              <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50">
                    <tr>
                      <th className="px-3 py-2 text-left text-xs font-semibold text-slate-500">Product</th>
                      <th className="px-3 py-2 text-right text-xs font-semibold text-slate-500">Ordered</th>
                      <th className="px-3 py-2 text-right text-xs font-semibold text-slate-500">Return qty</th>
                    </tr>
                  </thead>
                  <tbody>
                    {formReturnLines.map((line, i) => (
                      <tr key={line.catalog_product_id} className="border-t border-slate-100">
                        <td className="px-3 py-2 text-slate-700">{line.name}</td>
                        <td className="px-3 py-2 text-right text-slate-500">{line.max}</td>
                        <td className="px-3 py-2 text-right">
                          <input
                            type="number" min={0} max={line.max} value={line.qty}
                            onChange={e => {
                              const v = Math.min(line.max, Math.max(0, Number(e.target.value)));
                              setFormReturnLines(prev => prev.map((l, j) => j === i ? { ...l, qty: v } : l));
                            }}
                            className="w-20 rounded border border-slate-300 px-2 py-1 text-right text-sm"
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="mt-2 text-right text-sm text-slate-600">
                Credit amount: <strong>
                  ₹{formReturnLines.reduce((sum, l) => {
                    const orderItem = formOrder.items.find(it => it.catalog_product_id === l.catalog_product_id);
                    const unitPrice = orderItem?.unit_price || 0;
                    return sum + unitPrice * l.qty;
                  }, 0).toFixed(2)}
                </strong>
              </div>
            </div>
          )}

          <div className="mt-4 flex gap-3">
            <button type="submit" disabled={saving || !formOrder} className={BTN}>
              {saving ? "Saving…" : "Issue Credit Note"}
            </button>
            <button type="button" onClick={() => { setShowForm(false); resetForm(); }}
              className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm text-slate-700 hover:bg-slate-50">
              Cancel
            </button>
          </div>
        </form>
      )}

      {/* Credit notes list */}
      {loading ? (
        <div className="py-16 text-center text-slate-400">Loading…</div>
      ) : notes.length === 0 ? (
        <div className="py-16 text-center text-slate-400">No credit notes found.</div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
          <table className="w-full text-sm">
            <thead className="border-b border-slate-200 bg-slate-50">
              <tr>
                <th className="px-4 py-3 text-left font-semibold text-slate-600">ID</th>
                <th className="px-4 py-3 text-left font-semibold text-slate-600">Customer</th>
                <th className="px-4 py-3 text-left font-semibold text-slate-600">Order</th>
                <th className="px-4 py-3 text-right font-semibold text-slate-600">Amount</th>
                <th className="px-4 py-3 text-left font-semibold text-slate-600">Type</th>
                <th className="px-4 py-3 text-left font-semibold text-slate-600">Status</th>
                <th className="px-4 py-3 text-left font-semibold text-slate-600">Date</th>
                <th className="px-4 py-3 text-left font-semibold text-slate-600">Items</th>
                {canEdit && <th className="px-4 py-3" />}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {notes.map(note => (
                <tr key={note.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3 font-mono text-slate-500">CN-{note.id}</td>
                  <td className="px-4 py-3 font-medium text-slate-800">{customerName(note.customer_id)}</td>
                  <td className="px-4 py-3 text-slate-500">#{note.customer_order_id}</td>
                  <td className="px-4 py-3 text-right font-semibold text-slate-800">₹{parseFloat(note.amount).toFixed(2)}</td>
                  <td className="px-4 py-3 text-slate-500">
                    {note.is_full_return ? "Full" : "Partial"} • {note.refund_method === "payout" ? "Payout" : "Credit"}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_COLORS[note.status] || "bg-slate-100 text-slate-600"}`}>
                      {note.status.replace("_", " ")}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-slate-500">{note.note_date || note.created_at.slice(0, 10)}</td>
                  <td className="px-4 py-3 text-slate-500 text-xs">
                    {(note.return_items || []).map(it => `${it.product_name} ×${it.quantity}`).join(", ")}
                  </td>
                  {canEdit && (
                    <td className="px-4 py-3">
                      {note.status === "open" && (
                        <div className="flex gap-1">
                          <button onClick={() => applyNote(note)}
                            className={`${BTN_SM} bg-blue-50 text-blue-700 hover:bg-blue-100`}>
                            Apply to bill
                          </button>
                          <button onClick={() => payoutNote(note)}
                            className={`${BTN_SM} bg-emerald-50 text-emerald-700 hover:bg-emerald-100`}>
                            Pay out
                          </button>
                          <button onClick={() => deleteNote(note.id)}
                            className={`${BTN_SM} bg-red-50 text-red-600 hover:bg-red-100`}>
                            ✕
                          </button>
                        </div>
                      )}
                      {note.status === "applied" && (
                        <span className="text-xs text-slate-400">Bill #{note.applied_to_bill_id}</span>
                      )}
                      {note.status === "paid_out" && (
                        <span className="text-xs text-slate-400">{note.paid_out_at?.slice(0, 10)}</span>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
