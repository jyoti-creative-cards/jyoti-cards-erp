"use client";

import { useCallback, useEffect, useState } from "react";
import { apiUrl, fetchApi, formatApiError } from "@/lib/api";
import type { CatalogProductPublic, CityPublic, CustomerPublic, VendorPublic } from "@/lib/types";

const INPUT = "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500";
const LABEL = "mb-1 block text-xs font-semibold text-slate-500 uppercase tracking-wider";
const BTN_PRIMARY = "inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-700 disabled:opacity-50";
const BTN_SECONDARY = "inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm transition hover:bg-slate-50";

function emptyToNull(v: FormDataEntryValue | null) {
  const s = String(v ?? "").trim(); return s === "" ? null : s;
}

type CreateType = "customer_order" | "customer" | "vendor" | "purchase_order" | "expense";

const CREATE_OPTIONS: { id: CreateType; label: string; icon: string; desc: string }[] = [
  { id: "customer_order", icon: "🛒", label: "Customer order", desc: "Offline / walk-in order" },
  { id: "customer",       icon: "👤", label: "Customer",       desc: "New customer account" },
  { id: "vendor",         icon: "🏭", label: "Vendor",         desc: "New supplier / vendor" },
  { id: "purchase_order", icon: "📦", label: "Purchase order", desc: "Order from vendor" },
  { id: "expense",        icon: "🧾", label: "Expense",        desc: "Record an expense" },
];

interface Props { adminKey: string; }

export function CreateScreen({ adminKey }: Props) {
  const [selected, setSelected] = useState<CreateType>("customer_order");
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null);
  const [saving, setSaving] = useState(false);

  const headers = () => {
    const h: Record<string, string> = { "Content-Type": "application/json" };
    if (adminKey.trim()) h["X-Admin-Key"] = adminKey.trim();
    return h;
  };
  const headersAdmin = (): Record<string, string> => adminKey.trim() ? { "X-Admin-Key": adminKey.trim() } : {};

  const showToast = (msg: string, ok: boolean) => { setToast({ msg, ok }); setTimeout(() => setToast(null), 4000); };

  // Shared data
  const [customers, setCustomers] = useState<CustomerPublic[]>([]);
  const [vendors, setVendors] = useState<VendorPublic[]>([]);
  const [catalog, setCatalog] = useState<CatalogProductPublic[]>([]);
  const [cities, setCities] = useState<CityPublic[]>([]);

  const loadData = useCallback(async () => {
    if (!adminKey.trim()) return;
    const [cr, vr, pr, cir] = await Promise.all([
      fetchApi(apiUrl("customers"), { headers: headersAdmin() }),
      fetchApi(apiUrl("vendors"), { headers: headersAdmin() }),
      fetchApi(apiUrl("catalog"), { headers: headersAdmin() }),
      fetchApi(apiUrl("cities"), { headers: headersAdmin() }),
    ]);
    if (cr.ok) setCustomers(await cr.json());
    if (vr.ok) setVendors(await vr.json());
    if (pr.ok) setCatalog(await pr.json());
    if (cir.ok) setCities(await cir.json());
  }, [adminKey]);

  useEffect(() => { void loadData(); }, [loadData]);

  return (
    <div>
      {toast && (
        <div className={`fixed right-4 top-20 z-50 rounded-lg px-4 py-3 text-sm font-medium shadow-lg ${toast.ok ? "bg-emerald-600 text-white" : "bg-red-600 text-white"}`}>
          {toast.msg}
        </div>
      )}

      {/* What to create */}
      <div className="mb-6 flex flex-wrap gap-2">
        {CREATE_OPTIONS.map((opt) => (
          <button
            key={opt.id}
            type="button"
            onClick={() => setSelected(opt.id)}
            className={`flex items-center gap-2 rounded-xl border px-4 py-3 text-left text-sm transition ${
              selected === opt.id
                ? "border-blue-400 bg-blue-600 text-white shadow"
                : "border-slate-200 bg-white text-slate-700 shadow-sm hover:border-blue-200 hover:bg-blue-50"
            }`}
          >
            <span className="text-xl">{opt.icon}</span>
            <div>
              <div className="font-semibold leading-none">{opt.label}</div>
              <div className={`mt-0.5 text-[10px] ${selected === opt.id ? "text-blue-100" : "text-slate-400"}`}>{opt.desc}</div>
            </div>
          </button>
        ))}
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        {selected === "customer_order" && (
          <CustomerOrderForm
            customers={customers}
            catalog={catalog}
            headers={headers}
            headersAdmin={headersAdmin}
            adminKey={adminKey}
            saving={saving}
            setSaving={setSaving}
            showToast={showToast}
          />
        )}
        {selected === "customer" && (
          <CustomerForm
            headers={headers}
            saving={saving}
            setSaving={setSaving}
            showToast={showToast}
            cities={cities}
          />
        )}
        {selected === "vendor" && (
          <VendorForm
            headers={headers}
            saving={saving}
            setSaving={setSaving}
            showToast={showToast}
          />
        )}
        {selected === "purchase_order" && (
          <PurchaseOrderForm
            vendors={vendors}
            catalog={catalog}
            headers={headers}
            saving={saving}
            setSaving={setSaving}
            showToast={showToast}
          />
        )}
        {selected === "expense" && (
          <ExpenseForm
            headers={headers}
            saving={saving}
            setSaving={setSaving}
            showToast={showToast}
          />
        )}
      </div>
    </div>
  );
}

