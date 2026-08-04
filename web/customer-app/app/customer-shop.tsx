"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiUrl, fetchApi, formatApiError } from "@/lib/api";
import type {
  CustomerPublic,
  ShopAccountPublic,
  ShopOrderCreateResponse,
  ShopOrderHistoryPublic,
  ShopProductPublic,
  ShopSuggestionPublic,
} from "@/lib/types";

function fmtDateTime(iso: string): string {
  try {
    const d = new Date(iso);
    return isNaN(d.getTime())
      ? iso
      : d.toLocaleString("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso;
  }
}

function fmtDate(iso: string): string {
  try {
    const d = new Date(iso.length <= 10 ? `${iso}T00:00:00` : iso);
    return isNaN(d.getTime())
      ? iso
      : d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
  } catch {
    return iso;
  }
}

function fmtMoney(v: string | null | undefined): string {
  if (v == null || v === "") return "—";
  const n = Number(v);
  if (!Number.isFinite(n)) return `₹${v}`;
  return `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

function dealerBadgeClass(status: string): string {
  if (status === "completed") return "bg-emerald-100 text-emerald-800";
  if (status === "partly_sent") return "bg-sky-100 text-sky-800";
  return "bg-amber-100 text-amber-800";
}

function dealerStatusLabel(s: string): string {
  return {
    ordered: "Ordered",
    partly_sent: "Partly sent",
    completed: "Completed",
  }[s] ?? s;
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

function displayCustomerName(profile: CustomerPublic | null, account: ShopAccountPublic | null): string {
  const p = account?.profile;
  if (p?.business_name) return p.business_name;
  if (!profile) return "—";
  return profile.business_name || profile.company_name || profile.person_name || profile.name || "—";
}

function digitsPhone(raw: string): string {
  return raw.replace(/\D+/g, "").slice(-10);
}

const MAX_QTY = 100_000_000;

type PortalTab = "order" | "account";
type AccountView = "hub" | "orders";

export default function CustomerPortalPage() {
  const [loginMsg, setLoginMsg] = useState("");
  const [loggingIn, setLoggingIn] = useState(false);
  const [profile, setProfile] = useState<CustomerPublic | null>(null);
  const [profileLoading, setProfileLoading] = useState(false);
  const [token, setToken] = useState<string | null>(null);
  const [portalTab, setPortalTab] = useState<PortalTab>("order");
  const [accountView, setAccountView] = useState<AccountView>("hub");

  const [account, setAccount] = useState<ShopAccountPublic | null>(null);
  const [accountLoading, setAccountLoading] = useState(false);
  const [accountErr, setAccountErr] = useState("");

  const [history, setHistory] = useState<ShopOrderHistoryPublic[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyErr, setHistoryErr] = useState("");

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

  const loadAccount = useCallback(async (t: string) => {
    setAccountErr("");
    setAccountLoading(true);
    try {
      const r = await fetchApi(apiUrl("shop/account"), { headers: { Authorization: `Bearer ${t}` } });
      const data = await r.json().catch(() => null);
      if (!r.ok) {
        setAccountErr(formatApiError(data) || r.statusText);
        setAccount(null);
        return;
      }
      setAccount(data as ShopAccountPublic);
    } finally {
      setAccountLoading(false);
    }
  }, []);

  const loadHistory = useCallback(async (t: string) => {
    setHistoryErr("");
    setHistoryLoading(true);
    try {
      const r = await fetchApi(apiUrl("shop/orders/history"), { headers: { Authorization: `Bearer ${t}` } });
      const data = await r.json().catch(() => null);
      if (!r.ok) {
        setHistoryErr(formatApiError(data) || r.statusText);
        setHistory([]);
        return;
      }
      setHistory(Array.isArray(data) ? (data as ShopOrderHistoryPublic[]) : []);
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  useEffect(() => {
    try {
      const t = sessionStorage.getItem("token");
      if (t) {
        setToken(t);
        void loadMe(t);
        void loadAccount(t);
      }
    } catch {
      /* ignore */
    }
  }, [loadMe, loadAccount]);

  useEffect(() => {
    if (!token || portalTab !== "account") return;
    void loadAccount(token);
    if (accountView === "orders") void loadHistory(token);
  }, [token, portalTab, accountView, loadAccount, loadHistory]);

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
      await loadAccount(t);
    } finally {
      setLoggingIn(false);
    }
  }

  function logout() {
    try {
      sessionStorage.removeItem("token");
    } catch {
      /* ignore */
    }
    setToken(null);
    setProfile(null);
    setAccount(null);
    setHistory([]);
    setLoginMsg("");
    setShopQ("");
    setResults([]);
    setSuggestions([]);
    setDidSearch(false);
    setPortalTab("order");
    setAccountView("hub");
  }

  const runSearch = useCallback(
    async (qRaw?: string) => {
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
      } finally {
        if (seq === searchSeq.current) setSearching(false);
      }
    },
    [token, shopQ],
  );

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
    return () => {
      if (suggestTimer.current) clearTimeout(suggestTimer.current);
    };
  }, [shopQ, token]);

  useEffect(() => {
    const qn = normalizeQ(shopQ);
    if (!token || qn.length < 1) return;
    if (searchTimer.current) clearTimeout(searchTimer.current);
    searchTimer.current = setTimeout(() => {
      void runSearch(qn);
    }, 280);
    return () => {
      if (searchTimer.current) clearTimeout(searchTimer.current);
    };
  }, [shopQ, token, runSearch]);

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
              <input
                name="phone"
                data-testid="portal-phone"
                type="tel"
                inputMode="numeric"
                autoComplete="tel"
                required
                className="mt-2 w-full rounded-xl border border-jc-border bg-white px-4 py-3.5 text-sm shadow-sm outline-none transition focus:border-jc-brand focus:ring-2 focus:ring-jc-brand/15"
              />
            </label>
            <label className="block text-sm font-medium text-jc-ink">
              Password
              <input
                name="password"
                data-testid="portal-password"
                type="password"
                autoComplete="current-password"
                required
                className="mt-2 w-full rounded-xl border border-jc-border bg-white px-4 py-3.5 text-sm shadow-sm outline-none transition focus:border-jc-brand focus:ring-2 focus:ring-jc-brand/15"
              />
            </label>
            <button
              type="submit"
              disabled={loggingIn}
              className="w-full rounded-xl bg-jc-brand px-4 py-3.5 text-sm font-semibold text-white shadow-md transition hover:bg-jc-brand-light disabled:opacity-60"
            >
              {loggingIn ? "Signing in…" : "Sign in"}
            </button>
            {loginMsg && <p className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">{loginMsg}</p>}
          </form>
        </div>
      </section>
    );
  }

  const displayName = displayCustomerName(profile, account);
  const city = account?.profile.city_name || profile?.city_name || profile?.city || "";
  const money = account?.money;

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

      <div className="rounded-2xl border border-jc-border/70 bg-white px-5 py-4 shadow-sm">
        <div className="flex items-center justify-between gap-3">
          <div>
            {profileLoading && !account ? (
              <div className="h-4 w-40 animate-pulse rounded bg-slate-200" />
            ) : (
              <p className="font-semibold text-jc-ink">{displayName}</p>
            )}
            {city && <p className="mt-0.5 text-xs text-jc-muted">{city}</p>}
          </div>
          <button
            type="button"
            onClick={logout}
            className="rounded-xl border border-jc-border bg-white px-4 py-2 text-sm font-medium text-jc-muted transition hover:text-jc-ink"
          >
            Sign out
          </button>
        </div>
        {(money || accountLoading) && (
          <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 border-t border-jc-border/50 pt-3 text-sm">
            <p>
              <span className="text-jc-muted">Pending </span>
              <span className="font-semibold tabular-nums text-jc-ink">
                {accountLoading && !money ? "…" : fmtMoney(money?.pending)}
              </span>
            </p>
            <p>
              <span className="text-jc-muted">Remaining limit </span>
              <span className="font-semibold tabular-nums text-jc-ink">
                {accountLoading && !money
                  ? "…"
                  : money?.unlimited
                    ? "Unlimited"
                    : fmtMoney(money?.remaining_limit)}
              </span>
            </p>
          </div>
        )}
      </div>

      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => setPortalTab("order")}
          className={`flex-1 rounded-xl py-3 text-sm font-semibold transition ${
            portalTab === "order" ? "bg-jc-brand text-white shadow-md" : "border border-jc-border bg-white text-jc-ink hover:bg-jc-bg"
          }`}
        >
          Order
        </button>
        <button
          type="button"
          onClick={() => {
            setPortalTab("account");
            setAccountView("hub");
          }}
          className={`flex-1 rounded-xl py-3 text-sm font-semibold transition ${
            portalTab === "account" ? "bg-jc-brand text-white shadow-md" : "border border-jc-border bg-white text-jc-ink hover:bg-jc-bg"
          }`}
        >
          My Account
        </button>
      </div>

      {portalTab === "order" ? (
        <div className="overflow-hidden rounded-3xl border border-jc-border/80 bg-jc-card shadow-jc-lg ring-1 ring-black/[0.03]">
          <div className="border-b border-jc-border/90 bg-gradient-to-br from-amber-50/90 via-white to-jc-bg-deep/60 px-5 py-6 sm:px-8">
            <h3 className="font-display text-2xl font-semibold text-jc-ink sm:text-[1.65rem]">Find products</h3>
            <p className="mt-1 text-sm text-jc-muted">Type the product name (code). One tap adds it to your order — godown bills later.</p>
          </div>

          <div className="relative px-5 py-5 sm:px-8">
            <div className="flex gap-1 rounded-2xl border-2 border-jc-border bg-white p-1 shadow-sm transition focus-within:border-jc-brand focus-within:shadow-md focus-within:ring-4 focus-within:ring-jc-brand/10">
              <input
                value={shopQ}
                onChange={(e) => {
                  setShopQ(e.target.value);
                  setSuggestOpen(true);
                }}
                onFocus={() => setSuggestOpen(true)}
                onBlur={() => setTimeout(() => setSuggestOpen(false), 180)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    void runSearch();
                  }
                }}
                placeholder="Product name / code — e.g. 9500"
                autoComplete="off"
                autoFocus
                className="min-w-0 flex-1 border-0 bg-transparent px-4 py-3 text-sm outline-none ring-0 placeholder:text-jc-muted/50"
              />
              <button
                type="button"
                onClick={() => void runSearch()}
                disabled={searching}
                className="shrink-0 rounded-xl bg-jc-brand px-5 py-2.5 text-sm font-semibold text-white shadow-md transition hover:bg-jc-brand-light disabled:opacity-50"
              >
                {searching ? "…" : "Search"}
              </button>
            </div>
            {suggestOpen && suggestions.length > 0 && (
              <ul className="absolute left-5 right-5 top-full z-20 -mt-2 max-h-64 overflow-auto rounded-xl border border-jc-border bg-white py-1 shadow-jc-lg sm:left-8 sm:right-8">
                {suggestions.map((s) => (
                  <li key={s.catalog_product_id}>
                    <button
                      type="button"
                      className="flex w-full items-center justify-between gap-3 px-4 py-2.5 text-left text-sm hover:bg-jc-bg"
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => pickSuggest(s)}
                    >
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
            {bookErr && <p className="mt-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">{bookErr}</p>}
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
                  <article
                    key={p.catalog_product_id}
                    className="flex flex-col overflow-hidden rounded-3xl border border-jc-border/90 bg-white shadow-jc ring-1 ring-black/[0.04]"
                  >
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
                          <span className="text-xl font-bold tabular-nums text-jc-brand">{priceOk ? `₹${p.selling_price}` : "—"}</span>
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
                          <input
                            type="number"
                            min={1}
                            max={MAX_QTY}
                            value={qtyDraft[p.catalog_product_id] ?? "1"}
                            onChange={(e) => setQtyDraft((prev) => ({ ...prev, [p.catalog_product_id]: e.target.value }))}
                            className="mt-1.5 w-24 rounded-xl border border-jc-border bg-jc-bg/30 px-3 py-2 text-sm"
                          />
                        </label>
                        <div className="flex-1 text-right text-xs text-jc-muted">
                          Line ≈ <span className="font-semibold text-jc-ink">₹{lineTotal}</span>
                        </div>
                        <button
                          type="button"
                          disabled={!canOrder || busy}
                          onClick={() => startBook(p, qtyDraft[p.catalog_product_id] ?? "1")}
                          className="w-full rounded-xl bg-jc-accent px-5 py-3 text-sm font-bold text-white shadow-md transition hover:bg-jc-accent-hover disabled:cursor-not-allowed disabled:bg-neutral-300 sm:w-auto"
                        >
                          {busy ? "Adding…" : canOrder ? "Add to order" : priceOk ? "Out of stock" : "Price unavailable"}
                        </button>
                      </div>
                    </div>

                    {p.alternatives.length > 0 && (
                      <div className="border-t border-jc-border bg-jc-bg/50 px-5 py-4">
                        <p className="text-xs font-bold uppercase tracking-wide text-jc-muted">Alternatives in stock</p>
                        <ul className="mt-3 grid grid-cols-3 gap-2">
                          {p.alternatives.map((a) => (
                            <li key={a.catalog_product_id}>
                              <button
                                type="button"
                                onClick={() => {
                                  setShopQ(a.our_product_id);
                                  void runSearch(a.our_product_id);
                                }}
                                className="flex w-full flex-col overflow-hidden rounded-xl border border-jc-border bg-white p-2 text-left shadow-sm transition hover:border-jc-brand"
                              >
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
      ) : accountView === "orders" ? (
        <div className="overflow-hidden rounded-3xl border border-jc-border/80 bg-white shadow-jc-lg">
          <div className="flex items-center justify-between gap-2 border-b border-jc-border/60 bg-jc-bg/30 px-5 py-4">
            <button
              type="button"
              onClick={() => setAccountView("hub")}
              className="rounded-lg px-2 py-1.5 text-sm font-semibold text-jc-brand transition hover:bg-jc-bg"
            >
              ‹ Account
            </button>
            <h3 className="font-display text-lg font-semibold text-jc-ink">My orders</h3>
            <button
              type="button"
              onClick={() => token && void loadHistory(token)}
              className="rounded-xl border border-jc-border bg-white px-3 py-1.5 text-xs font-semibold text-jc-muted transition hover:bg-jc-bg"
            >
              Refresh
            </button>
          </div>
          <div className="p-5">
            {historyErr && <p className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">{historyErr}</p>}
            {historyLoading ? (
              <div className="space-y-3">
                {[0, 1].map((i) => (
                  <div key={i} className="h-28 animate-pulse rounded-2xl bg-jc-bg-deep/30" />
                ))}
              </div>
            ) : history.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-jc-border bg-jc-bg/40 py-14 text-center">
                <p className="font-semibold text-jc-ink">No orders yet</p>
                <p className="mt-1 text-sm text-jc-muted">Place your first order from the Order tab.</p>
                <button
                  type="button"
                  onClick={() => setPortalTab("order")}
                  className="mt-4 rounded-xl bg-jc-brand px-5 py-2.5 text-sm font-semibold text-white"
                >
                  Order products
                </button>
              </div>
            ) : (
              <ul className="space-y-4">
                {history.map((o) => {
                  const billIds = [...new Set(o.lines.filter((l) => l.bill_id).map((l) => l.bill_id!))];
                  const lineSummary = o.lines.map((l) => `${l.our_product_id} × ${l.quantity}`).join(" · ");
                  return (
                    <li key={o.id} className="overflow-hidden rounded-2xl border border-jc-border/80 bg-white shadow-sm">
                      <div className="flex flex-wrap items-center justify-between gap-2 border-l-4 border-jc-brand bg-jc-bg/30 px-5 py-4">
                        <div>
                          <span className="font-bold text-jc-ink">Order #{o.id}</span>
                          <span className="ml-2 text-xs text-jc-muted">{fmtDateTime(o.placed_at)}</span>
                        </div>
                        <span className={`rounded-full px-3 py-1 text-xs font-bold ${dealerBadgeClass(o.status)}`}>
                          {dealerStatusLabel(o.status)}
                        </span>
                      </div>
                      <div className="space-y-3 px-5 py-4">
                        <p className="text-sm text-jc-ink">{lineSummary}</p>
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <span className="text-sm font-bold tabular-nums text-jc-ink">₹{o.total_amount}</span>
                          <div className="flex flex-wrap gap-2">
                            {o.has_order_document && (
                              <button
                                type="button"
                                onClick={() => void openOrderPdf(o.id)}
                                className="rounded-lg border border-jc-border bg-white px-3 py-1.5 text-xs font-medium text-jc-ink"
                              >
                                Download order
                              </button>
                            )}
                            {billIds.map((bid) => {
                              const bn = o.lines.find((l) => l.bill_id === bid)?.bill_number;
                              return (
                                <button
                                  key={bid}
                                  type="button"
                                  onClick={() => void openBillPdf(bid)}
                                  className="rounded-lg border border-jc-border bg-white px-3 py-1.5 text-xs font-medium text-jc-ink"
                                >
                                  Download bill{bn ? ` ${bn}` : ""}
                                </button>
                              );
                            })}
                          </div>
                        </div>
                        {o.customer_notes && <p className="text-xs text-jc-muted">Note: {o.customer_notes}</p>}
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>
      ) : (
        <div className="overflow-hidden rounded-3xl border border-jc-border/80 bg-white shadow-jc-lg">
          <div className="flex items-center justify-between border-b border-jc-border/60 bg-jc-bg/30 px-6 py-5">
            <h3 className="font-display text-xl font-semibold text-jc-ink">My Account</h3>
            <button
              type="button"
              onClick={() => token && void loadAccount(token)}
              className="rounded-xl border border-jc-border bg-white px-4 py-2 text-xs font-semibold text-jc-muted transition hover:bg-jc-bg"
            >
              Refresh
            </button>
          </div>
          <div className="space-y-6 p-6">
            {accountErr && <p className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">{accountErr}</p>}

            <button
              type="button"
              onClick={() => setAccountView("orders")}
              className="flex w-full items-center justify-between rounded-2xl border border-jc-border bg-jc-bg/40 px-5 py-4 text-left transition hover:border-jc-brand hover:bg-jc-bg"
            >
              <div>
                <p className="font-semibold text-jc-ink">My orders</p>
                <p className="mt-0.5 text-xs text-jc-muted">See all orders, bills &amp; receipts</p>
              </div>
              <span className="text-lg text-jc-muted">›</span>
            </button>

            {accountLoading && !account ? (
              <div className="grid grid-cols-2 gap-4">
                {[0, 1, 2, 3].map((i) => (
                  <div key={i} className="h-16 animate-pulse rounded-xl bg-jc-bg-deep/30" />
                ))}
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-jc-muted">Pending</p>
                  <p className="mt-1 text-2xl font-bold tabular-nums text-jc-ink">{fmtMoney(money?.pending)}</p>
                </div>
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-jc-muted">Paid</p>
                  <p className="mt-1 text-2xl font-bold tabular-nums text-jc-ink">{fmtMoney(money?.paid)}</p>
                </div>
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-jc-muted">Limit</p>
                  <p className="mt-1 text-2xl font-bold tabular-nums text-jc-ink">
                    {money?.unlimited ? "Unlimited" : fmtMoney(money?.credit_limit)}
                  </p>
                </div>
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-jc-muted">Remaining</p>
                  <p className="mt-1 text-2xl font-bold tabular-nums text-jc-ink">
                    {money?.unlimited ? "Unlimited" : fmtMoney(money?.remaining_limit)}
                  </p>
                </div>
              </div>
            )}

            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-jc-muted">Money activity</p>
              {!account?.ledger?.length ? (
                <p className="mt-3 text-sm text-jc-muted">No bills or payments yet.</p>
              ) : (
                <ul className="mt-3 divide-y divide-jc-border/60">
                  {account.ledger.slice(0, 40).map((e) => {
                    const signed = Number(e.signed_amount);
                    const plus = signed >= 0;
                    return (
                      <li key={e.id} className="flex items-start justify-between gap-3 py-3 text-sm">
                        <div className="min-w-0">
                          <p className="text-xs text-jc-muted">{fmtDate(e.date)}</p>
                          <p className="font-medium text-jc-ink">
                            {e.label}
                            {e.payment_ref ? ` · ${e.payment_ref}` : ""}
                            {e.description ? ` · ${e.description}` : ""}
                          </p>
                        </div>
                        <span className={`shrink-0 font-semibold tabular-nums ${plus ? "text-amber-800" : "text-emerald-700"}`}>
                          {plus ? "+" : "−"}
                          {fmtMoney(String(Math.abs(signed)))}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>

            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-jc-muted">Your details</p>
              {account?.profile ? (
                <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
                  <div>
                    <dt className="text-jc-muted">Business</dt>
                    <dd className="font-medium text-jc-ink">{account.profile.business_name || "—"}</dd>
                  </div>
                  <div>
                    <dt className="text-jc-muted">Person</dt>
                    <dd className="font-medium text-jc-ink">{account.profile.person_name || "—"}</dd>
                  </div>
                  <div>
                    <dt className="text-jc-muted">Phone</dt>
                    <dd className="font-medium text-jc-ink">{account.profile.phone || "—"}</dd>
                  </div>
                  {account.profile.secondary_phone && (
                    <div>
                      <dt className="text-jc-muted">Alt phone</dt>
                      <dd className="font-medium text-jc-ink">{account.profile.secondary_phone}</dd>
                    </div>
                  )}
                  <div>
                    <dt className="text-jc-muted">City</dt>
                    <dd className="font-medium text-jc-ink">{account.profile.city_name || "—"}</dd>
                  </div>
                  {account.profile.route_name && (
                    <div>
                      <dt className="text-jc-muted">Route</dt>
                      <dd className="font-medium text-jc-ink">{account.profile.route_name}</dd>
                    </div>
                  )}
                  <div className="sm:col-span-2">
                    <dt className="text-jc-muted">Address</dt>
                    <dd className="font-medium text-jc-ink">{account.profile.address || "—"}</dd>
                  </div>
                  <div>
                    <dt className="text-jc-muted">GST</dt>
                    <dd className="font-medium text-jc-ink">{account.profile.gst_number || "—"}</dd>
                  </div>
                </dl>
              ) : (
                <p className="mt-3 text-sm text-jc-muted">Loading…</p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
