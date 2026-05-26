"use client";

import { useCallback, useEffect, useState } from "react";
import { Drawer } from "@/components/Drawer";
import { apiUrl, fetchApi, formatApiError } from "@/lib/api";
import type { CatalogProductPublic, CustomerBillPublic, CustomerOrderAdminPublic, CustomerPublic, PurchaseOrderPublic, VendorPublic } from "@/lib/types";

const INPUT = "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500";
const LABEL = "mb-1 block text-xs font-semibold text-slate-500 uppercase tracking-wider";
const BTN_PRIMARY = "inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-700 disabled:opacity-50";
const BTN_SECONDARY = "inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm transition hover:bg-slate-50";

function statusBadge(status: string) {
  const map: Record<string, { label: string; cls: string }> = {
    confirmed:  { label: "Confirmed",  cls: "bg-blue-50 text-blue-700 ring-blue-200" },
    billed:     { label: "Billed",     cls: "bg-amber-50 text-amber-700 ring-amber-200" },
    shipped:    { label: "Shipped",    cls: "bg-emerald-50 text-emerald-700 ring-emerald-200" },
    cancelled:  { label: "Cancelled",  cls: "bg-red-50 text-red-700 ring-red-200" },
  };
  const s = map[status] ?? { label: status, cls: "bg-slate-100 text-slate-600 ring-slate-200" };
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${s.cls}`}>
      {s.label}
    </span>
  );
}

interface Props {
  adminKey: string;
}

export function OrdersScreen({ adminKey }: Props) {
  const [tab, setTab] = useState<"customer" | "purchase">("customer");

  const headers = () => {
    const h: Record<string, string> = { "Content-Type": "application/json" };
    if (adminKey.trim()) h["X-Admin-Key"] = adminKey.trim();
    return h;
  };
  const headersAdmin = (): Record<string, string> => adminKey.trim() ? { "X-Admin-Key": adminKey.trim() } : {};

  return (
    <div>
      <div className="mb-6 flex gap-2">
        {([
          { id: "customer", label: "🛒 Customer orders" },
          { id: "purchase", label: "📦 Purchase orders" },
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

      {tab === "customer" ? (
        <CustomerOrdersTab headers={headers} headersAdmin={headersAdmin} adminKey={adminKey} />
      ) : (
        <PurchaseOrdersTab headers={headers} headersAdmin={headersAdmin} adminKey={adminKey} />
      )}
    </div>
  );
}

// ─────────────────────────────── CUSTOMER ORDERS ───────────────────────────────

function CustomerOrdersTab({
  headers,
  headersAdmin,
  adminKey,
}: {
  headers: () => Record<string, string>;
  headersAdmin: () => Record<string, string>;
  adminKey: string;
}) {
  const [orders, setOrders] = useState<CustomerOrderAdminPublic[]>([]);
  const [catalog, setCatalog] = useState<CatalogProductPublic[]>([]);
  const [loading, setLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string>("confirmed");
  const [search, setSearch] = useState("");
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null);

  // Drawer
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selected, setSelected] = useState<CustomerOrderAdminPublic | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState("");

  // Bill form
  const [showBillForm, setShowBillForm] = useState(false);
  const [freight, setFreight] = useState("");
  const [packaging, setPackaging] = useState("");
  const [discount, setDiscount] = useState("");
  const [gstEnabled, setGstEnabled] = useState(false);
  const [gstRate, setGstRate] = useState("18");
  const [billMsg, setBillMsg] = useState("");
  const [billBusy, setBillBusy] = useState(false);
  const [billData, setBillData] = useState<CustomerBillPublic | null>(null);

  // Bill detail modal
  const [showBillModal, setShowBillModal] = useState(false);

  // Credit summary
  const [creditSummary, setCreditSummary] = useState<{ credit_limit: string | null; outstanding: string; remaining: string | null } | null>(null);

  // Freight vendors
  const [freightVendors, setFreightVendors] = useState<{ id: number; name: string; balance_due: string }[]>([]);
  const [selectedFreightVendorId, setSelectedFreightVendorId] = useState("");

  // Shipment form
  const [showShipForm, setShowShipForm] = useState(false);

  // Edit order state
  const [editStatus, setEditStatus] = useState("confirmed");
  const [editNotes, setEditNotes] = useState("");
  const [shipReceipt, setShipReceipt] = useState("");
  const [shipContact, setShipContact] = useState("");
  const [shipNotes, setShipNotes] = useState("");

  const showToast = (msg: string, ok: boolean) => { setToast({ msg, ok }); setTimeout(() => setToast(null), 3500); };

  const load = useCallback(async () => {
    if (!adminKey.trim()) return;
    setLoading(true);
    const [or, cr, fvr] = await Promise.all([
      fetchApi(apiUrl("customer-orders"), { headers: headersAdmin() }),
      fetchApi(apiUrl("catalog"), { headers: headersAdmin() }),
      fetchApi(apiUrl("freight-vendors"), { headers: headersAdmin() }),
    ]);
    if (or.ok) setOrders(await or.json());
    if (cr.ok) setCatalog(await cr.json());
    if (fvr.ok) setFreightVendors(await fvr.json());
    setLoading(false);
  }, [adminKey]);

  useEffect(() => { void load(); }, [load]);

  async function openOrder(o: CustomerOrderAdminPublic) {
    setSelected(o);
    setEditStatus(o.status);
    setEditNotes(o.notes ?? "");
    setShipReceipt(o.shipment_receipt ?? "");
    setShipContact(o.shipment_contact ?? "");
    setShipNotes(o.shipment_notes ?? "");
    setSelectedFreightVendorId("");
    setBillMsg(""); setSaveMsg(""); setShowBillForm(false); setShowShipForm(false);
    setBillData(null); setShowBillModal(false); setCreditSummary(null);
    setDrawerOpen(true);
    // Fetch existing bill if any
    const billsR = await fetchApi(apiUrl("customer-bills"), { headers: headersAdmin() });
    if (billsR.ok) {
      const bills: CustomerBillPublic[] = await billsR.json();
      const b = bills.find((b) => b.customer_order_id === o.id);
      if (b) setBillData(b);
    }
    // Fetch credit summary
    if (o.customer_id) {
      const cr = await fetchApi(apiUrl(`customers/${o.customer_id}/credit-summary`), { headers: headersAdmin() });
      if (cr.ok) setCreditSummary(await cr.json());
    }
  }

  async function saveOrder(overrideStatus?: string) {
    if (!selected) return;
    setSaving(true); setSaveMsg("");
    const body: Record<string, unknown> = {
      status: overrideStatus ?? editStatus,
      notes: editNotes.trim() || null,
      shipment_receipt: shipReceipt.trim() || null,
      shipment_contact: shipContact.trim() || null,
      shipment_notes: shipNotes.trim() || null,
    };
    const r = await fetchApi(apiUrl(`customer-orders/${selected.id}`), { method: "PATCH", headers: headers(), body: JSON.stringify(body) });
    const data = await r.json().catch(() => ({}));
    setSaving(false);
    if (!r.ok) { setSaveMsg(formatApiError(data)); return; }
    const updated = data as CustomerOrderAdminPublic;
    setSelected(updated);
    setEditStatus(updated.status);
    showToast("Saved.", true);

    // If shipping with a selected freight vendor + freight amount, record ledger entry
    const finalStatus = overrideStatus ?? editStatus;
    if (finalStatus === "shipped" && selectedFreightVendorId && billData) {
      const freightAmt = billData.totals?.freight_charges;
      if (freightAmt && Number(freightAmt) > 0) {
        await fetchApi(apiUrl("freight-vendors/ledger"), {
          method: "POST",
          headers: headers(),
          body: JSON.stringify({
            freight_vendor_id: Number(selectedFreightVendorId),
            entry_date: new Date().toISOString().slice(0, 10),
            entry_type: "charge",
            amount: Number(freightAmt),
            reference: `Order #${selected.id}`,
            notes: shipNotes.trim() || null,
          }),
        });
      }
    }

    void load();
  }

  async function generateBill() {
    if (!selected) return;
    setBillBusy(true); setBillMsg("");
    const body: Record<string, unknown> = {
      customer_order_id: selected.id,
      gst_enabled: gstEnabled,
      gst_rate_percent: gstEnabled ? Number(gstRate) : 0,
    };
    if (freight.trim()) body.freight_charges = Number(freight);
    if (packaging.trim()) body.packaging_charges = Number(packaging);
    if (discount.trim()) body.discount_percent = Number(discount);
    const r = await fetchApi(apiUrl("customer-bills/generate"), { method: "POST", headers: headers(), body: JSON.stringify(body) });
    const data = await r.json().catch(() => ({}));
    setBillBusy(false);
    if (!r.ok) { setBillMsg(formatApiError(data)); return; }
    const bill = data as CustomerBillPublic;
    setBillData(bill);
    setBillMsg(`✓ Bill #${bill.id} generated and sent to customer via WhatsApp.`);
    setShowBillForm(false);
    void load();
    // Refresh the selected order
    const updated = await fetchApi(apiUrl(`customer-orders/${selected.id}`), { headers: headersAdmin() });
    if (updated.ok) setSelected(await updated.json());
  }

  const filtered = orders.filter((o) => {
    const matchStatus = !statusFilter || o.status === statusFilter;
    const q = search.toLowerCase();
    const matchSearch = !q || o.customer_name.toLowerCase().includes(q) || o.customer_phone.includes(q) || String(o.id).includes(q);
    return matchStatus && matchSearch;
  });

  const statusCounts = {
    confirmed: orders.filter((o) => o.status === "confirmed").length,
    billed: orders.filter((o) => o.status === "billed").length,
    shipped: orders.filter((o) => o.status === "shipped").length,
  };

  return (
    <div>
      {toast && (
        <div className={`fixed right-4 top-20 z-50 rounded-lg px-4 py-3 text-sm font-medium shadow-lg ${toast.ok ? "bg-emerald-600 text-white" : "bg-red-600 text-white"}`}>
          {toast.msg}
        </div>
      )}

      {/* Status filter pills */}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        {[
          { id: "", label: "All", count: orders.length },
          { id: "confirmed", label: "Confirmed", count: statusCounts.confirmed },
          { id: "billed", label: "Billed", count: statusCounts.billed },
          { id: "shipped", label: "Shipped", count: statusCounts.shipped },
        ].map((s) => (
          <button
            key={s.id}
            type="button"
            onClick={() => setStatusFilter(s.id)}
            className={`rounded-full px-4 py-1.5 text-sm font-medium transition ${
              statusFilter === s.id
                ? "bg-blue-600 text-white shadow-sm"
                : "bg-white text-slate-600 shadow-sm ring-1 ring-slate-200 hover:bg-slate-50"
            }`}
          >
            {s.label} <span className="ml-1 opacity-70">({s.count})</span>
          </button>
        ))}
        <div className="ml-auto flex items-center gap-2">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search customer…"
            className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none"
          />
          <button type="button" onClick={() => void load()} className={BTN_SECONDARY}>↻</button>
        </div>
      </div>

      {loading ? (
        <div className="py-12 text-center text-slate-400">Loading…</div>
      ) : filtered.length === 0 ? (
        <div className="rounded-xl border-2 border-dashed border-slate-200 py-16 text-center text-slate-400">
          <div className="text-4xl">🛒</div>
          <div className="mt-2 font-medium">No orders</div>
        </div>
      ) : (
        <div className="space-y-2">
          {filtered.map((o) => (
            <div
              key={o.id}
              onClick={() => void openOrder(o)}
              className="cursor-pointer rounded-xl border border-slate-200 bg-white p-4 shadow-sm transition hover:border-blue-300 hover:shadow-md"
            >
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-slate-900">{o.customer_name}</span>
                    <span className="font-mono text-xs text-slate-400">{o.customer_phone}</span>
                    {statusBadge(o.status)}
                  </div>
                  <div className="mt-1 text-sm text-slate-500">
                    {o.items.length} item{o.items.length !== 1 ? "s" : ""}
                    {o.items.slice(0, 3).map((it) => ` · ${it.name}`).join("")}
                    {o.items.length > 3 ? ` +${o.items.length - 3} more` : ""}
                  </div>
                  {o.customer_notes && (
                    <div className="mt-1 rounded-md bg-amber-50 px-2 py-1 text-xs text-amber-700">
                      📝 {o.customer_notes}
                    </div>
                  )}
                </div>
                <div className="text-right shrink-0">
                  <div className="text-lg font-bold text-slate-900">₹{o.total_amount}</div>
                  <div className="text-xs text-slate-400">
                    #{o.id} · {new Date(o.created_at).toLocaleDateString(undefined, { dateStyle: "short" })}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Order detail drawer */}
      <Drawer
        open={drawerOpen && !!selected}
        onClose={() => setDrawerOpen(false)}
        title={selected ? `Order #${selected.id} — ${selected.customer_name}` : "Order"}
        subtitle={selected ? `${selected.customer_phone} · ₹${selected.total_amount}` : ""}
        width="max-w-xl"
        footer={
          <div className="flex flex-wrap items-center gap-3">
            <button type="button" onClick={() => void saveOrder()} disabled={saving} className={BTN_PRIMARY}>
              {saving ? "Saving…" : "Save changes"}
            </button>
            {selected && selected.status === "confirmed" && !showBillForm && (
              <button type="button" onClick={() => setShowBillForm(true)} className="inline-flex items-center gap-1.5 rounded-lg bg-amber-500 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-amber-600">
                🧾 Generate Bill
              </button>
            )}
            {selected && selected.status === "billed" && !showShipForm && (
              <button type="button" onClick={() => setShowShipForm(true)} className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-emerald-700">
                🚚 Mark Shipped
              </button>
            )}
            {saveMsg && <span className="text-sm text-red-600">{saveMsg}</span>}
          </div>
        }
      >
        {selected && (
          <div className="space-y-5">
            {/* Status + notes */}
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className={LABEL}>Status</label>
                <select value={editStatus} onChange={(e) => setEditStatus(e.target.value)} className={INPUT}>
                  <option value="confirmed">Confirmed</option>
                  <option value="billed">Billed</option>
                  <option value="shipped">Shipped</option>
                  <option value="cancelled">Cancelled</option>
                </select>
              </div>
              <div>
                <label className={LABEL}>Current status</label>
                <div className="mt-2">{statusBadge(selected.status)}</div>
              </div>
            </div>

            <div>
              <label className={LABEL}>Admin notes</label>
              <textarea value={editNotes} onChange={(e) => setEditNotes(e.target.value)} rows={2} className={INPUT} placeholder="Internal notes…" />
            </div>

            {/* Customer notes */}
            {selected.customer_notes && (
              <div className="rounded-xl bg-amber-50 p-3">
                <div className="text-xs font-semibold uppercase text-amber-600">Customer note</div>
                <div className="mt-1 text-sm text-amber-800">{selected.customer_notes}</div>
              </div>
            )}

            {/* Manual order fields */}
            {(selected.invoice_date || selected.invoice_no || selected.receipt_note_no) && (
              <div className="rounded-xl bg-slate-50 p-3 space-y-1">
                <div className="text-xs font-semibold uppercase text-slate-500">Walk-in / Manual order details</div>
                {selected.invoice_date && <div className="text-sm text-slate-700"><span className="font-medium">Invoice date:</span> {new Date(selected.invoice_date).toLocaleDateString("en-IN")}</div>}
                {selected.invoice_no && <div className="text-sm text-slate-700"><span className="font-medium">Invoice no:</span> {selected.invoice_no}</div>}
                {selected.receipt_note_no && <div className="text-sm text-slate-700"><span className="font-medium">Receipt note no:</span> {selected.receipt_note_no}</div>}
              </div>
            )}

            {/* Items */}
            <div>
              <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">Items</div>
              <div className="overflow-hidden rounded-xl border border-slate-200">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-200 bg-slate-50 text-xs font-semibold uppercase text-slate-500">
                      <th className="px-3 py-2 text-left">Product</th>
                      <th className="px-3 py-2 text-right">Qty</th>
                      <th className="px-3 py-2 text-right">Price</th>
                      <th className="px-3 py-2 text-right">Total</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {selected.items.map((it) => {
                      const cat = catalog.find((c) => c.id === it.catalog_product_id);
                      return (
                        <tr key={it.catalog_product_id}>
                          <td className="px-3 py-2">
                            <div className="font-medium">{it.name}</div>
                            <div className="text-xs text-slate-400">{it.our_product_id}</div>
                          </td>
                          <td className="px-3 py-2 text-right">{it.quantity}</td>
                          <td className="px-3 py-2 text-right">₹{it.unit_price}</td>
                          <td className="px-3 py-2 text-right font-medium">₹{it.line_total}</td>
                        </tr>
                      );
                    })}
                    <tr className="border-t border-slate-200 bg-slate-50">
                      <td colSpan={3} className="px-3 py-2 text-right font-semibold">Total</td>
                      <td className="px-3 py-2 text-right font-bold text-slate-900">₹{selected.total_amount}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            {/* Bill info if already billed */}
            {billData && (
              <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-xs font-semibold uppercase text-amber-600">Bill #{billData.id}</div>
                    <button
                      type="button"
                      onClick={() => setShowBillModal(true)}
                      className="mt-0.5 text-xl font-bold text-amber-900 underline hover:text-amber-700"
                    >
                      ₹{billData.totals?.grand_total ?? selected?.total_amount}
                    </button>
                    <div className="text-xs text-amber-700">Click to view full breakdown</div>
                  </div>
                  <a
                    href={`${apiUrl(`customer-bills/${billData.id}/download`)}?x_admin_key=${encodeURIComponent(adminKey)}`}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1.5 rounded-lg bg-amber-600 px-3 py-2 text-xs font-semibold text-white shadow-sm hover:bg-amber-700"
                    onClick={(e) => {
                      e.stopPropagation();
                    }}
                  >
                    ⬇ Download PDF
                  </a>
                </div>
              </div>
            )}

            {/* Credit summary */}
            {creditSummary && creditSummary.credit_limit !== null && (
              <div className={`rounded-xl border p-3 ${Number(creditSummary.remaining) < 0 ? "border-red-200 bg-red-50" : "border-emerald-200 bg-emerald-50"}`}>
                <div className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1">Credit position</div>
                <div className="grid grid-cols-3 gap-2 text-sm">
                  <div><div className="text-xs text-slate-400">Limit</div><div className="font-bold">₹{creditSummary.credit_limit}</div></div>
                  <div><div className="text-xs text-slate-400">Outstanding AR</div><div className="font-bold text-amber-700">₹{creditSummary.outstanding}</div></div>
                  <div><div className="text-xs text-slate-400">Remaining</div><div className={`font-bold ${Number(creditSummary.remaining) < 0 ? "text-red-600" : "text-emerald-700"}`}>₹{creditSummary.remaining}</div></div>
                </div>
              </div>
            )}

            {/* Bill form */}
            {showBillForm && (
              <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <div className="text-sm font-semibold text-amber-800">Generate bill</div>
                  <button type="button" onClick={() => setShowBillForm(false)} className="text-slate-400 hover:text-slate-600">✕</button>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className={LABEL}>Freight charges (₹)</label>
                    <input value={freight} onChange={(e) => setFreight(e.target.value)} type="number" min="0" step="0.01" placeholder="0" className={INPUT} />
                  </div>
                  <div>
                    <label className={LABEL}>Packaging charges (₹)</label>
                    <input value={packaging} onChange={(e) => setPackaging(e.target.value)} type="number" min="0" step="0.01" placeholder="0" className={INPUT} />
                  </div>
                  <div>
                    <label className={LABEL}>Discount (%)</label>
                    <input value={discount} onChange={(e) => setDiscount(e.target.value)} type="number" min="0" max="100" step="0.01" placeholder="0" className={INPUT} />
                  </div>
                  <div className="flex items-end gap-2">
                    <label className="flex items-center gap-2 text-sm text-slate-700">
                      <input type="checkbox" checked={gstEnabled} onChange={(e) => setGstEnabled(e.target.checked)} className="h-4 w-4 rounded" />
                      GST
                    </label>
                    {gstEnabled && (
                      <input value={gstRate} onChange={(e) => setGstRate(e.target.value)} type="number" min="0" max="100" className="w-20 rounded-lg border border-slate-300 px-2 py-2 text-sm" />
                    )}
                  </div>
                </div>
                {billMsg && <p className="text-sm font-medium text-emerald-700">{billMsg}</p>}
                <button type="button" onClick={generateBill} disabled={billBusy} className={BTN_PRIMARY}>
                  {billBusy ? "Generating…" : "Generate & send to customer"}
                </button>
              </div>
            )}

            {/* Shipment form */}
            {showShipForm && (
              <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <div className="text-sm font-semibold text-emerald-800">Shipment details</div>
                  <button type="button" onClick={() => setShowShipForm(false)} className="text-slate-400 hover:text-slate-600">✕</button>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className={LABEL}>Receipt / AWB number *</label>
                    <input value={shipReceipt} onChange={(e) => setShipReceipt(e.target.value)} className={INPUT} placeholder="e.g. DTX12345" />
                  </div>
                  <div>
                    <label className={LABEL}>Contact number (optional)</label>
                    <input value={shipContact} onChange={(e) => setShipContact(e.target.value)} className={INPUT} placeholder="Courier contact" />
                  </div>
                  {freightVendors.length > 0 && (
                    <div className="col-span-2">
                      <label className={LABEL}>Freight agent</label>
                      <select value={selectedFreightVendorId} onChange={(e) => setSelectedFreightVendorId(e.target.value)} className={INPUT}>
                        <option value="">— none / not applicable —</option>
                        {freightVendors.map((fv) => (
                          <option key={fv.id} value={fv.id}>{fv.name}{Number(fv.balance_due) > 0 ? ` (balance: ₹${fv.balance_due})` : ""}</option>
                        ))}
                      </select>
                      {selectedFreightVendorId && billData?.totals?.freight_charges && Number(billData.totals.freight_charges) > 0 && (
                        <p className="mt-1 text-xs text-emerald-700">₹{billData.totals.freight_charges} will be added to their ledger on save.</p>
                      )}
                    </div>
                  )}
                  <div className="col-span-2">
                    <label className={LABEL}>Shipment notes</label>
                    <input value={shipNotes} onChange={(e) => setShipNotes(e.target.value)} className={INPUT} placeholder="e.g. via Blue Dart" />
                  </div>
                </div>
                <button
                  type="button"
                  disabled={saving}
                  onClick={() => { void saveOrder("shipped"); setShowShipForm(false); }}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-emerald-700 disabled:opacity-50"
                >
                  {saving ? "Saving…" : "Confirm shipment"}
                </button>
              </div>
            )}

            {/* Shipment info if already shipped */}
            {selected.shipment_receipt && (
              <div className="rounded-xl bg-emerald-50 p-3">
                <div className="text-xs font-semibold uppercase text-emerald-600">Shipment</div>
                <div className="mt-1 grid grid-cols-2 gap-1 text-sm text-emerald-800">
                  <span>Receipt: {selected.shipment_receipt}</span>
                  <span>Contact: {selected.shipment_contact}</span>
                  {selected.shipment_notes && <span className="col-span-2">Notes: {selected.shipment_notes}</span>}
                </div>
              </div>
            )}
          </div>
        )}
      </Drawer>

      {/* Bill detail modal */}
      {showBillModal && billData && selected && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-lg rounded-2xl bg-white shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
              <div>
                <div className="text-base font-bold text-slate-900">Bill #{billData.id} — Order #{billData.customer_order_id}</div>
                <div className="text-sm text-slate-500">{selected.customer_name}</div>
              </div>
              <button type="button" onClick={() => setShowBillModal(false)} className="text-slate-400 hover:text-slate-600 text-xl">✕</button>
            </div>
            <div className="px-6 py-4 space-y-2">
              <div className="overflow-hidden rounded-xl border border-slate-200">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-200 bg-slate-50 text-xs font-semibold uppercase text-slate-500">
                      <th className="px-3 py-2 text-left">Item</th>
                      <th className="px-3 py-2 text-right">Qty</th>
                      <th className="px-3 py-2 text-right">Rate</th>
                      <th className="px-3 py-2 text-right">Total</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {selected.items.map((it) => (
                      <tr key={it.catalog_product_id}>
                        <td className="px-3 py-2"><div className="font-medium">{it.name}</div><div className="text-xs text-slate-400">{it.our_product_id}</div></td>
                        <td className="px-3 py-2 text-right">{it.quantity}</td>
                        <td className="px-3 py-2 text-right">₹{it.unit_price}</td>
                        <td className="px-3 py-2 text-right font-medium">₹{it.line_total}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 space-y-1.5 text-sm">
                {billData.totals?.subtotal !== undefined && <div className="flex justify-between"><span className="text-slate-500">Subtotal</span><span>₹{billData.totals.subtotal}</span></div>}
                {Number(billData.totals?.discount_amount ?? 0) > 0 && <div className="flex justify-between"><span className="text-slate-500">Discount</span><span className="text-red-600">−₹{billData.totals?.discount_amount}</span></div>}
                {Number(billData.totals?.freight_charges ?? 0) > 0 && <div className="flex justify-between"><span className="text-slate-500">Freight</span><span>₹{billData.totals?.freight_charges}</span></div>}
                {Number(billData.totals?.packaging_charges ?? 0) > 0 && <div className="flex justify-between"><span className="text-slate-500">Packaging</span><span>₹{billData.totals?.packaging_charges}</span></div>}
                {Number(billData.totals?.gst_amount ?? 0) > 0 && <div className="flex justify-between"><span className="text-slate-500">GST ({billData.gst_rate_percent ?? 0}%)</span><span>₹{billData.totals?.gst_amount}</span></div>}
                <div className="flex justify-between border-t border-slate-200 pt-1.5 font-bold text-slate-900"><span>Grand total</span><span>₹{billData.totals?.grand_total}</span></div>
              </div>
            </div>
            <div className="flex justify-end gap-3 border-t border-slate-200 px-6 py-4">
              <a href={`${apiUrl(`customer-bills/${billData.id}/download`)}?x_admin_key=${encodeURIComponent(adminKey)}`} target="_blank" rel="noreferrer" className={BTN_PRIMARY}>⬇ Download PDF</a>
              <button type="button" onClick={() => setShowBillModal(false)} className={BTN_SECONDARY}>Close</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────── PURCHASE ORDERS ───────────────────────────────

function PurchaseOrdersTab({
  headers,
  headersAdmin,
  adminKey,
}: {
  headers: () => Record<string, string>;
  headersAdmin: () => Record<string, string>;
  adminKey: string;
}) {
  const [orders, setOrders] = useState<PurchaseOrderPublic[]>([]);
  const [vendors, setVendors] = useState<VendorPublic[]>([]);
  const [catalog, setCatalog] = useState<CatalogProductPublic[]>([]);
  const [loading, setLoading] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selected, setSelected] = useState<PurchaseOrderPublic | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null);
  const [saving, setSaving] = useState(false);
  // Create form state
  const [selectedVendorId, setSelectedVendorId] = useState("");
  const [lines, setLines] = useState<{ catalog_product_id: string; quantity: string; search: string }[]>([{ catalog_product_id: "", quantity: "1", search: "" }]);

  const showToast = (msg: string, ok: boolean) => { setToast({ msg, ok }); setTimeout(() => setToast(null), 3500); };

  const load = useCallback(async () => {
    if (!adminKey.trim()) return;
    setLoading(true);
    const [pr, vr, cr] = await Promise.all([
      fetchApi(apiUrl("purchase-orders"), { headers: headersAdmin() }),
      fetchApi(apiUrl("vendors"), { headers: headersAdmin() }),
      fetchApi(apiUrl("catalog"), { headers: headersAdmin() }),
    ]);
    if (pr.ok) setOrders(await pr.json());
    if (vr.ok) setVendors(await vr.json());
    if (cr.ok) setCatalog(await cr.json());
    setLoading(false);
  }, [adminKey]);

  useEffect(() => { void load(); }, [load]);

  const vendorName = (id: number) => {
    const v = vendors.find((v) => v.id === id);
    return v?.company_name || v?.person_name || `#${id}`;
  };

  async function createOrder(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setSaving(true);
    const fd = new FormData(e.currentTarget);
    const validLines = lines.filter((l) => l.catalog_product_id && Number(l.quantity) >= 1).map((l) => ({ catalog_product_id: Number(l.catalog_product_id), quantity: Math.floor(Number(l.quantity)) }));
    const body = { vendor_id: Number(fd.get("vendor_id")), notes: fd.get("notes") || null, items: validLines };
    const r = await fetchApi(apiUrl("purchase-orders"), { method: "POST", headers: headers(), body: JSON.stringify(body) });
    const data = await r.json().catch(() => ({}));
    setSaving(false);
    if (!r.ok) { showToast(formatApiError(data), false); return; }
    showToast("Order created.", true);
    setShowCreate(false);
    setSelectedVendorId("");
    setLines([{ catalog_product_id: "", quantity: "1", search: "" }]);
    void load();
  }

  const poBadge = (status: string) => {
    const map: Record<string, string> = {
      booked:      "bg-blue-50 text-blue-700 ring-blue-200",
      in_progress: "bg-amber-50 text-amber-700 ring-amber-200",
      closed:      "bg-emerald-50 text-emerald-700 ring-emerald-200",
      disputed:    "bg-orange-50 text-orange-700 ring-orange-200",
      cancelled:   "bg-red-50 text-red-700 ring-red-200",
    };
    return <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${map[status] ?? "bg-slate-100 text-slate-600 ring-slate-200"}`}>{status}</span>;
  };

  return (
    <div>
      {toast && (
        <div className={`fixed right-4 top-20 z-50 rounded-lg px-4 py-3 text-sm font-medium shadow-lg ${toast.ok ? "bg-emerald-600 text-white" : "bg-red-600 text-white"}`}>
          {toast.msg}
        </div>
      )}

      <div className="mb-4 flex items-center gap-3">
        <button type="button" onClick={() => void load()} className={BTN_SECONDARY}>↻ Refresh</button>
        <button type="button" onClick={() => setShowCreate((v) => !v)} className={BTN_PRIMARY}>
          {showCreate ? "Cancel" : "+ New purchase order"}
        </button>
      </div>

      {showCreate && (
        <form onSubmit={createOrder} className="mb-6 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="mb-4 grid grid-cols-2 gap-4">
            <div>
              <label className={LABEL}>Vendor *</label>
              <select
                name="vendor_id"
                required
                value={selectedVendorId}
                onChange={(e) => {
                  setSelectedVendorId(e.target.value);
                  // Clear lines when vendor changes
                  setLines([{ catalog_product_id: "", quantity: "1", search: "" }]);
                }}
                className={INPUT}
              >
                <option value="">— select vendor —</option>
                {vendors.map((v) => <option key={v.id} value={v.id}>{v.company_name || v.person_name}</option>)}
              </select>
            </div>
            <div>
              <label className={LABEL}>Notes</label>
              <input name="notes" className={INPUT} />
            </div>
          </div>

          {selectedVendorId && (() => {
            const vendorProducts = catalog.filter((p) => String(p.vendor_id) === selectedVendorId);
            return (
              <>
                <div className="mb-3 flex items-center justify-between">
                  <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">Items</span>
                  <span className="text-xs text-slate-400">{vendorProducts.length} product{vendorProducts.length !== 1 ? "s" : ""} from this vendor</span>
                </div>
                {lines.map((line, i) => {
                  const suggestions = line.search.trim()
                    ? vendorProducts.filter((p) =>
                        p.our_product_id.toLowerCase().includes(line.search.toLowerCase()) ||
                        p.category.toLowerCase().includes(line.search.toLowerCase()) ||
                        p.vendor_product_id.toLowerCase().includes(line.search.toLowerCase())
                      )
                    : vendorProducts;
                  const selected = vendorProducts.find((p) => String(p.id) === line.catalog_product_id);
                  return (
                    <div key={i} className="mb-3">
                      <div className="flex items-start gap-2">
                        <div className="flex-1 relative">
                          {selected ? (
                            // Selected — show chip with clear
                            <div className="flex items-center gap-2 rounded-lg border border-blue-300 bg-blue-50 px-3 py-2 text-sm">
                              <span className="font-mono text-blue-700">{selected.our_product_id}</span>
                              <span className="text-slate-600">— {selected.category}</span>
                              <span className="ml-auto text-xs text-slate-400">{selected.unit || "pcs"} · ₹{selected.selling_price}</span>
                              <button
                                type="button"
                                onClick={() => setLines((prev) => prev.map((l, j) => j === i ? { ...l, catalog_product_id: "", search: "" } : l))}
                                className="ml-1 text-slate-400 hover:text-red-500"
                              >✕</button>
                            </div>
                          ) : (
                            // Search input
                            <div>
                              <input
                                type="text"
                                value={line.search}
                                onChange={(e) => setLines((prev) => prev.map((l, j) => j === i ? { ...l, search: e.target.value } : l))}
                                placeholder="Type to search products…"
                                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                                autoComplete="off"
                              />
                              {/* Dropdown suggestions */}
                              {suggestions.length > 0 && (
                                <div className="absolute z-20 mt-1 max-h-52 w-full overflow-y-auto rounded-lg border border-slate-200 bg-white shadow-lg">
                                  {suggestions.slice(0, 20).map((p) => (
                                    <button
                                      key={p.id}
                                      type="button"
                                      onClick={() => setLines((prev) => prev.map((l, j) => j === i ? { ...l, catalog_product_id: String(p.id), search: "" } : l))}
                                      className="flex w-full items-center gap-3 px-3 py-2.5 text-left text-sm hover:bg-blue-50"
                                    >
                                      <span className="font-mono text-xs text-slate-400 w-20 shrink-0">{p.our_product_id}</span>
                                      <span className="flex-1 font-medium text-slate-800">{p.category}</span>
                                      <span className="text-xs text-slate-400">{p.unit || "pcs"}</span>
                                      <span className="text-sm font-semibold text-slate-700">₹{p.selling_price}</span>
                                    </button>
                                  ))}
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                        <input
                          type="number" min="1"
                          value={line.quantity}
                          onChange={(e) => setLines((prev) => prev.map((l, j) => j === i ? { ...l, quantity: e.target.value } : l))}
                          className="w-20 rounded-lg border border-slate-300 px-3 py-2 text-sm"
                          placeholder="Qty"
                        />
                        {lines.length > 1 && (
                          <button type="button" onClick={() => setLines((prev) => prev.filter((_, j) => j !== i))} className="mt-2 text-slate-400 hover:text-red-500">✕</button>
                        )}
                      </div>
                    </div>
                  );
                })}
                <button
                  type="button"
                  onClick={() => setLines((p) => [...p, { catalog_product_id: "", quantity: "1", search: "" }])}
                  className="mb-4 text-sm text-blue-600 hover:underline"
                >
                  + Add item
                </button>
              </>
            );
          })()}

          {!selectedVendorId && (
            <div className="mb-4 rounded-lg bg-slate-50 px-4 py-3 text-sm text-slate-500">
              Select a vendor first to see their products.
            </div>
          )}

          <div className="flex gap-3">
            <button type="submit" disabled={saving} className={BTN_PRIMARY}>{saving ? "Creating…" : "Create order"}</button>
            <button type="button" onClick={() => { setShowCreate(false); setSelectedVendorId(""); setLines([{ catalog_product_id: "", quantity: "1", search: "" }]); }} className={BTN_SECONDARY}>Cancel</button>
          </div>
        </form>
      )}

      {loading ? (
        <div className="py-12 text-center text-slate-400">Loading…</div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-xs font-semibold uppercase text-slate-500">
                <th className="px-4 py-3 text-left">#</th>
                <th className="px-4 py-3 text-left">Vendor</th>
                <th className="px-4 py-3 text-left">Status</th>
                <th className="px-4 py-3 text-right">Value</th>
                <th className="px-4 py-3 text-left">Date</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {orders.map((o) => (
                <tr
                  key={o.id}
                  className="cursor-pointer transition hover:bg-blue-50/40"
                  onClick={() => { setSelected(o); setDrawerOpen(true); }}
                >
                  <td className="px-4 py-3 font-mono text-slate-400">#{o.id}</td>
                  <td className="px-4 py-3 font-medium">{vendorName(o.vendor_id)}</td>
                  <td className="px-4 py-3">{poBadge(o.status)}</td>
                  <td className="px-4 py-3 text-right font-medium">₹{o.total_buying_value?.toFixed(2) ?? "—"}</td>
                  <td className="px-4 py-3 text-slate-400 text-xs">{new Date(o.created_at).toLocaleDateString()}</td>
                </tr>
              ))}
              {orders.length === 0 && (
                <tr><td colSpan={5} className="px-4 py-8 text-center text-slate-400">No purchase orders yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      <Drawer
        open={drawerOpen && !!selected}
        onClose={() => setDrawerOpen(false)}
        title={selected ? `PO #${selected.id} — ${vendorName(selected.vendor_id)}` : "Purchase Order"}
        subtitle={selected ? `Status: ${selected.status} · Created ${new Date(selected.created_at).toLocaleDateString()}` : ""}
        width="max-w-xl"
      >
        {selected && (
          <div className="space-y-4">
            <div className="overflow-hidden rounded-xl border border-slate-200">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-200 bg-slate-50 text-xs font-semibold uppercase text-slate-500">
                    <th className="px-3 py-2 text-left">Product</th>
                    <th className="px-3 py-2 text-right">Ordered</th>
                    <th className="px-3 py-2 text-right">Received</th>
                    <th className="px-3 py-2 text-right">Value</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {selected.items.map((it) => (
                    <tr key={it.catalog_product_id}>
                      <td className="px-3 py-2">
                        <div className="font-medium">{it.name}</div>
                        <div className="text-xs text-slate-400">{it.our_product_id}</div>
                      </td>
                      <td className="px-3 py-2 text-right">{it.quantity}</td>
                      <td className="px-3 py-2 text-right text-emerald-600">{it.received_quantity ?? 0}</td>
                      <td className="px-3 py-2 text-right font-medium">₹{it.line_total_buying?.toFixed(2)}</td>
                    </tr>
                  ))}
                  <tr className="bg-slate-50 border-t">
                    <td colSpan={3} className="px-3 py-2 text-right font-semibold">Total</td>
                    <td className="px-3 py-2 text-right font-bold">₹{selected.total_buying_value?.toFixed(2)}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            {selected.notes && (
              <div className="rounded-lg bg-slate-50 p-3 text-sm text-slate-600">
                <strong>Notes:</strong> {selected.notes}
              </div>
            )}
          </div>
        )}
      </Drawer>
    </div>
  );
}