// ──────────────────── CUSTOMER ORDER (offline / walk-in) ────────────────────

function CustomerOrderForm({
  customers, catalog, headers, headersAdmin, adminKey, saving, setSaving, showToast,
}: {
  customers: CustomerPublic[];
  catalog: CatalogProductPublic[];
  headers: () => Record<string, string>;
  headersAdmin: () => Record<string, string>;
  adminKey: string;
  saving: boolean;
  setSaving: (b: boolean) => void;
  showToast: (msg: string, ok: boolean) => void;
}) {
  const [custSearch, setCustSearch] = useState("");
  const [selectedCust, setSelectedCust] = useState<CustomerPublic | null>(null);
  const [lines, setLines] = useState<{ catalog_product_id: string; quantity: string; search: string }[]>([{ catalog_product_id: "", quantity: "1", search: "" }]);
  const [notes, setNotes] = useState("");
  const [invoiceDate, setInvoiceDate] = useState("");
  const [invoiceNo, setInvoiceNo] = useState("");
  const [receiptNoteNo, setReceiptNoteNo] = useState("");
  const [formKey, setFormKey] = useState(0);

  const custSuggestions = custSearch.trim()
    ? customers.filter((c) => c.name.toLowerCase().includes(custSearch.toLowerCase()) || c.phone.includes(custSearch) || (c.alias ?? "").toLowerCase().includes(custSearch.toLowerCase())).slice(0, 8)
    : [];

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!selectedCust) { showToast("Select a customer.", false); return; }
    const validLines = lines.filter((l) => l.catalog_product_id && Number(l.quantity) >= 1)
      .map((l) => ({ catalog_product_id: Number(l.catalog_product_id), quantity: Math.floor(Number(l.quantity)) }));
    if (!validLines.length) { showToast("Add at least one item.", false); return; }
    setSaving(true);
    const body = {
      customer_id: selectedCust.id,
      items: validLines,
      notes: notes.trim() || null,
      invoice_date: invoiceDate ? new Date(invoiceDate).toISOString() : null,
      invoice_no: invoiceNo.trim() || null,
      receipt_note_no: receiptNoteNo.trim() || null,
    };
    const r = await fetchApi(apiUrl("customer-orders"), { method: "POST", headers: headers(), body: JSON.stringify(body) });
    const data = await r.json().catch(() => ({}));
    setSaving(false);
    if (!r.ok) { showToast(formatApiError(data), false); return; }
    showToast(`Order #${(data as { id: number }).id} created for ${selectedCust.name}.`, true);
    setSelectedCust(null); setCustSearch(""); setNotes("");
    setInvoiceDate(""); setInvoiceNo(""); setReceiptNoteNo("");
    setLines([{ catalog_product_id: "", quantity: "1", search: "" }]);
    setFormKey((k) => k + 1);
  }

  const selectedProducts = lines.map((l) => catalog.find((p) => String(p.id) === l.catalog_product_id));
  const total = lines.reduce((s, l, i) => {
    const p = selectedProducts[i];
    return s + (p ? Number(p.selling_price) * Number(l.quantity || 0) : 0);
  }, 0);

  return (
    <div key={formKey}>
      <h3 className="mb-4 text-base font-semibold text-slate-800">🛒 New customer order</h3>
      <form onSubmit={onSubmit} className="space-y-5">
        {/* Customer */}
        <div>
          <label className={LABEL}>Customer *</label>
          {selectedCust ? (
            <div className="flex items-center gap-3 rounded-xl border border-blue-300 bg-blue-50 px-4 py-3">
              <div>
                <div className="font-semibold text-slate-800">{selectedCust.name}</div>
                <div className="text-xs text-slate-500">{selectedCust.phone} {selectedCust.company_name ? `· ${selectedCust.company_name}` : ""}</div>
              </div>
              <button type="button" onClick={() => { setSelectedCust(null); setCustSearch(""); }} className="ml-auto text-slate-400 hover:text-red-500">✕ Change</button>
            </div>
          ) : (
            <div className="relative">
              <input
                value={custSearch}
                onChange={(e) => setCustSearch(e.target.value)}
                placeholder="Search by name, phone or alias…"
                className={INPUT}
                autoComplete="off"
              />
              {custSuggestions.length > 0 && (
                <div className="absolute z-20 mt-1 w-full rounded-xl border border-slate-200 bg-white shadow-lg">
                  {custSuggestions.map((c) => (
                    <button key={c.id} type="button" onClick={() => { setSelectedCust(c); setCustSearch(""); }}
                      className="flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-blue-50">
                      <div className="font-medium text-slate-800">{c.name}</div>
                      <div className="ml-2 text-xs text-slate-400">{c.phone}</div>
                      {c.company_name && <div className="ml-auto text-xs text-slate-400">{c.company_name}</div>}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Items */}
        <div>
          <label className={LABEL}>Items *</label>
          <div className="space-y-2">
            {lines.map((line, i) => {
              const selProduct = catalog.find((p) => String(p.id) === line.catalog_product_id);
              const suggestions = line.search.trim()
                ? catalog.filter((p) =>
                    p.our_product_id.toLowerCase().includes(line.search.toLowerCase()) ||
                    p.category.toLowerCase().includes(line.search.toLowerCase())
                  ).slice(0, 8)
                : [];

              return (
                <div key={i} className="flex items-start gap-2">
                  <div className="flex-1 relative">
                    {selProduct ? (
                      <div className="flex items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm">
                        <span className="font-mono text-xs text-blue-600">{selProduct.our_product_id}</span>
                        <span className="font-medium text-slate-700">{selProduct.category}</span>
                        <span className="ml-auto text-xs text-slate-500">₹{selProduct.selling_price}</span>
                        <button type="button" onClick={() => setLines((p) => p.map((l, j) => j === i ? { ...l, catalog_product_id: "", search: "" } : l))}
                          className="text-slate-300 hover:text-red-500">✕</button>
                      </div>
                    ) : (
                      <div>
                        <input
                          value={line.search}
                          onChange={(e) => setLines((p) => p.map((l, j) => j === i ? { ...l, search: e.target.value } : l))}
                          placeholder="Type to search products…"
                          className={INPUT}
                          autoComplete="off"
                        />
                        {suggestions.length > 0 && (
                          <div className="absolute z-20 mt-1 w-full rounded-xl border border-slate-200 bg-white shadow-lg">
                            {suggestions.map((p) => (
                              <button key={p.id} type="button"
                                onClick={() => setLines((prev) => prev.map((l, j) => j === i ? { ...l, catalog_product_id: String(p.id), search: "" } : l))}
                                className="flex w-full items-center gap-3 px-3 py-2.5 hover:bg-blue-50 text-left text-sm">
                                <span className="font-mono text-xs text-slate-400 w-16 shrink-0">{p.our_product_id}</span>
                                <span className="flex-1 font-medium">{p.category}</span>
                                <span className="text-xs text-slate-400">{p.unit || "pcs"}</span>
                                <span className="font-semibold">₹{p.selling_price}</span>
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                  <input type="number" min="1" value={line.quantity}
                    onChange={(e) => setLines((p) => p.map((l, j) => j === i ? { ...l, quantity: e.target.value } : l))}
                    className="w-20 rounded-lg border border-slate-300 px-3 py-2 text-sm text-center"
                    placeholder="Qty" />
                  {selProduct && (
                    <div className="w-20 rounded-lg bg-slate-100 px-2 py-2 text-right text-xs font-semibold text-slate-700">
                      ₹{(Number(selProduct.selling_price) * Number(line.quantity || 0)).toFixed(0)}
                    </div>
                  )}
                  {lines.length > 1 && (
                    <button type="button" onClick={() => setLines((p) => p.filter((_, j) => j !== i))}
                      className="mt-2 text-slate-300 hover:text-red-500">✕</button>
                  )}
                </div>
              );
            })}
          </div>
          <button type="button" onClick={() => setLines((p) => [...p, { catalog_product_id: "", quantity: "1", search: "" }])}
            className="mt-2 text-sm text-blue-600 hover:underline">+ Add item</button>
        </div>

        {/* Notes */}
        <div>
          <label className={LABEL}>Notes (visible on bill)</label>
          <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} className={INPUT} placeholder="e.g. Urgent, COD, specific packing instructions…" />
        </div>

        {/* Walk-in / manual order fields */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div>
            <label className={LABEL}>Invoice date (if different from today)</label>
            <input type="date" value={invoiceDate} onChange={(e) => setInvoiceDate(e.target.value)} className={INPUT} />
          </div>
          <div>
            <label className={LABEL}>Invoice no. (our bill ID)</label>
            <input type="text" value={invoiceNo} onChange={(e) => setInvoiceNo(e.target.value)} className={INPUT} placeholder="e.g. JC-2025-001" />
          </div>
          <div>
            <label className={LABEL}>Receipt note no. (vendor ID)</label>
            <input type="text" value={receiptNoteNo} onChange={(e) => setReceiptNoteNo(e.target.value)} className={INPUT} placeholder="e.g. VND-456" />
          </div>
        </div>

        {/* Total + submit */}
        <div className="flex items-center justify-between rounded-xl bg-slate-50 px-4 py-3">
          <div className="text-sm text-slate-500">
            {lines.filter((l) => l.catalog_product_id).length} item{lines.filter((l) => l.catalog_product_id).length !== 1 ? "s" : ""}
          </div>
          <div className="flex items-center gap-4">
            {total > 0 && <span className="text-lg font-bold text-slate-900">₹{total.toFixed(2)}</span>}
            <button type="submit" disabled={saving} className={BTN_PRIMARY}>
              {saving ? "Creating…" : "Create order"}
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}

// ──────────────────── CUSTOMER ────────────────────

function CustomerForm({ headers, saving, setSaving, showToast, cities }: {
  headers: () => Record<string, string>;
  saving: boolean;
  setSaving: (b: boolean) => void;
  showToast: (msg: string, ok: boolean) => void;
  cities: CityPublic[];
}) {
  const [key, setKey] = useState(0);
  const [cityId, setCityId] = useState("");
  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    const body = {
      name: fd.get("name"),
      phone: fd.get("phone"),
      company_name: emptyToNull(fd.get("company_name")),
      alias: emptyToNull(fd.get("alias")),
      address: emptyToNull(fd.get("address")),
      credit_limit: emptyToNull(fd.get("credit_limit")),
      city_id: cityId ? Number(cityId) : null,
    };
    setSaving(true);
    const r = await fetchApi(apiUrl("customers"), { method: "POST", headers: headers(), body: JSON.stringify(body) });
    const data = await r.json().catch(() => ({}));
    setSaving(false);
    if (!r.ok) { showToast(formatApiError(data), false); return; }
    showToast(`Customer "${(data as { name: string }).name}" created.`, true);
    setCityId("");
    setKey((k) => k + 1);
  }
  return (
    <div key={key}>
      <h3 className="mb-4 text-base font-semibold text-slate-800">👤 New customer</h3>
      <form onSubmit={onSubmit} className="grid grid-cols-2 gap-4 max-w-lg">
        <div className="col-span-2"><label className={LABEL}>Full name *</label><input name="name" required className={INPUT} /></div>
        <div><label className={LABEL}>Phone *</label><input name="phone" required className={INPUT} /></div>
        <div><label className={LABEL}>Alias</label><input name="alias" placeholder="Short name for search" className={INPUT} /></div>
        <div className="col-span-2"><label className={LABEL}>Company</label><input name="company_name" className={INPUT} /></div>
        <div className="col-span-2"><label className={LABEL}>Address</label><input name="address" className={INPUT} /></div>
        <div>
          <label className={LABEL}>City</label>
          <select value={cityId} onChange={(e) => setCityId(e.target.value)} className={INPUT}>
            <option value="">— select city —</option>
            {cities.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>
        <div><label className={LABEL}>Credit limit ₹</label><input name="credit_limit" type="number" min="0" placeholder="No limit" className={INPUT} /></div>
        <div className="col-span-2"><button type="submit" disabled={saving} className={BTN_PRIMARY}>{saving ? "Saving…" : "Create customer"}</button></div>
      </form>
    </div>
  );
}

// ──────────────────── VENDOR ────────────────────

function VendorForm({ headers, saving, setSaving, showToast }: {
  headers: () => Record<string, string>;
  saving: boolean;
  setSaving: (b: boolean) => void;
  showToast: (msg: string, ok: boolean) => void;
}) {
  const [key, setKey] = useState(0);
  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    const body = { person_name: fd.get("person_name"), phone: fd.get("phone"), company_name: emptyToNull(fd.get("company_name")), alias: emptyToNull(fd.get("alias")), address: emptyToNull(fd.get("address")), billing_percentage: emptyToNull(fd.get("billing_percentage")) ? Number(fd.get("billing_percentage")) : null, city: emptyToNull(fd.get("city")) };
    setSaving(true);
    const r = await fetchApi(apiUrl("vendors"), { method: "POST", headers: headers(), body: JSON.stringify(body) });
    const data = await r.json().catch(() => ({}));
    setSaving(false);
    if (!r.ok) { showToast(formatApiError(data), false); return; }
    showToast("Vendor created.", true);
    setKey((k) => k + 1);
  }
  return (
    <div key={key}>
      <h3 className="mb-4 text-base font-semibold text-slate-800">🏭 New vendor</h3>
      <form onSubmit={onSubmit} className="grid grid-cols-2 gap-4 max-w-lg">
        <div className="col-span-2"><label className={LABEL}>Person name *</label><input name="person_name" required className={INPUT} /></div>
        <div><label className={LABEL}>Phone *</label><input name="phone" required className={INPUT} /></div>
        <div><label className={LABEL}>Alias</label><input name="alias" className={INPUT} /></div>
        <div className="col-span-2"><label className={LABEL}>Company</label><input name="company_name" className={INPUT} /></div>
        <div><label className={LABEL}>City</label><input name="city" className={INPUT} /></div>
        <div><label className={LABEL}>Billing %</label><input name="billing_percentage" type="number" min="0" max="100" placeholder="e.g. 2" className={INPUT} /></div>
        <div className="col-span-2"><label className={LABEL}>Address</label><textarea name="address" rows={2} className={INPUT} /></div>
        <div className="col-span-2"><button type="submit" disabled={saving} className={BTN_PRIMARY}>{saving ? "Saving…" : "Create vendor"}</button></div>
      </form>
    </div>
  );
}

// ──────────────────── PURCHASE ORDER ────────────────────

function PurchaseOrderForm({ vendors, catalog, headers, saving, setSaving, showToast }: {
  vendors: VendorPublic[];
  catalog: CatalogProductPublic[];
  headers: () => Record<string, string>;
  saving: boolean;
  setSaving: (b: boolean) => void;
  showToast: (msg: string, ok: boolean) => void;
}) {
  const [vendorId, setVendorId] = useState("");
  const [lines, setLines] = useState<{ catalog_product_id: string; quantity: string; search: string }[]>([{ catalog_product_id: "", quantity: "1", search: "" }]);
  const [key, setKey] = useState(0);

  const vendorProducts = catalog.filter((p) => String(p.vendor_id) === vendorId);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!vendorId) { showToast("Select a vendor.", false); return; }
    const validLines = lines.filter((l) => l.catalog_product_id && Number(l.quantity) >= 1)
      .map((l) => ({ catalog_product_id: Number(l.catalog_product_id), quantity: Math.floor(Number(l.quantity)) }));
    if (!validLines.length) { showToast("Add at least one item.", false); return; }
    setSaving(true);
    const fd = new FormData(e.currentTarget);
    const body = { vendor_id: Number(vendorId), notes: fd.get("notes") || null, items: validLines };
    const r = await fetchApi(apiUrl("purchase-orders"), { method: "POST", headers: headers(), body: JSON.stringify(body) });
    const data = await r.json().catch(() => ({}));
    setSaving(false);
    if (!r.ok) { showToast(formatApiError(data), false); return; }
    showToast(`PO #${(data as { id: number }).id} created.`, true);
    setVendorId(""); setLines([{ catalog_product_id: "", quantity: "1", search: "" }]); setKey((k) => k + 1);
  }

  return (
    <div key={key}>
      <h3 className="mb-4 text-base font-semibold text-slate-800">📦 New purchase order</h3>
      <form onSubmit={onSubmit} className="space-y-4 max-w-2xl">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className={LABEL}>Vendor *</label>
            <select value={vendorId} onChange={(e) => { setVendorId(e.target.value); setLines([{ catalog_product_id: "", quantity: "1", search: "" }]); }} className={INPUT}>
              <option value="">— select vendor —</option>
              {vendors.map((v) => <option key={v.id} value={v.id}>{v.company_name || v.person_name}</option>)}
            </select>
          </div>
          <div><label className={LABEL}>Notes</label><input name="notes" className={INPUT} /></div>
        </div>

        {vendorId && (
          <div>
            <label className={LABEL}>Items * <span className="text-slate-400 normal-case font-normal">({vendorProducts.length} products from this vendor)</span></label>
            <div className="space-y-2">
              {lines.map((line, i) => {
                const sel = vendorProducts.find((p) => String(p.id) === line.catalog_product_id);
                const suggestions = line.search.trim()
                  ? vendorProducts.filter((p) => p.our_product_id.toLowerCase().includes(line.search.toLowerCase()) || p.category.toLowerCase().includes(line.search.toLowerCase())).slice(0, 8)
                  : vendorProducts.slice(0, 8);
                return (
                  <div key={i} className="flex items-start gap-2">
                    <div className="flex-1 relative">
                      {sel ? (
                        <div className="flex items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm">
                          <span className="font-mono text-xs text-blue-600">{sel.our_product_id}</span>
                          <span className="font-medium text-slate-700">{sel.category}</span>
                          <span className="ml-auto text-xs text-slate-500">₹{sel.buying_price}</span>
                          <button type="button" onClick={() => setLines((p) => p.map((l, j) => j === i ? { ...l, catalog_product_id: "", search: "" } : l))} className="text-slate-300 hover:text-red-500">✕</button>
                        </div>
                      ) : (
                        <div>
                          <input value={line.search} onChange={(e) => setLines((p) => p.map((l, j) => j === i ? { ...l, search: e.target.value } : l))} placeholder="Type to search…" className={INPUT} autoComplete="off" />
                          {suggestions.length > 0 && (
                            <div className="absolute z-20 mt-1 w-full rounded-xl border border-slate-200 bg-white shadow-lg">
                              {suggestions.map((p) => (
                                <button key={p.id} type="button" onClick={() => setLines((prev) => prev.map((l, j) => j === i ? { ...l, catalog_product_id: String(p.id), search: "" } : l))}
                                  className="flex w-full items-center gap-3 px-3 py-2.5 hover:bg-blue-50 text-left text-sm">
                                  <span className="font-mono text-xs text-slate-400 w-16 shrink-0">{p.our_product_id}</span>
                                  <span className="flex-1 font-medium">{p.category}</span>
                                  <span className="text-xs font-semibold">₹{p.buying_price}</span>
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                    <input type="number" min="1" value={line.quantity} onChange={(e) => setLines((p) => p.map((l, j) => j === i ? { ...l, quantity: e.target.value } : l))} className="w-20 rounded-lg border border-slate-300 px-3 py-2 text-sm text-center" />
                    {lines.length > 1 && <button type="button" onClick={() => setLines((p) => p.filter((_, j) => j !== i))} className="mt-2 text-slate-300 hover:text-red-500">✕</button>}
                  </div>
                );
              })}
            </div>
            <button type="button" onClick={() => setLines((p) => [...p, { catalog_product_id: "", quantity: "1", search: "" }])} className="mt-2 text-sm text-blue-600 hover:underline">+ Add item</button>
          </div>
        )}

        <button type="submit" disabled={saving || !vendorId} className={BTN_PRIMARY}>{saving ? "Creating…" : "Create purchase order"}</button>
      </form>
    </div>
  );
}

// ──────────────────── EXPENSE ────────────────────

const EXPENSE_CATEGORIES = ["Rent", "Salary", "Transport", "Packaging", "Utilities", "Marketing", "Miscellaneous"];

function ExpenseForm({ headers, saving, setSaving, showToast }: {
  headers: () => Record<string, string>;
  saving: boolean;
  setSaving: (b: boolean) => void;
  showToast: (msg: string, ok: boolean) => void;
}) {
  const [key, setKey] = useState(0);
  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    const body = { expense_date: fd.get("expense_date"), category: fd.get("category"), description: fd.get("description") || null, amount: fd.get("amount"), payment_mode: fd.get("payment_mode"), reference: fd.get("reference") || null };
    setSaving(true);
    const r = await fetchApi(apiUrl("expenses"), { method: "POST", headers: headers(), body: JSON.stringify(body) });
    const data = await r.json().catch(() => ({}));
    setSaving(false);
    if (!r.ok) { showToast(formatApiError(data), false); return; }
    showToast("Expense recorded.", true);
    setKey((k) => k + 1);
  }
  return (
    <div key={key}>
      <h3 className="mb-4 text-base font-semibold text-slate-800">🧾 Record expense</h3>
      <form onSubmit={onSubmit} className="grid grid-cols-2 gap-4 max-w-lg">
        <div><label className={LABEL}>Date *</label><input name="expense_date" type="date" required defaultValue={new Date().toISOString().slice(0, 10)} className={INPUT} /></div>
        <div>
          <label className={LABEL}>Category *</label>
          <select name="category" required className={INPUT}>
            <option value="">— select —</option>
            {EXPENSE_CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
        <div className="col-span-2"><label className={LABEL}>Description</label><input name="description" className={INPUT} /></div>
        <div><label className={LABEL}>Amount ₹ *</label><input name="amount" type="number" required step="0.01" min="0.01" className={INPUT} /></div>
        <div>
          <label className={LABEL}>Payment mode</label>
          <select name="payment_mode" className={INPUT}>
            <option value="cash">Cash</option>
            <option value="upi">UPI</option>
            <option value="bank_transfer">Bank</option>
            <option value="cheque">Cheque</option>
          </select>
        </div>
        <div><label className={LABEL}>Reference</label><input name="reference" className={INPUT} /></div>
        <div className="col-span-2"><button type="submit" disabled={saving} className={BTN_PRIMARY}>{saving ? "Saving…" : "Record expense"}</button></div>
      </form>
    </div>
  );
}
