"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiUrl, fetchApi, formatApiError } from "@/lib/api";
import type {
  CustomerOrderPublic,
  CustomerPublic,
  PortalPlacementPublic,
  ShopOrderCreateResponse,
  ShopProductPublic,
  ShopSuggestionPublic,
} from "@/lib/types";

function fmtDateTime(iso: string): string {
  try {
    const d = new Date(iso);
    return isNaN(d.getTime())
      ? iso
      : d.toLocaleString("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
  } catch { return iso; }
}

function orderBadgeClass(status: string): string {
  if (status === "shipped") return "bg-violet-100 text-violet-800";
  if (status === "partial") return "bg-sky-100 text-sky-800";
  return "bg-amber-100 text-amber-800";
}

function statusLabel(s: string): string {
  return {
    submitted: "Open",
    received: "Open",
    partial: "Partly billed",
    shipped: "Billed",
  }[s] ?? s;
}

function mergePlacementStatus(statuses: string[]): string {
  if (statuses.some((s) => s === "partial")) return "partial";
  if (statuses.length && statuses.every((s) => s === "shipped")) return "shipped";
  if (statuses.some((s) => s === "shipped")) return "partial";
  return statuses[0] || "submitted";
}

function placementsToOrders(rows: PortalPlacementPublic[]): CustomerOrderPublic[] {
  const byId = new Map<number, CustomerOrderPublic>();
  const statusBag = new Map<number, string[]>();
  for (const p of rows) {
    const line = {
      catalog_product_id: p.catalog_product_id,
      our_product_id: p.our_product_id,
      name: p.series || "",
      category: p.category || "",
      quantity: p.quantity,
      quantity_shipped: p.quantity_shipped,
      unit_price: p.unit_price,
      line_total: p.line_total,
      bill_id: p.bill_id,
      bill_number: p.bill_number,
      has_bill_document: p.has_bill_document,
      status: p.status,
    };
    const statuses = statusBag.get(p.id) || [];
    statuses.push(p.status);
    statusBag.set(p.id, statuses);
    const existing = byId.get(p.id);
    if (existing) {
      existing.items.push(line);
      const sum = existing.items.reduce((acc, it) => acc + Number(it.line_total || 0), 0);
      existing.total_amount = sum.toFixed(2);
      existing.status = mergePlacementStatus(statuses);
      existing.has_order_document = existing.has_order_document || p.has_order_document;
      continue;
    }
    byId.set(p.id, {
      id: p.id,
      customer_id: 0,
      status: p.status,
      items: [line],
      total_amount: p.line_total,
      notes: null,
      customer_notes: p.customer_notes,
      created_at: p.placed_at,
      updated_at: p.placed_at,
      has_order_document: p.has_order_document,
    });
  }
  return Array.from(byId.values());
}

function stockPillClass(s: string): string {
  if (s === "in_stock") return "bg-emerald-100 text-emerald-800 ring-emerald-200/70";
  if (s === "low_stock") return "bg-amber-100 text-amber-800 ring-amber-200/70";
  if (s === "out_of_stock") return "bg-stone-100 text-stone-600 ring-stone-200/70";
  return "bg-stone-100 text-stone-700 ring-stone-200/70";
}

function stockLabel(s: string): string {
  if (s === "in_stock") return "In Stock";
  if (s === "low_stock") return "Low Stock";
  if (s === "out_of_stock") return "Out of Stock";
  return "Unknown";
}

function normalizeQ(s: string): string {
  return s.replace(/\u00a0/g, " ").trim().replace(/\s+/g, " ");
}

function displayCustomerName(profile: CustomerPublic | null): string {
  if (!profile) return "—";
  return profile.business_name || profile.company_name || profile.person_name || profile.name || "—";
}

function digitsPhone(raw: string): string {
  return raw.replace(/\D+/g, "").slice(-10);
}

const MAX_QTY = 100_000_000;

type PortalTab = "search" | "my_order";

export default function CustomerPortalPage() {
  const [loginMsg, setLoginMsg] = useState("");
  const [loggingIn, setLoggingIn] = useState(false);
  const [profile, setProfile] = useState<CustomerPublic | null>(null);
  const [profileLoading, setProfileLoading] = useState(false);
  const [token, setToken] = useState<string | null>(null);
  const [portalTab, setPortalTab] = useState<PortalTab>("search");

  const [shopQ, setShopQ] = useState("");
  const [suggestions, setSuggestions] = useState<ShopSuggestionPublic[]>([]);
  const [suggestOpen, setSuggestOpen] = useState(false);
  const [results, setResults] = useState<ShopProductPublic[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchErr, setSearchErr] = useState("");
  const [didSearch, setDidSearch] = useState(false);
  const suggestTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const searchSeq = useRef(0);

  const [qtyDraft, setQtyDraft] = useState<Record<number, string>>({});
  const [bookingId, setBookingId] = useState<number | null>(null);
  const [toast, setToast] = useState("");
  const [bookErr, setBookErr] = useState("");
  const [pendingBook, setPendingBook] = useState<{ product: ShopProductPublic; qty: number } | null>(null);
  const [noteInput, setNoteInput] = useState("");
  const [imageMap, setImageMap] = useState<Record<number, string>>({});

  const [myOrders, setMyOrders] = useState<CustomerOrderPublic[]>([]);
  const [ordersLoading, setOrdersLoading] = useState(false);
  const [ordersErr, setOrdersErr] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [openLineCount, setOpenLineCount] = useState(0);

  const showToast = useCallback((msg: string) => {
    setToast(msg);
    window.setTimeout(() => setToast(""), 3200);
  }, []);

  const loadMe = useCallback(async (t: string) => {
    setProfileLoading(true);
    try {
      const r = await fetchApi(apiUrl("auth/me"), { headers: { Authorization: `Bearer ${t}` } });
      const me = await r.json().catch(() => null);
      if (r.ok && me) setProfile(me as CustomerPublic);
      else setProfile(null);
    } finally {
      setProfileLoading(false);
    }
  }, []);

  const loadMyOrders = useCallback(async (t: string, sf = "all") => {
    setOrdersErr("");
    setOrdersLoading(true);
    try {
      const r = await fetchApi(apiUrl("shop/orders"), { headers: { Authorization: `Bearer ${t}` } });
      const data = await r.json().catch(() => null);
      if (!r.ok) {
        setOrdersErr(formatApiError(data) || r.statusText);
        setMyOrders([]);
        setOpenLineCount(0);
        return;
      }
      const rows = Array.isArray(data) ? (data as PortalPlacementPublic[]) : [];
      let orders = placementsToOrders(rows);
      setOpenLineCount(rows.filter((x) => x.status === "submitted" || x.status === "partial").length);
      if (sf && sf !== "all") {
        orders = orders.filter((o) => {
          if (sf === "open") return o.status === "submitted" || o.status === "received" || o.status === "partial";
          if (sf === "partial") return o.status === "partial";
          if (sf === "shipped") return o.status === "shipped";
          return true;
        });
      }
      setMyOrders(orders);
      setImageMap((prev) => {
        const next = { ...prev };
        for (const row of rows) {
          if (row.image_url) next[row.catalog_product_id] = row.image_url;
        }
        return next;
      });
    } finally {
      setOrdersLoading(false);
    }
  }, []);

  useEffect(() => {
    try {
      const t = sessionStorage.getItem("token");
      if (t) {
        setToken(t);
        void loadMe(t);
        void loadMyOrders(t);
      }
    } catch { /* ignore */ }
  }, [loadMe, loadMyOrders]);

  async function onLogin(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setLoginMsg("");
    setLoggingIn(true);
    const fd = new FormData(e.currentTarget);
    const phone = digitsPhone(String(fd.get("phone") || ""));
    if (phone.length !== 10) {
      setLoginMsg("Enter a valid 10-digit mobile number.");
      setLoggingIn(false);
      return;
    }
    try {
      const r = await fetchApi(apiUrl("auth/login"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone, password: String(fd.get("password") || "") }),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) {
        setLoginMsg(formatApiError(data) || r.statusText);
        return;
      }
      const t = data.access_token as string;
      sessionStorage.setItem("token", t);
      setToken(t);
      await loadMe(t);
      await loadMyOrders(t);
    } finally {
      setLoggingIn(false);
    }
  }

  function logout() {
    try { sessionStorage.removeItem("token"); } catch { /* ignore */ }
    setToken(null);
    setProfile(null);
    setLoginMsg("");
    setShopQ("");
    setResults([]);
    setSuggestions([]);
    setDidSearch(false);
    setMyOrders([]);
    setOpenLineCount(0);
    setPortalTab("search");
  }

  const runSearch = useCallback(async (qRaw?: string) => {
    setSearchErr("");
    if (!token) return;
    const q = normalizeQ(qRaw ?? shopQ);
    if (q.length < 1) {
      setSearchErr("Type a product name / code (e.g. 9500).");
      return;
    }
    const seq = ++searchSeq.current;
    setSearching(true);
    try {
      const r = await fetchApi(apiUrl(`shop/products/search?q=${encodeURIComponent(q)}`), {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await r.json().catch(() => null);
      if (seq !== searchSeq.current) return;
      if (!r.ok) {
        setSearchErr(formatApiError(data) || r.statusText);
        return;
      }
      const rows = Array.isArray(data) ? (data as ShopProductPublic[]) : [];
      setResults(rows);
      setDidSearch(true);
      setQtyDraft((prev) => {
        const next = { ...prev };
        for (const row of rows) if (next[row.catalog_product_id] === undefined) next[row.catalog_product_id] = "1";
        return next;
      });
      setImageMap((prev) => {
        const next = { ...prev };
        for (const row of rows) if (row.image_url) next[row.catalog_product_id] = row.image_url;
        return next;
      });
    } finally {
      if (seq === searchSeq.current) setSearching(false);
    }
  }, [token, shopQ]);

  useEffect(() => {
    const qn = normalizeQ(shopQ);
    if (!token || qn.length < 1) {
      setSuggestions([]);
      return;
    }
    if (suggestTimer.current) clearTimeout(suggestTimer.current);
    suggestTimer.current = setTimeout(async () => {
      const r = await fetchApi(apiUrl(`shop/products/suggestions?q=${encodeURIComponent(qn)}`), {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await r.json().catch(() => []);
      setSuggestions(r.ok && Array.isArray(data) ? (data as ShopSuggestionPublic[]) : []);
    }, 160);
    return () => { if (suggestTimer.current) clearTimeout(suggestTimer.current); };
  }, [shopQ, token]);

  // Typeahead search — Amazon-style: results while typing (debounced).
  useEffect(() => {
    const qn = normalizeQ(shopQ);
    if (!token || qn.length < 1) return;
    if (searchTimer.current) clearTimeout(searchTimer.current);
    searchTimer.current = setTimeout(() => { void runSearch(qn); }, 280);
    return () => { if (searchTimer.current) clearTimeout(searchTimer.current); };
  }, [shopQ, token, runSearch]);

  useEffect(() => {
    if (!token || portalTab !== "my_order") return;
    void loadMyOrders(token, statusFilter);
  }, [token, portalTab, statusFilter, loadMyOrders]);

  function pickSuggest(s: ShopSuggestionPublic) {
    setShopQ(s.our_product_id);
    setSuggestOpen(false);
    setSuggestions([]);
    void runSearch(s.our_product_id);
  }

  function startBook(p: ShopProductPublic, qtyStr: string) {
    setBookErr("");
    if (!token || p.stock_status === "out_of_stock") return;
    if (!p.selling_price || Number(p.selling_price) <= 0) {
      setBookErr("Price not set for this product. Please call godown.");
      return;
    }
    const n = Math.floor(Number(qtyStr));
    const qty = Number.isFinite(n) ? Math.max(1, Math.min(n, MAX_QTY)) : 1;
    setNoteInput("");
    setPendingBook({ product: p, qty });
  }

  async function confirmBook(note?: string) {
    if (!token || !pendingBook) return;
    const { product: p, qty } = pendingBook;
    const notes = (note || "").trim() || null;
    setPendingBook(null);
    setBookingId(p.catalog_product_id);
    setBookErr("");
    try {
      const r = await fetchApi(apiUrl("shop/orders"), {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({
          catalog_product_id: p.catalog_product_id,
          quantity: qty,
          customer_notes: notes,
        }),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) {
        setBookErr(formatApiError(data) || r.statusText);
        return;
      }
      const res = data as ShopOrderCreateResponse;
      showToast(res.message || (res.merged ? "Added to your order" : "Order started"));
      void loadMyOrders(token);
      // Stay on search so dealer can add the next code immediately.
    } finally {
      setBookingId(null);
    }
  }

  async function openOrderPdf(orderId: number) {
    if (!token) return;
    try {
      const r = await fetchApi(apiUrl(`shop/orders/${orderId}/document`), {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) {
        showToast(formatApiError(data) || "Order PDF not ready yet");
        return;
      }
      if (data.document_url) window.open(data.document_url as string, "_blank");
    } catch {
      showToast("Could not open order PDF");
    }
  }

  async function openBillPdf(billId: number) {
    if (!token) return;
    try {
      const r = await fetchApi(apiUrl(`shop/bills/${billId}/document`), {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) {
        showToast(formatApiError(data) || "Bill PDF not ready yet");
        return;
      }
      if (data.document_url) window.open(data.document_url as string, "_blank");
    } catch {
      showToast("Could not open bill PDF");
    }
  }

  if (!token) {
    return (
      <section className="overflow-hidden rounded-3xl border border-jc-border/80 bg-jc-card shadow-jc-lg ring-1 ring-black/[0.04] lg:flex lg:min-h-[460px]">
        <div className="relative flex flex-col justify-center overflow-hidden bg-gradient-to-br from-jc-brand via-[#5a1a0a] to-jc-accent px-8 py-10 text-white lg:w-[42%] lg:shrink-0">
          <div className="relative z-10">
            <p className="text-xs font-semibold uppercase tracking-widest text-white/60">Dealer Portal</p>
            <h2 className="mt-3 font-display text-3xl font-semibold leading-tight sm:text-4xl">Welcome back</h2>
            <p className="mt-4 max-w-xs text-sm leading-relaxed text-white/85">
              Search by product name, add items to your order, and we confirm on WhatsApp.
            </p>
          </div>
        </div>
        <div className="flex flex-1 flex-col justify-center px-6 py-10 sm:px-10">
          <form onSubmit={onLogin} className="mx-auto w-full max-w-sm space-y-5">
            <label className="block text-sm font-medium text-jc-ink">
              Mobile number
              <input name="phone" data-testid="portal-phone" type="tel" inputMode="numeric" autoComplete="tel" required
                className="mt-2 w-full rounded-xl border border-jc-border bg-white px-4 py-3.5 text-sm shadow-sm outline-none transition focus:border-jc-brand focus:ring-2 focus:ring-jc-brand/15" />
            </label>
            <label className="block text-sm font-medium text-jc-ink">
              Password
              <input name="password" data-testid="portal-password" type="password" autoComplete="current-password" required
                className="mt-2 w-full rounded-xl border border-jc-border bg-white px-4 py-3.5 text-sm shadow-sm outline-none transition focus:border-jc-brand focus:ring-2 focus:ring-jc-brand/15" />
            </label>
            <button type="submit" disabled={loggingIn}
              className="w-full rounded-xl bg-jc-brand px-4 py-3.5 text-sm font-semibold text-white shadow-md transition hover:bg-jc-brand-light disabled:opacity-60">
              {loggingIn ? "Signing in…" : "Sign in"}
            </button>
            {loginMsg && <p className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">{loginMsg}</p>}
          </form>
        </div>
      </section>
    );
  }

  const displayName = displayCustomerName(profile);
  const city = profile?.city_name || profile?.city || "";

  return (
    <div className="space-y-5">
      {toast && (
        <div className="fixed bottom-5 left-1/2 z-[60] max-w-md -translate-x-1/2 rounded-2xl bg-jc-ink px-5 py-3 text-sm font-medium text-white shadow-lg">
          {toast}
        </div>
      )}

      {pendingBook && (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-4 sm:items-center">
          <div className="w-full max-w-sm rounded-2xl bg-white p-6 shadow-2xl">
            <h3 className="text-base font-bold text-jc-ink">Add to your order</h3>
            <p className="mt-1 text-sm text-jc-muted">
              <strong>{pendingBook.product.our_product_id}</strong> × {pendingBook.qty}
              {pendingBook.product.selling_price ? ` · ₹${pendingBook.product.selling_price} each` : ""}
            </p>
            <textarea
              autoFocus
              value={noteInput}
              onChange={(e) => setNoteInput(e.target.value)}
              placeholder="Optional note (bus, urgent…)"
              rows={2}
              className="mt-3 w-full rounded-xl border border-jc-border bg-jc-bg px-3 py-2 text-sm text-jc-ink placeholder-jc-muted focus:outline-none focus:ring-2 focus:ring-jc-brand"
            />
            <div className="mt-4 flex gap-3">
              <button
                type="button"
                disabled={!!bookingId}
                onClick={() => void confirmBook(noteInput)}
                className="flex-1 rounded-xl bg-jc-brand py-2.5 text-sm font-bold text-white transition hover:opacity-90 disabled:opacity-50"
              >
                {bookingId ? "Adding…" : "Confirm"}
              </button>
              <button
                type="button"
                onClick={() => setPendingBook(null)}
                className="rounded-xl border border-jc-border px-4 py-2.5 text-sm font-semibold text-jc-ink transition hover:bg-jc-bg"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="flex items-center justify-between rounded-2xl border border-jc-border/70 bg-white px-5 py-4 shadow-sm">
        <div>
          {profileLoading
            ? <div className="h-4 w-40 animate-pulse rounded bg-slate-200" />
            : <p className="font-semibold text-jc-ink">{displayName}</p>}
          {!profileLoading && city && (
            <p className="mt-0.5 text-xs text-jc-muted">{city}</p>
          )}
        </div>
        <button type="button" onClick={logout}
          className="rounded-xl border border-jc-border bg-white px-4 py-2 text-sm font-medium text-jc-muted transition hover:text-jc-ink">
          Sign out
        </button>
      </div>

      <div className="flex gap-2">
        <button type="button" onClick={() => setPortalTab("search")}
          className={`flex-1 rounded-xl py-3 text-sm font-semibold transition ${portalTab === "search" ? "bg-jc-brand text-white shadow-md" : "bg-white border border-jc-border text-jc-ink hover:bg-jc-bg"}`}>
          Search &amp; Order
        </button>
        <button type="button" onClick={() => setPortalTab("my_order")}
          className={`flex-1 rounded-xl py-3 text-sm font-semibold transition ${portalTab === "my_order" ? "bg-jc-brand text-white shadow-md" : "bg-white border border-jc-border text-jc-ink hover:bg-jc-bg"}`}>
          My Order{openLineCount > 0 ? ` (${openLineCount})` : ""}
        </button>
      </div>

      {portalTab === "search" ? (
        <div className="overflow-hidden rounded-3xl border border-jc-border/80 bg-jc-card shadow-jc-lg ring-1 ring-black/[0.03]">
          <div className="border-b border-jc-border/90 bg-gradient-to-br from-amber-50/90 via-white to-jc-bg-deep/60 px-5 py-6 sm:px-8">
            <h3 className="font-display text-2xl font-semibold text-jc-ink sm:text-[1.65rem]">Find products</h3>
            <p className="mt-1 text-sm text-jc-muted">
              Type the product name (code). One tap adds it to your open order — godown bills later.
            </p>
          </div>

          <div className="relative px-5 py-5 sm:px-8">
            <div className="flex gap-1 rounded-2xl border-2 border-jc-border bg-white p-1 shadow-sm transition focus-within:border-jc-brand focus-within:shadow-md focus-within:ring-4 focus-within:ring-jc-brand/10">
              <input
                value={shopQ}
                onChange={(e) => { setShopQ(e.target.value); setSuggestOpen(true); }}
                onFocus={() => setSuggestOpen(true)}
                onBlur={() => setTimeout(() => setSuggestOpen(false), 180)}
                onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void runSearch(); } }}
                placeholder="Product name / code — e.g. 9500"
                autoComplete="off"
                autoFocus
                className="min-w-0 flex-1 border-0 bg-transparent px-4 py-3 text-sm outline-none ring-0 placeholder:text-jc-muted/50"
              />
              <button type="button" onClick={() => void runSearch()} disabled={searching}
                className="shrink-0 rounded-xl bg-jc-brand px-5 py-2.5 text-sm font-semibold text-white shadow-md transition hover:bg-jc-brand-light disabled:opacity-50">
                {searching ? "…" : "Search"}
              </button>
            </div>
            {suggestOpen && suggestions.length > 0 && (
              <ul className="absolute left-5 right-5 top-full z-20 -mt-2 max-h-64 overflow-auto rounded-xl border border-jc-border bg-white py-1 shadow-jc-lg sm:left-8 sm:right-8">
                {suggestions.map((s) => (
                  <li key={s.catalog_product_id}>
                    <button type="button" className="flex w-full items-center justify-between gap-3 px-4 py-2.5 text-left text-sm hover:bg-jc-bg"
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => pickSuggest(s)}>
                      <span>
                        <span className="font-semibold text-jc-ink">{s.our_product_id}</span>
                        {s.category ? <span className="ml-2 text-xs text-jc-muted">{s.category}</span> : null}
                      </span>
                      <span className="shrink-0 text-xs tabular-nums text-jc-muted">
                        {s.selling_price && Number(s.selling_price) > 0 ? `₹${s.selling_price}` : ""}
                        {s.stock_status ? ` · ${stockLabel(s.stock_status)}` : ""}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {searchErr && <p className="mt-3 text-sm text-red-700">{searchErr}</p>}
            {bookErr && (
              <p className="mt-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">{bookErr}</p>
            )}
          </div>

          {!didSearch && !searching && (
            <div className="mx-5 mb-8 rounded-2xl border border-dashed border-jc-border/90 bg-jc-bg/40 px-6 py-10 text-center sm:mx-8">
              <p className="font-display text-lg font-semibold text-jc-ink">Start typing a product name</p>
              <p className="mt-2 text-sm text-jc-muted">Results appear as you type. Tap Add to order.</p>
            </div>
          )}

          {searching && results.length === 0 && (
            <div className="grid gap-4 px-5 pb-8 sm:grid-cols-2 sm:px-8">
              {[0, 1].map((i) => (
                <div key={i} className="h-64 animate-pulse rounded-3xl bg-jc-bg-deep/40" />
              ))}
            </div>
          )}

          {results.length > 0 && (
            <div className="grid gap-5 px-5 pb-8 sm:grid-cols-2 sm:px-8">
              {results.map((p) => {
                const priceOk = Number(p.selling_price) > 0;
                const canOrder = p.stock_status !== "out_of_stock" && priceOk;
                const busy = bookingId === p.catalog_product_id;
                const meta = [p.category, p.series, p.unit, p.year_group].filter(Boolean).join(" · ");
                const lineTotal = (Number(p.selling_price || 0) * Number(qtyDraft[p.catalog_product_id] || 1)).toFixed(2);
                return (
                  <article key={p.catalog_product_id}
                    className="flex flex-col overflow-hidden rounded-3xl border border-jc-border/90 bg-white shadow-jc ring-1 ring-black/[0.04]">
                    <div className="relative aspect-[4/3] w-full bg-gradient-to-b from-jc-bg-deep to-jc-bg/80">
                      {p.image_url ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={p.image_url} alt={p.our_product_id} className="h-full w-full object-contain p-3" />
                      ) : (
                        <div className="flex h-full items-center justify-center text-sm text-jc-muted">No photo</div>
                      )}
                      <span className={`absolute right-3 top-3 rounded-full px-3 py-1 text-xs font-semibold ring-1 ${stockPillClass(p.stock_status)}`}>
                        {stockLabel(p.stock_status)}
                      </span>
                    </div>
                    <div className="flex flex-1 flex-col gap-3 p-5">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <p className="font-display text-xl font-semibold text-jc-ink">{p.our_product_id}</p>
                          {meta ? <p className="mt-1 text-xs text-jc-muted">{meta}</p> : null}
                        </div>
                        <div className="text-right">
                          <span className="block text-[10px] font-semibold uppercase tracking-wider text-jc-muted">Your price</span>
                          <span className="text-xl font-bold tabular-nums text-jc-brand">
                            {priceOk ? `₹${p.selling_price}` : "—"}
                          </span>
                        </div>
                      </div>

                      {p.addons && p.addons.length > 0 && (
                        <div className="rounded-xl bg-jc-bg/70 px-3 py-2 text-xs text-jc-muted">
                          <span className="font-semibold text-jc-ink">Included: </span>
                          {p.addons.map((a) => `${a.name || a.our_product_id} ×${a.quantity}`).join(", ")}
                        </div>
                      )}

                      <div className="mt-auto flex flex-wrap items-end gap-3 border-t border-jc-border/60 pt-4">
                        <label className="block text-sm font-medium text-jc-ink">
                          Qty
                          <input type="number" min={1} max={MAX_QTY}
                            value={qtyDraft[p.catalog_product_id] ?? "1"}
                            onChange={(e) => setQtyDraft((prev) => ({ ...prev, [p.catalog_product_id]: e.target.value }))}
                            className="mt-1.5 w-24 rounded-xl border border-jc-border bg-jc-bg/30 px-3 py-2 text-sm"
                          />
                        </label>
                        <div className="flex-1 text-right text-xs text-jc-muted">
                          Line ≈ <span className="font-semibold text-jc-ink">₹{lineTotal}</span>
                        </div>
                        <button type="button" disabled={!canOrder || busy}
                          onClick={() => startBook(p, qtyDraft[p.catalog_product_id] ?? "1")}
                          className="w-full rounded-xl bg-jc-accent px-5 py-3 text-sm font-bold text-white shadow-md transition hover:bg-jc-accent-hover disabled:cursor-not-allowed disabled:bg-neutral-300 sm:w-auto">
                          {busy ? "Adding…" : canOrder ? "Add to order" : (priceOk ? "Out of stock" : "Price unavailable")}
                        </button>
                      </div>
                    </div>

                    {p.alternatives.length > 0 && (
                      <div className="border-t border-jc-border bg-jc-bg/50 px-5 py-4">
                        <p className="text-xs font-bold uppercase tracking-wide text-jc-muted">Alternatives in stock</p>
                        <ul className="mt-3 grid grid-cols-3 gap-2">
                          {p.alternatives.map((a) => (
                            <li key={a.catalog_product_id}>
                              <button type="button"
                                onClick={() => { setShopQ(a.our_product_id); void runSearch(a.our_product_id); }}
                                className="flex w-full flex-col overflow-hidden rounded-xl border border-jc-border bg-white p-2 text-left shadow-sm transition hover:border-jc-brand">
                                <div className="aspect-square w-full overflow-hidden rounded-lg bg-jc-bg-deep/40">
                                  {a.image_url ? (
                                    // eslint-disable-next-line @next/next/no-img-element
                                    <img src={a.image_url} alt="" className="h-full w-full object-contain p-1" />
                                  ) : (
                                    <div className="flex h-full min-h-[64px] items-center justify-center text-[10px] text-jc-muted">—</div>
                                  )}
                                </div>
                                <p className="mt-1.5 truncate text-center text-[11px] font-semibold text-jc-ink">{a.our_product_id}</p>
                                {a.selling_price ? (
                                  <p className="text-center text-[10px] tabular-nums text-jc-muted">₹{a.selling_price}</p>
                                ) : null}
                              </button>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </article>
                );
              })}
            </div>
          )}

          {didSearch && !searching && results.length === 0 && !searchErr && (
            <div className="mx-5 mb-8 rounded-2xl border border-jc-border bg-jc-bg/40 px-6 py-10 text-center sm:mx-8">
              <p className="font-display text-base font-semibold text-jc-ink">No matches</p>
              <p className="mt-2 text-sm text-jc-muted">Try another product name / code.</p>
            </div>
          )}
        </div>
      ) : (
        <div className="overflow-hidden rounded-3xl border border-jc-border/80 bg-white shadow-jc-lg">
          <div className="flex items-center justify-between border-b border-jc-border/60 bg-jc-bg/30 px-6 py-5">
            <div>
              <h3 className="font-display text-xl font-semibold text-jc-ink">My Order</h3>
              <p className="mt-0.5 text-xs text-jc-muted">Everything you add stays on one open order until billed.</p>
            </div>
            <button type="button" onClick={() => token && void loadMyOrders(token, statusFilter)}
              className="rounded-xl border border-jc-border bg-white px-4 py-2 text-xs font-semibold text-jc-muted transition hover:bg-jc-bg">
              Refresh
            </button>
          </div>
          <div className="p-6">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold uppercase tracking-wide text-jc-muted">Show</span>
              <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}
                className="rounded-xl border border-jc-border bg-white px-4 py-2 text-sm text-jc-ink shadow-sm">
                <option value="all">All lines</option>
                <option value="open">Open</option>
                <option value="partial">Partly billed</option>
                <option value="shipped">Billed</option>
              </select>
            </div>
            {ordersErr && <p className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">{ordersErr}</p>}
            {ordersLoading ? (
              <div className="mt-6 space-y-3">
                {[0, 1].map((i) => <div key={i} className="h-24 animate-pulse rounded-2xl bg-jc-bg-deep/30" />)}
              </div>
            ) : myOrders.length === 0 ? (
              <div className="mt-10 rounded-2xl border border-dashed border-jc-border bg-jc-bg/40 py-14 text-center">
                <p className="font-semibold text-jc-ink">No open order yet</p>
                <p className="mt-1 text-sm text-jc-muted">Search a product and tap Add to order.</p>
                <button type="button" onClick={() => setPortalTab("search")}
                  className="mt-4 rounded-xl bg-jc-brand px-5 py-2.5 text-sm font-semibold text-white">
                  Search products
                </button>
              </div>
            ) : (
              <ul className="mt-5 space-y-4">
                {myOrders.map((o) => (
                  <li key={o.id} className="overflow-hidden rounded-2xl border border-jc-border/80 bg-white shadow-sm">
                    <div className="flex flex-wrap items-center justify-between gap-2 border-l-4 border-jc-brand bg-jc-bg/30 px-5 py-4">
                      <div>
                        <span className="font-bold text-jc-ink">Order #{o.id}</span>
                        <span className="ml-2 text-xs text-jc-muted">{fmtDateTime(o.created_at)}</span>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className={`rounded-full px-3 py-1 text-xs font-bold ${orderBadgeClass(o.status)}`}>
                          {statusLabel(o.status)}
                        </span>
                        {o.has_order_document && (
                          <button type="button" onClick={() => void openOrderPdf(o.id)}
                            className="rounded-lg border border-jc-border bg-white px-3 py-1.5 text-xs font-medium text-jc-ink">
                            Order PDF
                          </button>
                        )}
                      </div>
                    </div>
                    <div className="divide-y divide-jc-border/50 px-5">
                      {o.items.map((it) => (
                        <div key={`${o.id}-${it.catalog_product_id}`} className="flex items-center gap-3 py-3 text-sm">
                          <div className="h-12 w-12 shrink-0 overflow-hidden rounded-lg border border-jc-border bg-jc-bg">
                            {imageMap[it.catalog_product_id] ? (
                              // eslint-disable-next-line @next/next/no-img-element
                              <img src={imageMap[it.catalog_product_id]} alt="" className="h-full w-full object-contain" />
                            ) : null}
                          </div>
                          <div className="min-w-0 flex-1">
                            <div className="font-semibold text-jc-ink">{it.our_product_id}</div>
                            {(it.category || it.name) && (
                              <div className="truncate text-xs text-jc-muted">{[it.category, it.name].filter(Boolean).join(" · ")}</div>
                            )}
                            {it.quantity_shipped ? (
                              <div className="text-xs text-sky-700">Billed {it.quantity_shipped}/{it.quantity}</div>
                            ) : null}
                          </div>
                          <div className="text-right">
                            <div className="tabular-nums text-jc-muted">× {it.quantity}</div>
                            <div className="font-semibold tabular-nums">₹{it.line_total}</div>
                            {it.bill_id && (
                              <button type="button" onClick={() => void openBillPdf(it.bill_id!)}
                                className="mt-1 text-[11px] font-medium text-jc-brand underline">
                                Bill {it.bill_number || it.bill_id}
                              </button>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                    <div className="flex items-center justify-between bg-jc-bg/20 px-5 py-3">
                      <span className="text-sm font-bold text-jc-ink">Total ₹{o.total_amount}</span>
                      {o.customer_notes && <span className="max-w-[55%] truncate text-xs text-jc-muted">Note: {o.customer_notes}</span>}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
