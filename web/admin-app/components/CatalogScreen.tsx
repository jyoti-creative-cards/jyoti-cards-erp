"use client";

import { useCallback, useEffect, useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import { Drawer } from "@/components/Drawer";
import { apiUrl, fetchApi, formatApiError } from "@/lib/api";
import type { CatalogProductPublic, ProductPricePublic, ProductAlternativePublic, VendorPublic } from "@/lib/types";

const INPUT = "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500";
const LABEL = "mb-1 block text-xs font-semibold text-slate-500 uppercase tracking-wider";
const BTN_PRIMARY = "inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-700 disabled:opacity-50";
const BTN_SECONDARY = "inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm transition hover:bg-slate-50";

function emptyToNull(v: FormDataEntryValue | null): string | null {
  const s = String(v ?? "").trim();
  return s === "" ? null : s;
}

interface Props {
  adminKey: string;
}

export function CatalogScreen({ adminKey }: Props) {
  const [tab, setTab] = useState<"products" | "prices" | "addons">("products");
  const headers = () => {
    const h: Record<string, string> = { "Content-Type": "application/json" };
    if (adminKey.trim()) h["X-Admin-Key"] = adminKey.trim();
    return h;
  };
  const headersAdmin = (): Record<string, string> => adminKey.trim() ? { "X-Admin-Key": adminKey.trim() } : {};

  // Shared catalog data
  const [products, setProducts] = useState<CatalogProductPublic[]>([]);
  const [vendors, setVendors] = useState<VendorPublic[]>([]);
  const [categoryList, setCategoryList] = useState<string[]>([]);
  // Units — fetched from API, managed in Admin > Units
  const [units, setUnits] = useState<string[]>(["pcs", "bundle", "box", "dozen", "set", "pair", "roll", "sheet"]);
  const [seriesList, setSeriesList] = useState<string[]>([]);
  const [yearGroups, setYearGroups] = useState<string[]>([]);

  const loadProducts = useCallback(async () => {
    if (!adminKey.trim()) return;
    const [pr, vr, sr, yr, cr, ur] = await Promise.all([
      fetchApi(apiUrl("catalog"), { headers: headersAdmin() }),
      fetchApi(apiUrl("vendors"), { headers: headersAdmin() }),
      fetchApi(apiUrl("catalog/series"), { headers: headersAdmin() }),
      fetchApi(apiUrl("catalog/year-groups"), { headers: headersAdmin() }),
      fetchApi(apiUrl("catalog/categories"), { headers: headersAdmin() }),
      fetchApi(apiUrl("catalog/units"), { headers: headersAdmin() }),
    ]);
    if (pr.ok) {
      const data = await pr.json() as { items: CatalogProductPublic[]; total: number } | CatalogProductPublic[];
      // Handle both paginated response and legacy array
      const items = Array.isArray(data) ? data : (data.items ?? []);
      setProducts(items);
    }
    if (vr.ok) setVendors(await vr.json());
    if (sr.ok) { const d = await sr.json(); setSeriesList(d.series ?? []); }
    if (yr.ok) { const d = await yr.json(); setYearGroups(d.year_groups ?? []); }
    if (cr.ok) { const d = await cr.json(); setCategoryList((d.categories ?? []).sort()); }
    if (ur.ok) { const d = await ur.json(); setUnits((d.units ?? []).sort()); }
  }, [adminKey]);

  useEffect(() => { void loadProducts(); }, [loadProducts]);

  const vendorName = (id: number) => {
    const v = vendors.find((v) => v.id === id);
    return v?.company_name || v?.person_name || `#${id}`;
  };

  return (
    <div>
      <div className="mb-6 flex gap-2">
        {([
          { id: "products", label: "📦 Products" },
          { id: "prices",   label: "💲 Price history" },
          { id: "addons",   label: "🎁 Add-ons" },
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

      {tab === "products" && (
        <ProductsTab
          products={products}
          vendors={vendors}
          vendorName={vendorName}
          categories={categoryList}
          units={units}
          seriesList={seriesList}
          setSeriesList={setSeriesList}
          yearGroups={yearGroups}
          setYearGroups={setYearGroups}
          headers={headers}
          headersAdmin={headersAdmin}
          adminKey={adminKey}
          onRefresh={loadProducts}
        />
      )}
      {tab === "prices" && (
        <PricesTab products={products} headers={headers} headersAdmin={headersAdmin} adminKey={adminKey} />
      )}
      {tab === "addons" && (
        <AddonsTab products={products} headers={headers} headersAdmin={headersAdmin} adminKey={adminKey} />
      )}
    </div>
  );
}

// ─────────────────────────────── PRODUCTS ───────────────────────────────

function ProductsTab({
  products,
  vendors,
  vendorName,
  categories,
  units,
  setUnits,
  seriesList,
  setSeriesList,
  yearGroups,
  setYearGroups,
  headers,
  headersAdmin,
  adminKey,
  onRefresh,
}: {
  products: CatalogProductPublic[];
  vendors: VendorPublic[];
  vendorName: (id: number) => string;
  categories: string[];
  units: string[];
  setUnits: Dispatch<SetStateAction<string[]>>;
  seriesList: string[];
  setSeriesList: Dispatch<SetStateAction<string[]>>;
  yearGroups: string[];
  setYearGroups: Dispatch<SetStateAction<string[]>>;
  headers: () => Record<string, string>;
  headersAdmin: () => Record<string, string>;
  adminKey: string;
  onRefresh: () => void;
}) {
  const [search, setSearch] = useState("");
  const [catFilter, setCatFilter] = useState("");
  const [vendorFilter, setVendorFilter] = useState("");
  const [yearFilter, setYearFilter] = useState("2026-27");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editing, setEditing] = useState<CatalogProductPublic | null>(null);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null);
  const [imgMsg, setImgMsg] = useState("");
  // New unit input
  const [newUnit, setNewUnit] = useState(""); // kept for type compat, not used
  // Addon state
  const [addonId, setAddonId] = useState<string>("");
  const [addons, setAddons] = useState<{ id: number; name: string }[]>([]);
  // Bulk add state
  const [showBulk, setShowBulk] = useState(false);
  type BulkRow = { our_product_id: string; vendor_product_id: string; category: string; unit: string; buying_price: string; selling_price: string };
  const emptyRow = (): BulkRow => ({ our_product_id: "", vendor_product_id: "", category: "", unit: "pcs", buying_price: "", selling_price: "" });
  const [bulkVendorId, setBulkVendorId] = useState("");
  const [bulkRows, setBulkRows] = useState<BulkRow[]>([emptyRow(), emptyRow(), emptyRow()]);
  const [bulkSaving, setBulkSaving] = useState(false);
  const [bulkResult, setBulkResult] = useState<{ created: number; errors: {row: number; error: string}[] } | null>(null);

  useEffect(() => {
    if (!adminKey.trim()) return;
    fetchApi(apiUrl("addons"), { headers: headersAdmin() })
      .then((r) => r.ok ? r.json() : [])
      .then((data: { id: number; name: string }[]) => setAddons(data))
      .catch(() => {/* ignore */});
  }, [adminKey]); // eslint-disable-line react-hooks/exhaustive-deps

  async function submitBulk() {
    if (!bulkVendorId) { showToast("Select a vendor", false); return; }
    const rows = bulkRows.filter(r => r.our_product_id.trim());
    if (!rows.length) { showToast("Add at least one product", false); return; }
    setBulkSaving(true); setBulkResult(null);
    const body = rows.map(r => ({
      our_product_id: r.our_product_id.trim(),
      vendor_id: Number(bulkVendorId),
      name: r.category.trim() || r.our_product_id.trim(),
      vendor_product_id: r.vendor_product_id.trim() || r.our_product_id.trim(),
      category: r.category.trim() || "Uncategorised",
      unit: r.unit || "pcs",
      buying_price: Number(r.buying_price) || 0,
      selling_price: Number(r.selling_price) || 0,
    }));
    const r = await fetchApi(apiUrl("catalog/bulk"), { method: "POST", headers: { ...headersAdmin(), "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await r.json().catch(() => ({})) as { created: number; errors: {row: number; error: string}[] };
    setBulkSaving(false);
    if (!r.ok) { showToast(formatApiError(data as Record<string, unknown>), false); return; }
    setBulkResult(data);
    if (data.created > 0) { onRefresh(); showToast(`${data.created} product(s) created.`, true); }
    if (data.errors?.length === 0) { setBulkRows([emptyRow(), emptyRow(), emptyRow()]); }
  }

  function openProduct(p: CatalogProductPublic | null) {
    setEditing(p);
    setImgMsg("");
    setAddonId("");
    setDrawerOpen(true);
  }

  const showToast = (msg: string, ok: boolean) => {
    setToast({ msg, ok });
    setTimeout(() => setToast(null), 3500);
  };

  const filtered = products.filter((p) => {
    const q = search.toLowerCase();
    const matchSearch = !q || p.our_product_id.toLowerCase().includes(q) || p.category.toLowerCase().includes(q) || p.vendor_product_id.toLowerCase().includes(q);
    const matchCat = !catFilter || p.category === catFilter;
    const matchVendor = !vendorFilter || String(p.vendor_id) === vendorFilter;
    const matchYear = !yearFilter || p.year_group === yearFilter;
    return matchSearch && matchCat && matchVendor && matchYear;
  });

  const PAGE_SIZE = 100;
  const [page, setPage] = useState(0);
  // Reset page when filters change
  useEffect(() => { setPage(0); }, [search, catFilter, vendorFilter, yearFilter]);
  const pageCount = Math.ceil(filtered.length / PAGE_SIZE);
  const pagedProducts = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  async function onSave(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!adminKey.trim()) return;
    setSaving(true);
    const form = e.currentTarget;
    const fd = new FormData(form);
    const body: Record<string, unknown> = {
      our_product_id: String(fd.get("our_product_id") ?? "").trim(),
      vendor_id: Number(fd.get("vendor_id")),
      name: String(fd.get("category") ?? "").trim(), // use category as name
      vendor_product_id: String(fd.get("vendor_product_id") ?? "").trim(),
      category: String(fd.get("category") ?? "").trim(),
      unit: String(fd.get("unit") ?? "pcs").trim() || "pcs",
      buying_price: Number(fd.get("buying_price")),
      selling_price: Number(fd.get("selling_price")),
      series: String(fd.get("series") ?? "").trim() || null,
      year_group: String(fd.get("year_group") ?? "").trim() || null,
    };
    if (addonId) body.addon_id = Number(addonId);

    if (editing) {
      // PATCH
      const r = await fetchApi(apiUrl(`catalog/${editing.id}`), {
        method: "PATCH", headers: headers(), body: JSON.stringify(body),
      });
      const data = await r.json().catch(() => ({}));
      setSaving(false);
      if (!r.ok) { showToast(formatApiError(data), false); return; }
      setEditing(data as CatalogProductPublic);
      showToast("Saved.", true);
      onRefresh();
    } else {
      // POST
      const r = await fetchApi(apiUrl("catalog"), {
        method: "POST", headers: headers(), body: JSON.stringify(body),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) { setSaving(false); showToast(formatApiError(data), false); return; }
      const created = data as CatalogProductPublic;
      // Upload images if any
      const imgInput = form.querySelector<HTMLInputElement>('input[name="images"]');
      const fl = imgInput?.files;
      if (fl?.length) {
        const up = new FormData();
        for (let i = 0; i < fl.length; i++) up.append("files", fl.item(i)!);
        await fetchApi(apiUrl(`catalog/${created.id}/images`), { method: "POST", headers: headersAdmin(), body: up });
      }
      setSaving(false);
      showToast(`Product "${created.our_product_id}" created.`, true);
      setDrawerOpen(false);
      onRefresh();
    }
  }

  async function uploadImages(files: FileList | null) {
    if (!editing || !files?.length) return;
    setImgMsg("");
    const up = new FormData();
    for (let i = 0; i < files.length; i++) up.append("files", files.item(i)!);
    const r = await fetchApi(apiUrl(`catalog/${editing.id}/images`), { method: "POST", headers: headersAdmin(), body: up });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) { setImgMsg(formatApiError(data)); return; }
    setEditing(data as CatalogProductPublic);
    onRefresh();
  }

  async function deleteImage(key: string) {
    if (!editing || !confirm("Remove this image?")) return;
    const r = await fetchApi(apiUrl(`catalog/${editing.id}/images`), { method: "DELETE", headers: headers(), body: JSON.stringify({ key }) });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) { setImgMsg(formatApiError(data)); return; }
    setEditing(data as CatalogProductPublic);
    onRefresh();
  }

  async function delProduct(id: number) {
    if (!confirm("Permanently delete this product?")) return;
    const r = await fetchApi(apiUrl(`catalog/${id}`), { method: "DELETE", headers: headersAdmin() });
    if (r.ok) { showToast("Deleted.", true); setDrawerOpen(false); onRefresh(); }
    else showToast("Delete failed.", false);
  }

  return (
    <div>
      {toast && (
        <div className={`fixed right-4 top-20 z-50 rounded-lg px-4 py-3 text-sm font-medium shadow-lg ${toast.ok ? "bg-emerald-600 text-white" : "bg-red-600 text-white"}`}>
          {toast.msg}
        </div>
      )}

      {/* Toolbar */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search products…"
          className="min-w-[200px] flex-1 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none"
        />
        <select value={catFilter} onChange={(e) => setCatFilter(e.target.value)} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none">
          <option value="">All categories</option>
          {categories.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <select value={vendorFilter} onChange={(e) => setVendorFilter(e.target.value)} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none">
          <option value="">All vendors</option>
          {vendors.map((v) => <option key={v.id} value={v.id}>{v.company_name || v.person_name}</option>)}
        </select>
        <select value={yearFilter} onChange={(e) => setYearFilter(e.target.value)} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none">
          <option value="">All years</option>
          {["2026-27", ...yearGroups.filter(y => y !== "2026-27")].map((y) => <option key={y} value={y}>{y}</option>)}
        </select>
        <button type="button" onClick={onRefresh} className={BTN_SECONDARY}>↻ Refresh</button>
        <button type="button" onClick={() => openProduct(null)} className={BTN_PRIMARY}>
          + New product
        </button>
        <button type="button" onClick={() => { setShowBulk(b => !b); setBulkResult(null); }} className={BTN_SECONDARY}>
          + Bulk Add
        </button>
      </div>

      {/* Bulk add panel */}
      {showBulk && (
        <div className="mb-4 rounded-2xl border border-blue-200 bg-blue-50 p-4 space-y-3">
          <div className="flex items-center justify-between">
            <div className="text-sm font-bold text-blue-800">Bulk Add Products</div>
            <button type="button" onClick={() => setShowBulk(false)} className="text-slate-400 hover:text-slate-600">✕</button>
          </div>
          <div>
            <label className="mb-1 block text-xs font-semibold uppercase tracking-wider text-slate-500">Vendor *</label>
            <select value={bulkVendorId} onChange={e => setBulkVendorId(e.target.value)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm w-full max-w-xs">
              <option value="">— Select vendor —</option>
              {vendors.map(v => <option key={v.id} value={v.id}>{v.company_name || v.person_name}</option>)}
            </select>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-slate-500 font-semibold">
                  <th className="pb-1 pr-2 text-left">Our Product ID *</th>
                  <th className="pb-1 pr-2 text-left">Vendor Product ID</th>
                  <th className="pb-1 pr-2 text-left">Category</th>
                  <th className="pb-1 pr-2 text-left">Unit</th>
                  <th className="pb-1 pr-2 text-left">Buy Price</th>
                  <th className="pb-1 pr-2 text-left">Sell Price</th>
                  <th className="pb-1 text-left"></th>
                </tr>
              </thead>
              {/* datalist removed — category is now a strict select */}
              <datalist id="bulk-units-list">
                {units.map(u => <option key={u} value={u} />)}
              </datalist>
              <tbody>
                {bulkRows.map((row, idx) => (
                  <tr key={idx}>
                    {(["our_product_id", "vendor_product_id", "category", "unit", "buying_price", "selling_price"] as const).map(field => (
                      <td key={field} className="pr-2 pb-1">
                        {field === "category" ? (
                          <select
                            value={row[field]}
                            onChange={e => setBulkRows(rows => rows.map((r, i) => i === idx ? { ...r, [field]: e.target.value } : r))}
                            className="w-full rounded border border-slate-300 px-2 py-1 text-xs focus:border-blue-400 focus:outline-none"
                          >
                            <option value="">— select —</option>
                            {categories.map(c => <option key={c} value={c}>{c}</option>)}
                          </select>
                        ) : field === "unit" ? (
                          <input
                            type="text"
                            list="bulk-units-list"
                            value={row[field]}
                            placeholder="pcs"
                            onChange={e => setBulkRows(rows => rows.map((r, i) => i === idx ? { ...r, [field]: e.target.value } : r))}
                            className="w-full rounded border border-slate-300 px-2 py-1 text-xs focus:border-blue-400 focus:outline-none"
                          />
                        ) : (
                          <input
                            type={field.includes("price") ? "number" : "text"}
                            value={row[field]}
                            placeholder=""
                            onChange={e => setBulkRows(rows => rows.map((r, i) => i === idx ? { ...r, [field]: e.target.value } : r))}
                            className="w-full rounded border border-slate-300 px-2 py-1 text-xs focus:border-blue-400 focus:outline-none"
                          />
                        )}
                      </td>
                    ))}
                    <td className="pb-1">
                      <button type="button" onClick={() => setBulkRows(rows => rows.filter((_, i) => i !== idx))} className="text-red-400 hover:text-red-600">×</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex items-center gap-3 flex-wrap">
            <button type="button" onClick={() => setBulkRows(r => [...r, emptyRow()])} className="text-xs text-blue-600 hover:underline">+ Add row</button>
            <button type="button" onClick={submitBulk} disabled={bulkSaving} className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-1.5 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-50">
              {bulkSaving ? "Creating…" : "Create All"}
            </button>
          </div>
          {bulkResult && (
            <div className="text-xs space-y-1">
              <div className="text-emerald-600 font-semibold">✓ {bulkResult.created} product(s) created</div>
              {bulkResult.errors.map((e, i) => (
                <div key={i} className="text-red-600">Row {e.row + 1}: {e.error}</div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Grid */}
      {filtered.length === 0 ? (
        <div className="rounded-xl border-2 border-dashed border-slate-200 py-16 text-center text-slate-400">
          <div className="text-4xl">📦</div>
          <div className="mt-2 font-medium">No products</div>
        </div>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {pagedProducts.map((p) => (
              <div
                key={p.id}
                className="cursor-pointer rounded-xl border border-slate-200 bg-white p-4 shadow-sm transition hover:border-blue-300 hover:shadow-md"
                onClick={() => openProduct(p)}
              >
                {/* Image */}
                <div className="mb-3 flex h-24 items-center justify-center overflow-hidden rounded-lg bg-slate-100">
                  {p.image_urls[0] ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={p.image_urls[0]} alt={p.name} className="h-full w-full object-cover" />
                  ) : (
                    <span className="text-3xl text-slate-300">📦</span>
                  )}
                </div>
                {/* Info */}
                <div className="text-xs font-mono text-slate-400">{p.our_product_id}</div>
                <div className="mt-0.5 font-semibold text-slate-800 leading-tight">{p.category}</div>
                <div className="mt-1 flex items-center gap-1.5">
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-500">{p.unit || "pcs"}</span>
                </div>
                <div className="mt-2 flex items-center justify-between">
                  <span className="text-sm font-bold text-slate-900">₹{p.selling_price}</span>
                  <span className="text-xs text-slate-400">{vendorName(p.vendor_id)}</span>
                </div>
              </div>
            ))}
          </div>
          {pageCount > 1 && (
            <div className="mt-4 flex items-center justify-center gap-2 text-sm">
              <button type="button" disabled={page === 0} onClick={() => setPage(p => p - 1)} className="rounded-lg border border-slate-300 px-3 py-1.5 text-slate-600 hover:bg-slate-50 disabled:opacity-40">← Prev</button>
              <span className="text-slate-500">Page {page + 1} of {pageCount} · {filtered.length} products</span>
              <button type="button" disabled={page >= pageCount - 1} onClick={() => setPage(p => p + 1)} className="rounded-lg border border-slate-300 px-3 py-1.5 text-slate-600 hover:bg-slate-50 disabled:opacity-40">Next →</button>
            </div>
          )}
        </>
      )}

      {/* Drawer */}
      <Drawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        title={editing ? `${editing.our_product_id} — ${editing.category}` : "New product"}
        subtitle={editing ? `${editing.unit || "pcs"} · ${vendorName(editing.vendor_id)}` : "Add a new catalog product"}
        width="max-w-xl"
        footer={
          <div className="flex items-center justify-between gap-3">
            <div className="flex gap-3">
              <button type="submit" form="product-form" disabled={saving} className={BTN_PRIMARY}>
                {saving ? "Saving…" : editing ? "Save changes" : "Create product"}
              </button>
              <button type="button" onClick={() => setDrawerOpen(false)} className={BTN_SECONDARY}>Cancel</button>
            </div>
            {editing && (
              <button type="button" onClick={() => void delProduct(editing.id)} className="text-sm text-red-500 hover:underline">
                Delete product
              </button>
            )}
          </div>
        }
      >
        <form id="product-form" onSubmit={onSave} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className={LABEL}>Our product ID *</label>
              <input name="our_product_id" required defaultValue={editing?.our_product_id ?? ""}
                readOnly={editing ? (editing.image_keys?.length ?? 0) > 0 : false}
                className={INPUT + ((editing && (editing.image_keys?.length ?? 0) > 0) ? " bg-slate-100" : "")} />
            </div>
            <div>
              <label className={LABEL}>Vendor SKU *</label>
              <input name="vendor_product_id" required defaultValue={editing?.vendor_product_id ?? ""} className={INPUT} />
            </div>
            <div>
              <label className={LABEL}>Vendor *</label>
              <select name="vendor_id" required defaultValue={editing?.vendor_id ?? ""} className={INPUT}>
                <option value="">— select vendor —</option>
                {vendors.map((v) => <option key={v.id} value={v.id}>{v.company_name || v.person_name}</option>)}
              </select>
            </div>
            <div>
              <label className={LABEL}>Category *</label>
              <input name="category" required list="cat-list" defaultValue={editing?.category ?? ""} className={INPUT} />
              <datalist id="cat-list">
                {[...new Set(products.map((p) => p.category))].map((c) => <option key={c} value={c} />)}
              </datalist>
            </div>
            <div>
              <label className={LABEL}>Unit *</label>
              <select name="unit" required defaultValue={editing?.unit ?? "pcs"} className={INPUT}>
                {units.map((u) => <option key={u} value={u}>{u}</option>)}
              </select>
              <p className="mt-1 text-xs text-slate-400">To add new units, go to Admin → Units</p>
            </div>
            <div>
              <label className={LABEL}>Buying price (₹) *</label>
              <input name="buying_price" type="number" required step="0.0001" min="0" defaultValue={editing?.buying_price ?? 0} className={INPUT} />
            </div>
            <div>
              <label className={LABEL}>Selling price (₹) *</label>
              <input name="selling_price" type="number" required step="0.0001" min="0" defaultValue={editing?.selling_price ?? 0} className={INPUT} />
            </div>
            <div>
              <label className={LABEL}>Series (optional)</label>
              <input name="series" list="series-list" defaultValue={editing?.series ?? ""} placeholder="e.g. Ganesh, Laxmi…" className={INPUT} />
              <datalist id="series-list">
                {seriesList.map((s) => <option key={s} value={s} />)}
              </datalist>
            </div>
            <div>
              <label className={LABEL}>Year group (optional)</label>
              <input name="year_group" list="yg-list" defaultValue={editing?.year_group ?? "2026-27"} placeholder="2026-27" className={INPUT} />
              <datalist id="yg-list">
                {yearGroups.map((y) => <option key={y} value={y} />)}
              </datalist>
            </div>
            <div className="col-span-2">
              <label className={LABEL}>Link add-on (optional)</label>
              <select value={addonId} onChange={(e) => setAddonId(e.target.value)} className={INPUT}>
                <option value="">— no add-on —</option>
                {addons.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
              <p className="mt-1 text-xs text-slate-400">Add-on sent with this product when customer orders it.</p>
            </div>
            {!editing && (
              <div className="col-span-2">
                <label className={LABEL}>Images (optional)</label>
                <input name="images" type="file" multiple accept="image/*" className="text-sm" />
              </div>
            )}
          </div>
        </form>

        {/* Image management (edit only) */}
        {editing && (
          <div className="mt-6">
            <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">Images</div>
            {imgMsg && <p className="mb-2 text-sm text-red-600">{imgMsg}</p>}
            <div className="flex flex-wrap gap-2">
              {editing.image_keys.map((key, i) => (
                <div key={key} className="group relative h-20 w-20 overflow-hidden rounded-lg border border-slate-200">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={editing.image_urls[i] ?? ""} alt="" className="h-full w-full object-cover" />
                  <button
                    type="button"
                    onClick={() => void deleteImage(key)}
                    className="absolute inset-0 flex items-center justify-center bg-black/50 opacity-0 transition group-hover:opacity-100"
                  >
                    <span className="text-xs font-semibold text-white">Remove</span>
                  </button>
                </div>
              ))}
            </div>
            <label className="mt-3 inline-flex cursor-pointer items-center gap-2 rounded-lg border border-dashed border-slate-300 px-4 py-2 text-sm text-slate-500 hover:border-blue-400 hover:text-blue-600">
              + Upload images
              <input type="file" multiple accept="image/*" className="hidden" onChange={(e) => void uploadImages(e.target.files)} />
            </label>
          </div>
        )}

        {/* Alternatives — only shown when editing an existing product */}
        {editing && (
          <AlternativesSection
            product={editing}
            allProducts={products}
            headers={headers}
            headersAdmin={headersAdmin}
            adminKey={adminKey}
          />
        )}
      </Drawer>
    </div>
  );
}

// ─────────────────────────────── PRICE HISTORY ───────────────────────────────

function PricesTab({
  products,
  headers,
  headersAdmin,
  adminKey,
}: {
  products: CatalogProductPublic[];
  headers: () => Record<string, string>;
  headersAdmin: () => Record<string, string>;
  adminKey: string;
}) {
  const [selectedId, setSelectedId] = useState("");
  const [history, setHistory] = useState<ProductPricePublic[]>([]);
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState("");
  const [ok, setOk] = useState("");
  const [saving, setSaving] = useState(false);

  async function load(pid: string) {
    if (!pid || !adminKey.trim()) return;
    setLoading(true);
    const r = await fetchApi(apiUrl(`product-prices/${pid}`), { headers: headersAdmin() });
    const d = await r.json().catch(() => []);
    setHistory(r.ok && Array.isArray(d) ? d : []);
    setLoading(false);
  }

  async function onSetPrice(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!selectedId) return;
    setSaving(true); setMsg(""); setOk("");
    const fd = new FormData(e.currentTarget);
    const body = {
      catalog_product_id: Number(selectedId),
      buying_price: String(fd.get("buying_price")),
      selling_price: String(fd.get("selling_price")),
      start_date: fd.get("start_date"),
    };
    const r = await fetchApi(apiUrl("product-prices"), { method: "POST", headers: headers(), body: JSON.stringify(body) });
    const data = await r.json().catch(() => ({}));
    setSaving(false);
    if (!r.ok) { setMsg(formatApiError(data)); return; }
    setOk("Price updated.");
    (e.target as HTMLFormElement).reset();
    void load(selectedId);
  }

  const selected = products.find((p) => String(p.id) === selectedId);

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <label className={LABEL}>Select product</label>
        <select
          value={selectedId}
          onChange={(e) => { setSelectedId(e.target.value); void load(e.target.value); }}
          className={INPUT}
        >
          <option value="">— choose a product —</option>
          {products.map((p) => <option key={p.id} value={p.id}>{p.our_product_id} — {p.category}</option>)}
        </select>
      </div>

      {selected && (
        <>
          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="mb-3 text-sm font-semibold text-slate-700">Set new price for: {selected.category}</div>
            <form onSubmit={onSetPrice} className="grid grid-cols-3 gap-3">
              <div>
                <label className={LABEL}>Buying price (₹) *</label>
                <input name="buying_price" type="number" required step="0.0001" min="0"
                  defaultValue={history.find((h) => h.is_current)?.buying_price ?? selected.buying_price}
                  className={INPUT} />
              </div>
              <div>
                <label className={LABEL}>Selling price (₹) *</label>
                <input name="selling_price" type="number" required step="0.0001" min="0"
                  defaultValue={history.find((h) => h.is_current)?.selling_price ?? selected.selling_price}
                  className={INPUT} />
              </div>
              <div>
                <label className={LABEL}>Effective from *</label>
                <input name="start_date" type="date" required defaultValue={new Date().toISOString().slice(0, 10)} className={INPUT} />
              </div>
              <div className="col-span-3 flex items-center gap-3">
                <button type="submit" disabled={saving} className={BTN_PRIMARY}>
                  {saving ? "Saving…" : "Set new price"}
                </button>
                {msg && <span className="text-sm text-red-600">{msg}</span>}
                {ok && <span className="text-sm text-emerald-600">{ok}</span>}
              </div>
            </form>
          </div>

          <div>
            <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">Price history</div>
            {loading ? <div className="text-slate-400">Loading…</div> : history.length === 0 ? (
              <div className="text-sm text-slate-400">No price history yet.</div>
            ) : (
              <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-200 bg-slate-50 text-xs font-semibold uppercase text-slate-500">
                      <th className="px-4 py-2 text-left">Buying</th>
                      <th className="px-4 py-2 text-left">Selling</th>
                      <th className="px-4 py-2 text-left">From</th>
                      <th className="px-4 py-2 text-left">To</th>
                      <th className="px-4 py-2 text-left">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {history.map((h) => (
                      <tr key={h.id}>
                        <td className="px-4 py-2 font-medium">₹{h.buying_price}</td>
                        <td className="px-4 py-2 font-medium">₹{h.selling_price}</td>
                        <td className="px-4 py-2 text-slate-500">{h.start_date}</td>
                        <td className="px-4 py-2 text-slate-500">{h.end_date ?? "—"}</td>
                        <td className="px-4 py-2">
                          {h.is_current ? (
                            <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700">Current</span>
                          ) : (
                            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">Past</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

// ─────────────────────────────── ADD-ONS ───────────────────────────────

interface AddonProduct { id: number; name: string; description: string | null; unit: string; stock_quantity?: number; }
interface AddonLink { id: number; catalog_product_id: number; addon_product_id: number; quantity_per_card: number; addon_name: string; }

function AddonsTab({
  products,
  headers,
  headersAdmin,
  adminKey,
}: {
  products: CatalogProductPublic[];
  headers: () => Record<string, string>;
  headersAdmin: () => Record<string, string>;
  adminKey: string;
}) {
  const [addons, setAddons] = useState<AddonProduct[]>([]);
  const [links, setLinks] = useState<AddonLink[]>([]);
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null);
  const [selectedProduct, setSelectedProduct] = useState("");
  const [mode, setMode] = useState<"create" | "stock" | "link" | null>(null);

  const showToast = (msg: string, ok: boolean) => { setToast({ msg, ok }); setTimeout(() => setToast(null), 3500); };

  const load = useCallback(async () => {
    if (!adminKey.trim()) return;
    const [ar, lr] = await Promise.all([
      fetchApi(apiUrl("addons"), { headers: headersAdmin() }),
      fetchApi(apiUrl("addons/links"), { headers: headersAdmin() }),
    ]);
    if (ar.ok) setAddons(await ar.json());
    if (lr.ok) setLinks(await lr.json());
  }, [adminKey]);

  useEffect(() => { void load(); }, [load]);

  async function createAddon(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    const r = await fetchApi(apiUrl("addons"), { method: "POST", headers: headers(), body: JSON.stringify({ name: fd.get("name"), description: fd.get("description") || null, unit: fd.get("unit") }) });
    if (r.ok) { (e.target as HTMLFormElement).reset(); setMode(null); void load(); showToast("Add-on created.", true); }
    else showToast("Failed.", false);
  }

  async function adjustStock(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    const r = await fetchApi(apiUrl("addons/stock-adjust"), { method: "POST", headers: headers(), body: JSON.stringify({ addon_product_id: Number(fd.get("addon_id")), quantity_delta: Number(fd.get("delta")), reason: fd.get("reason") || "Manual" }) });
    if (r.ok) { (e.target as HTMLFormElement).reset(); setMode(null); void load(); showToast("Stock updated.", true); }
    else showToast("Failed.", false);
  }

  async function linkAddon(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    const r = await fetchApi(apiUrl("addons/links"), { method: "POST", headers: headers(), body: JSON.stringify({ catalog_product_id: Number(selectedProduct), addon_product_id: Number(fd.get("addon_id")), quantity_per_card: Number(fd.get("qty")) }) });
    if (r.ok) { (e.target as HTMLFormElement).reset(); void load(); showToast("Linked.", true); }
    else showToast("Failed.", false);
  }

  async function unlinkAddon(id: number) {
    const r = await fetchApi(apiUrl(`addons/links/${id}`), { method: "DELETE", headers: headersAdmin() });
    if (r.ok) { void load(); showToast("Unlinked.", true); }
  }

  const productLinks = links.filter((l) => String(l.catalog_product_id) === selectedProduct);

  return (
    <div className="space-y-6">
      {toast && (
        <div className={`fixed right-4 top-20 z-50 rounded-lg px-4 py-3 text-sm font-medium shadow-lg ${toast.ok ? "bg-emerald-600 text-white" : "bg-red-600 text-white"}`}>
          {toast.msg}
        </div>
      )}

      {/* Add-on list */}
      <div>
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-slate-700">Add-ons</h3>
          <div className="flex gap-2">
            <button type="button" onClick={() => setMode(mode === "create" ? null : "create")} className={BTN_PRIMARY}>
              + New add-on
            </button>
            <button type="button" onClick={() => setMode(mode === "stock" ? null : "stock")} className={BTN_SECONDARY}>
              Adjust stock
            </button>
          </div>
        </div>

        {mode === "create" && (
          <form onSubmit={createAddon} className="mb-4 grid grid-cols-3 gap-3 rounded-xl border border-slate-200 bg-white p-4">
            <div><label className={LABEL}>Name *</label><input name="name" required className={INPUT} /></div>
            <div><label className={LABEL}>Unit</label><input name="unit" defaultValue="pcs" className={INPUT} /></div>
            <div><label className={LABEL}>Description</label><input name="description" className={INPUT} /></div>
            <div className="col-span-3"><button type="submit" className={BTN_PRIMARY}>Create add-on</button></div>
          </form>
        )}

        {mode === "stock" && (
          <form onSubmit={adjustStock} className="mb-4 grid grid-cols-3 gap-3 rounded-xl border border-slate-200 bg-white p-4">
            <div>
              <label className={LABEL}>Add-on *</label>
              <select name="addon_id" required className={INPUT}>
                <option value="">— select —</option>
                {addons.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
            </div>
            <div><label className={LABEL}>Qty change *</label><input name="delta" type="number" required placeholder="e.g. +50 or -10" className={INPUT} /></div>
            <div><label className={LABEL}>Reason</label><input name="reason" className={INPUT} /></div>
            <div className="col-span-3"><button type="submit" className={BTN_PRIMARY}>Adjust</button></div>
          </form>
        )}

        {addons.length === 0 ? (
          <div className="rounded-xl border-2 border-dashed border-slate-200 py-10 text-center text-slate-400 text-sm">No add-ons yet. Add one to get started.</div>
        ) : (
          <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50 text-xs font-semibold uppercase text-slate-500">
                  <th className="px-4 py-2 text-left">Name</th>
                  <th className="px-4 py-2 text-left">Unit</th>
                  <th className="px-4 py-2 text-left">Description</th>
                  <th className="px-4 py-2 text-right">Stock</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {addons.map((a) => (
                  <tr key={a.id}>
                    <td className="px-4 py-2 font-medium">{a.name}</td>
                    <td className="px-4 py-2 text-slate-500">{a.unit}</td>
                    <td className="px-4 py-2 text-slate-400">{a.description ?? "—"}</td>
                    <td className="px-4 py-2 text-right font-mono font-medium">{a.stock_quantity ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Link add-ons to product */}
      <div>
        <div className="mb-3 text-sm font-semibold text-slate-700">Link add-ons to a product</div>
        <select
          value={selectedProduct}
          onChange={(e) => setSelectedProduct(e.target.value)}
          className={INPUT + " max-w-sm"}
        >
          <option value="">— select product —</option>
          {products.map((p) => <option key={p.id} value={p.id}>{p.our_product_id} — {p.category}</option>)}
        </select>

        {selectedProduct && (
          <div className="mt-4 space-y-3">
            <form onSubmit={linkAddon} className="flex flex-wrap gap-3">
              <select name="addon_id" required className="rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none">
                <option value="">— add-on —</option>
                {addons.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
              <input name="qty" type="number" required min="1" defaultValue="1" placeholder="Qty per card" className="w-36 rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none" />
              <button type="submit" className={BTN_PRIMARY}>Link</button>
            </form>

            {productLinks.length === 0 ? (
              <p className="text-sm text-slate-400">No add-ons linked to this product yet.</p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {productLinks.map((l) => (
                  <div key={l.id} className="flex items-center gap-2 rounded-full bg-blue-50 px-3 py-1.5 text-sm text-blue-700">
                    <span>{l.addon_name} × {l.quantity_per_card}</span>
                    <button type="button" onClick={() => void unlinkAddon(l.id)} className="text-blue-400 hover:text-red-500">✕</button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ─────────────────────────────── ALTERNATIVES ───────────────────────────────

function AlternativesSection({
  product,
  allProducts,
  headers,
  headersAdmin,
  adminKey,
}: {
  product: CatalogProductPublic;
  allProducts: CatalogProductPublic[];
  headers: () => Record<string, string>;
  headersAdmin: () => Record<string, string>;
  adminKey: string;
}) {
  const [alts, setAlts] = useState<ProductAlternativePublic[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null);
  const [adding, setAdding] = useState(false);

  const showToast = (msg: string, ok: boolean) => { setToast({ msg, ok }); setTimeout(() => setToast(null), 3000); };

  const load = useCallback(async () => {
    if (!adminKey.trim()) return;
    setLoading(true);
    const r = await fetchApi(apiUrl(`catalog/${product.id}/alternatives`), { headers: headersAdmin() });
    if (r.ok) setAlts(await r.json());
    setLoading(false);
  }, [product.id, adminKey]);

  useEffect(() => { void load(); }, [load]);

  async function addAlt(altId: number) {
    setAdding(true);
    const r = await fetchApi(apiUrl(`catalog/${product.id}/alternatives`), {
      method: "POST",
      headers: headers(),
      body: JSON.stringify({ alternative_catalog_product_id: altId }),
    });
    const data = await r.json().catch(() => ({}));
    setAdding(false);
    if (!r.ok) { showToast(formatApiError(data), false); return; }
    showToast("Alternative added (reverse link created automatically).", true);
    setSearch("");
    void load();
  }

  async function removeAlt(rowId: number) {
    if (!confirm("Remove this alternative? The reverse link will also be removed.")) return;
    const r = await fetchApi(apiUrl(`catalog/${product.id}/alternatives/${rowId}`), { method: "DELETE", headers: headersAdmin() });
    if (r.ok) { showToast("Removed.", true); void load(); }
    else showToast("Failed.", false);
  }

  // Products that can be added: not already linked, not self
  const altIds = new Set([product.id, ...alts.map((a) => a.alternative_catalog_product_id)]);
  const suggestions = search.trim()
    ? allProducts.filter((p) =>
        !altIds.has(p.id) && (
          p.our_product_id.toLowerCase().includes(search.toLowerCase()) ||
          p.category.toLowerCase().includes(search.toLowerCase())
        )
      ).slice(0, 10)
    : [];

  return (
    <div className="mt-6 rounded-xl border border-slate-200 bg-slate-50 p-4">
      <div className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-500">
        Alternatives
        {alts.length > 0 && <span className="ml-2 rounded-full bg-blue-100 px-2 py-0.5 text-[10px] text-blue-700">{alts.length}</span>}
      </div>

      {toast && (
        <div className={`mb-3 rounded-lg px-3 py-2 text-xs font-medium ${toast.ok ? "bg-emerald-100 text-emerald-700" : "bg-red-100 text-red-700"}`}>
          {toast.msg}
        </div>
      )}

      {/* Current alternatives */}
      {loading ? (
        <div className="text-xs text-slate-400">Loading…</div>
      ) : alts.length === 0 ? (
        <div className="mb-3 text-xs text-slate-400">No alternatives linked yet.</div>
      ) : (
        <div className="mb-3 flex flex-wrap gap-2">
          {alts.map((a) => (
            <div key={a.id} className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-1.5">
              <span className="font-mono text-xs text-slate-400">{a.alternative_our_product_id}</span>
              <span className="text-sm font-medium text-slate-700">{a.alternative_category}</span>
              <button type="button" onClick={() => void removeAlt(a.id)} className="ml-1 text-slate-300 hover:text-red-500">✕</button>
            </div>
          ))}
        </div>
      )}

      {/* Search to add */}
      <div className="relative">
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search product to add as alternative…"
          className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
          autoComplete="off"
        />
        {suggestions.length > 0 && (
          <div className="absolute z-20 mt-1 w-full overflow-hidden rounded-lg border border-slate-200 bg-white shadow-lg">
            {suggestions.map((p) => (
              <button
                key={p.id}
                type="button"
                disabled={adding}
                onClick={() => void addAlt(p.id)}
                className="flex w-full items-center gap-3 px-3 py-2.5 text-left text-sm hover:bg-blue-50 disabled:opacity-50"
              >
                <span className="font-mono text-xs text-slate-400 w-20 shrink-0">{p.our_product_id}</span>
                <span className="flex-1 font-medium text-slate-700">{p.category}</span>
                <span className="text-xs text-slate-400">₹{p.selling_price}</span>
              </button>
            ))}
          </div>
        )}
      </div>
      <p className="mt-1.5 text-[10px] text-slate-400">
        Adding A→B automatically creates B→A. Removing either side removes both.
      </p>
    </div>
  );
}
