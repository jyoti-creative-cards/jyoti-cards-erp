"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiUrl, fetchApi, formatApiError } from "@/lib/api";
import type {
  CustomerOrderPublic,
  CustomerPublic,
  ShopProductPublic,
  ShopSuggestionPublic,
} from "@/lib/types";

type PortalTab = "availability" | "order_now" | "my_orders";

/** Customer-facing: can they rely on us having units? */
function availabilityLine(s: string): { title: string; hint: string } {
  if (s === "in_stock")
    return { title: "In stock with us", hint: "We have this product available now." };
  if (s === "low_stock")
    return {
      title: "Limited stock",
      hint: "We still have units, but quantity is running low.",
    };
  if (s === "out_of_stock")
    return { title: "Not in stock right now", hint: "We do not have available units at the moment." };
  return { title: "Unknown", hint: "" };
}

function orderBadgeClass(status: string): string {
  if (status === "shipped") return "bg-blue-100 text-blue-900";
  if (status === "billed") return "bg-purple-100 text-purple-900";
  if (status === "confirmed") return "bg-indigo-100 text-indigo-900";
  if (status === "cancelled") return "bg-neutral-200 text-neutral-800";
  return "bg-amber-100 text-amber-900";
}

function statusBadge(status: string): string {
  const m: Record<string, string> = {
    confirmed: "Confirmed",
    billed: "Billed",
    shipped: "Shipped",
    cancelled: "Cancelled",
  };
  return m[status] ?? status;
}

function fmtTs(iso: string): string {
  try {
    const d = new Date(iso);
    return isNaN(d.getTime()) ? iso : d.toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" });
  } catch {
    return iso;
  }
}

/** Cart qty cap when exact stock is not exposed in the shop UI (server still validates). */
const MAX_ORDER_QTY = 100_000_000;

function stockPillClass(status: string): string {
  if (status === "in_stock") return "bg-emerald-100 text-emerald-900 ring-emerald-200/70";
  if (status === "low_stock") return "bg-amber-100 text-amber-900 ring-amber-200/70";
  if (status === "out_of_stock") return "bg-stone-100 text-stone-600 ring-stone-200/70";
  return "bg-stone-100 text-stone-700 ring-stone-200/70";
}

/** Trim fancy spaces / NBSP so SKU search matches the catalogue. */
function normalizeShopQuery(s: string): string {
  return s.replace(/\u00a0/g, " ").trim().replace(/\s+/g, " ");
}

function profileInitials(name: string | undefined): string {
  const n = (name ?? "").trim();
  if (!n) return "JC";
  const parts = n.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) {
    const a = parts[0]?.[0];
    const b = parts[parts.length - 1]?.[0];
    if (a && b) return (a + b).toUpperCase();
  }
  return n.slice(0, 2).toUpperCase();
}

function ShopTab(props: {
  active: boolean;
  onClick: () => void;
  icon: string;
  title: string;
  subtitle: string;
  badge?: number;
  "data-testid"?: string;
}) {
  const { active, onClick, icon, title, subtitle, badge, "data-testid": dataTestId } = props;
  return (
    <button
      type="button"
      data-testid={dataTestId}
      onClick={onClick}
      className={`flex min-h-[4.5rem] w-full snap-start items-center gap-3 rounded-2xl border px-3 py-3 text-left shadow-sm transition sm:min-h-0 sm:flex-1 sm:px-4 ${
        active
          ? "border-jc-brand/40 bg-jc-brand text-white shadow-md ring-2 ring-jc-brand/25"
          : "border-jc-border bg-white text-jc-ink hover:border-jc-brand/30 hover:bg-jc-bg hover:shadow"
      }`}
    >
      <span className="text-2xl leading-none" aria-hidden>
        {icon}
      </span>
      <span className="min-w-0 flex-1">
        <span className={`block text-sm font-semibold ${active ? "text-white" : "text-jc-ink"}`}>{title}</span>
        <span className={`mt-0.5 block truncate text-xs ${active ? "text-white/85" : "text-jc-muted"}`}>
          {subtitle}
        </span>
      </span>
      {badge != null && badge > 0 ? (
        <span
          className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-bold tabular-nums ${
            active ? "bg-white/25 text-white" : "bg-jc-brand/10 text-jc-brand"
          }`}
        >
          {badge}
        </span>
      ) : null}
    </button>
  );
}

export default function CustomerPortalPage() {
  const [msg, setMsg] = useState("");
  const [ok, setOk] = useState("");
  const [profile, setProfile] = useState<CustomerPublic | null>(null);
  const [token, setToken] = useState<string | null>(null);

  const [portalTab, setPortalTab] = useState<PortalTab>("availability");

  const [shopQ, setShopQ] = useState("");
  const [shopSuggestions, setShopSuggestions] = useState<ShopSuggestionPublic[]>([]);
  const [shopSuggestOpen, setShopSuggestOpen] = useState(false);
  const [shopResults, setShopResults] = useState<ShopProductPublic[]>([]);
  const [shopLoading, setShopLoading] = useState(false);
  const [shopErr, setShopErr] = useState("");
  const [shopDidSearch, setShopDidSearch] = useState(false);
  const suggestTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [cart, setCart] = useState<Record<number, { p: ShopProductPublic; qty: number }>>({});
  const [qtyDraft, setQtyDraft] = useState<Record<number, string>>({});
  const [orderMsg, setOrderMsg] = useState("");
  const [orderSubmitting, setOrderSubmitting] = useState(false);
  const [orderNotes, setOrderNotes] = useState("");

  const [myOrders, setMyOrders] = useState<CustomerOrderPublic[]>([]);
  const [ordersLoading, setOrdersLoading] = useState(false);
  const [ordersErr, setOrdersErr] = useState("");
  const [orderStatusFilter, setOrderStatusFilter] = useState<string>("");

  const loadMe = useCallback(async (t: string) => {
    const r = await fetchApi(apiUrl("auth/me"), { headers: { Authorization: `Bearer ${t}` } });
    const me = await r.json().catch(() => null);
    if (r.ok && me) setProfile(me as CustomerPublic);
    else setProfile(null);
  }, []);

  const [confirmBusyId, setConfirmBusyId] = useState<number | null>(null);

  async function confirmReceived(orderId: number) {
    if (!token) return;
    setOrdersErr("");
    setConfirmBusyId(orderId);
    try {
      const r = await fetchApi(apiUrl(`shop/orders/${orderId}/confirm-delivery`), {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) {
        setOrdersErr(formatApiError(data) || r.statusText);
        return;
      }
      void loadMyOrders(token, orderStatusFilter);
    } finally {
      setConfirmBusyId(null);
    }
  }

  const loadMyOrders = useCallback(async (t: string, statusFilter?: string) => {
    setOrdersErr("");
    setOrdersLoading(true);
    try {
      const sf = (statusFilter ?? "").trim();
      const qs =
        sf && sf !== "all" ? `?${new URLSearchParams({ status: sf }).toString()}` : "";
      const r = await fetchApi(apiUrl(`shop/orders${qs}`), { headers: { Authorization: `Bearer ${t}` } });
      const data = await r.json().catch(() => null);
      if (!r.ok) {
        setOrdersErr(formatApiError(data) || r.statusText);
        setMyOrders([]);
        return;
      }
      setMyOrders(Array.isArray(data) ? (data as CustomerOrderPublic[]) : []);
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
      }
    } catch {
      /* ignore */
    }
  }, [loadMe]);

  useEffect(() => {
    if (!token || portalTab !== "my_orders") return;
    void loadMyOrders(token, orderStatusFilter);
  }, [token, portalTab, orderStatusFilter, loadMyOrders]);

  useEffect(() => {
    const qn = normalizeShopQuery(shopQ);
    if (!token || qn.length < 1) {
      setShopSuggestions([]);
      return;
    }
    if (suggestTimer.current) clearTimeout(suggestTimer.current);
    suggestTimer.current = setTimeout(async () => {
      const r = await fetchApi(
        apiUrl(`shop/products/suggestions?q=${encodeURIComponent(qn)}`),
        { headers: { Authorization: `Bearer ${token}` } },
      );
      const data = await r.json().catch(() => []);
      if (!r.ok) {
        setShopSuggestions([]);
        return;
      }
      setShopSuggestions(Array.isArray(data) ? (data as ShopSuggestionPublic[]) : []);
    }, 220);
    return () => {
      if (suggestTimer.current) clearTimeout(suggestTimer.current);
    };
  }, [shopQ, token]);

  const runSearch = useCallback(async () => {
    setShopErr("");
    setShopResults([]);
    if (!token) return;
    const q = normalizeShopQuery(shopQ);
    if (q.length < 1) {
      setShopErr("Please enter an item code or product name to search.");
      return;
    }
    setShopLoading(true);
    try {
      const p = new URLSearchParams();
      p.set("q", q);
      const r = await fetchApi(apiUrl(`shop/products/search?${p}`), {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await r.json().catch(() => null);
      if (!r.ok) {
        setShopErr(formatApiError(data) || r.statusText);
        return;
      }
      setShopResults(Array.isArray(data) ? (data as ShopProductPublic[]) : []);
      setShopDidSearch(true);
      setQtyDraft((prev) => {
        const next = { ...prev };
        for (const row of Array.isArray(data) ? data : []) {
          const prod = row as ShopProductPublic;
          if (next[prod.catalog_product_id] === undefined) next[prod.catalog_product_id] = "1";
        }
        return next;
      });
    } finally {
      setShopLoading(false);
    }
  }, [token, shopQ]);

  function addProductToCart(p: ShopProductPublic, qtyStr: string) {
    if (p.stock_status === "out_of_stock") {
      setOrderMsg("This item isn’t available to add right now.");
      return;
    }
    const n = Math.floor(Number(qtyStr));
    const addQty = Number.isFinite(n) ? Math.max(1, Math.min(n, MAX_ORDER_QTY)) : 1;
    setOrderMsg("");
    setCart((prev) => {
      const existing = prev[p.catalog_product_id];
      const merged = (existing?.qty ?? 0) + addQty;
      const q = Math.min(Math.max(1, merged), MAX_ORDER_QTY);
      return {
        ...prev,
        [p.catalog_product_id]: { p, qty: q },
      };
    });
  }

  function setQtyDraftFor(pid: number, s: string) {
    setQtyDraft((prev) => ({ ...prev, [pid]: s }));
  }

  function setLineQty(catalogProductId: number, qtyStr: string) {
    const row = cart[catalogProductId];
    if (!row) return;
    const n = Math.floor(Number(qtyStr));
    const q = Number.isFinite(n) ? Math.max(1, Math.min(n, MAX_ORDER_QTY)) : 1;
    setCart((prev) => ({
      ...prev,
      [catalogProductId]: { ...row, qty: q },
    }));
  }

  function removeLine(catalogProductId: number) {
    setCart((prev) => {
      const next = { ...prev };
      delete next[catalogProductId];
      return next;
    });
  }

  async function placeOrder() {
    setOrderMsg("");
    if (!token) return;
    const lines = Object.values(cart).map((row) => ({
      catalog_product_id: row.p.catalog_product_id,
      quantity: row.qty,
    }));
    if (lines.length < 1) {
      setOrderMsg("Add at least one item to your bag first.");
      return;
    }
    setOrderSubmitting(true);
    try {
      const r = await fetchApi(apiUrl("shop/orders"), {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ lines, customer_notes: orderNotes.trim() || null }),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) {
        setOrderMsg(formatApiError(data) || r.statusText);
        return;
      }
      setCart({});
      setOrderNotes("");
      setOrderMsg(`Order #${(data as CustomerOrderPublic).id} confirmed! We’ll message you on WhatsApp shortly.`);
      void loadMyOrders(token, orderStatusFilter);
      setPortalTab("my_orders");
    } finally {
      setOrderSubmitting(false);
    }
  }

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setMsg("");
    setOk("");
    setProfile(null);
    const fd = new FormData(e.currentTarget);
    const phone = String(fd.get("phone") || "");
    const password = String(fd.get("password") || "");

    const r = await fetchApi(apiUrl("auth/login"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phone, password }),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) {
      setMsg(formatApiError(data) || r.statusText);
      return;
    }
    const t = data.access_token as string;
    sessionStorage.setItem("token", t);
    setToken(t);
    setOk("Welcome — you're signed in.");
    await loadMe(t);
  }

  function logout() {
    try {
      sessionStorage.removeItem("token");
    } catch {
      /* ignore */
    }
    setToken(null);
    setProfile(null);
    setOk("");
    setShopQ("");
    setShopResults([]);
    setShopSuggestions([]);
    setShopDidSearch(false);
    setCart({});
    setMyOrders([]);
    setPortalTab("availability");
  }

  function pickSuggestion(s: ShopSuggestionPublic) {
    setShopQ(s.our_product_id);
    setShopSuggestOpen(false);
    setShopSuggestions([]);
  }

  const cartLines = Object.values(cart);
  const cartTotal = cartLines.reduce((sum, row) => {
    const unit = parseFloat(row.p.selling_price || "0") || 0;
    return sum + unit * row.qty;
  }, 0);

  return (
    <div className="mx-auto max-w-6xl space-y-8 pb-6 sm:pb-2">
      {!token ? (
        <section className="overflow-hidden rounded-3xl border border-jc-border/80 bg-jc-card shadow-jc-lg ring-1 ring-black/[0.04] lg:flex lg:min-h-[440px]">
          <div className="relative flex flex-col justify-center overflow-hidden bg-gradient-to-br from-jc-brand via-[#5a1a0a] to-jc-accent px-8 py-10 text-white lg:w-[44%] lg:shrink-0">
            <div
              className="pointer-events-none absolute -right-16 -top-16 h-48 w-48 rounded-full bg-white/10 blur-2xl"
              aria-hidden
            />
            <div
              className="pointer-events-none absolute -bottom-20 -left-10 h-56 w-56 rounded-full bg-black/20 blur-2xl"
              aria-hidden
            />
            <div className="relative z-10">
              <p className="text-xs font-semibold uppercase tracking-[0.25em] text-white/70">Customer shop</p>
              <h2 className="mt-3 font-display text-3xl font-semibold leading-tight sm:text-4xl">Welcome back</h2>
              <p className="mt-4 max-w-sm text-sm leading-relaxed text-white/90">
                Sign in, search our catalogue, fill your bag, and send your order. We confirm on WhatsApp.
              </p>
              <ul className="mt-8 space-y-2.5 text-sm text-white/90">
                <li className="flex items-center gap-2">
                  <span className="flex h-6 w-6 items-center justify-center rounded-full bg-white/15 text-xs">✓</span>
                  Search by code or name
                </li>
                <li className="flex items-center gap-2">
                  <span className="flex h-6 w-6 items-center justify-center rounded-full bg-white/15 text-xs">✓</span>
                  See prices before you order
                </li>
                <li className="flex items-center gap-2">
                  <span className="flex h-6 w-6 items-center justify-center rounded-full bg-white/15 text-xs">✓</span>
                  Track delivery here
                </li>
              </ul>
            </div>
          </div>
          <div className="flex flex-1 flex-col justify-center px-6 py-8 sm:px-10 lg:py-12">
            <form onSubmit={onSubmit} className="mx-auto w-full max-w-md space-y-5">
              <label className="block text-sm font-medium text-jc-ink">
                Mobile number
                <input
                  name="phone"
                  data-testid="portal-phone"
                  type="tel"
                  inputMode="tel"
                  autoComplete="tel"
                  required
                  className="mt-2 w-full rounded-xl border border-jc-border bg-white px-4 py-3.5 text-sm shadow-sm outline-none ring-jc-accent/30 transition focus:border-jc-brand focus:ring-2"
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
                  className="mt-2 w-full rounded-xl border border-jc-border bg-white px-4 py-3.5 text-sm shadow-sm outline-none ring-jc-accent/30 transition focus:border-jc-brand focus:ring-2"
                />
              </label>
              <button
                type="submit"
                className="w-full rounded-xl bg-jc-brand px-4 py-3.5 text-sm font-semibold text-white shadow-lg transition hover:bg-jc-brand-light sm:w-auto sm:min-w-[180px]"
              >
                Sign in
              </button>
            </form>
            {msg ? (
              <p className="mx-auto mt-6 max-w-md rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
                {msg}
              </p>
            ) : null}
          </div>
        </section>
      ) : (
        <div className="space-y-6">
          <div className="overflow-hidden rounded-3xl border border-jc-border/80 bg-jc-card shadow-jc ring-1 ring-black/[0.03]">
            <div className="flex flex-col gap-4 bg-gradient-to-r from-jc-bg-deep/90 via-white to-jc-bg/40 p-5 sm:flex-row sm:items-center sm:justify-between sm:p-6">
              <div className="flex min-w-0 items-center gap-4">
                <div
                  className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-jc-brand to-jc-accent font-display text-base font-bold text-white shadow-md"
                  aria-hidden
                >
                  {profileInitials(profile?.name)}
                </div>
                <div className="min-w-0">
                  <p className="text-xs font-medium uppercase tracking-wide text-jc-muted">Hello</p>
                  <p className="truncate font-display text-xl font-semibold text-jc-ink">{profile?.name ?? "…"}</p>
                  {profile ? (
                    <p className="mt-1 truncate text-sm text-jc-muted">
                      {profile.company_name ? `${profile.company_name} · ` : null}
                      {profile.city ?? ""}
                      {profile.phone ? ` · ${profile.phone}` : null}
                    </p>
                  ) : (
                    <p className="mt-1 text-sm text-jc-muted">Loading your account…</p>
                  )}
                </div>
              </div>
              <button
                type="button"
                onClick={logout}
                className="shrink-0 self-start rounded-xl border border-jc-border bg-white/80 px-4 py-2.5 text-sm font-medium text-jc-muted shadow-sm transition hover:bg-white hover:text-jc-ink sm:self-auto"
              >
                Sign out
              </button>
            </div>
          </div>
          {ok ? (
            <p className="rounded-2xl border border-emerald-200 bg-emerald-50/95 px-4 py-3 text-sm text-emerald-900 shadow-sm">
              {ok}
            </p>
          ) : null}

          <nav className="-mx-1 flex snap-x snap-mandatory gap-2 overflow-x-auto pb-1 sm:mx-0 sm:grid sm:grid-cols-3 sm:overflow-visible sm:pb-0">
            <ShopTab
              active={portalTab === "availability"}
              onClick={() => setPortalTab("availability")}
              icon="🔍"
              title="Browse shop"
              subtitle="Search & add to bag"
              data-testid="portal-tab-browse"
            />
            <ShopTab
              active={portalTab === "order_now"}
              onClick={() => setPortalTab("order_now")}
              icon="🛒"
              title="Your bag"
              subtitle="Review & place order"
              badge={cartLines.length > 0 ? cartLines.length : undefined}
              data-testid="portal-tab-bag"
            />
            <ShopTab
              active={portalTab === "my_orders"}
              onClick={() => setPortalTab("my_orders")}
              icon="📦"
              title="Your orders"
              subtitle="Track & confirm"
              data-testid="portal-tab-orders"
            />
          </nav>

          {portalTab === "availability" ? (
            <div
              className={`relative overflow-hidden rounded-3xl border border-jc-border/80 bg-jc-card shadow-jc-lg ring-1 ring-black/[0.03] ${cartLines.length > 0 ? "pb-28" : ""}`}
            >
              <div className="border-b border-jc-border/90 bg-gradient-to-br from-amber-50/90 via-white to-jc-bg-deep/60 px-5 py-6 sm:px-8">
                <div className="flex flex-wrap items-end justify-between gap-4">
                  <div>
                    <h3 className="font-display text-2xl font-semibold text-jc-ink sm:text-[1.65rem]">Find products</h3>
                    <p className="mt-1 max-w-xl text-sm text-jc-muted">
                      Search by code or name. Add to your bag, then open{" "}
                      <strong className="font-semibold text-jc-ink">Your bag</strong> to send your order.
                    </p>
                  </div>
                  <p className="hidden max-w-[10rem] rounded-2xl bg-white/80 px-3 py-2 text-center text-[11px] font-medium leading-snug text-jc-muted shadow-sm ring-1 ring-jc-border/70 sm:block">
                    List prices shown here
                  </p>
                </div>
              </div>

              <div className="relative px-5 py-6 sm:px-8">
                <p className="text-xs font-semibold uppercase tracking-wide text-jc-muted">Search catalogue</p>
                <div className="relative mt-2">
                  <div className="flex gap-1 rounded-2xl border-2 border-jc-border bg-white p-1 shadow-sm transition focus-within:border-jc-brand focus-within:shadow-md focus-within:ring-4 focus-within:ring-jc-brand/10">
                    <span className="flex w-11 shrink-0 items-center justify-center text-lg opacity-80" aria-hidden>
                      🔍
                    </span>
                    <input
                      value={shopQ}
                      onChange={(e) => {
                        setShopQ(e.target.value);
                        setShopSuggestOpen(true);
                      }}
                      onFocus={() => setShopSuggestOpen(true)}
                      onBlur={() => {
                        setTimeout(() => setShopSuggestOpen(false), 180);
                      }}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          void runSearch();
                        }
                      }}
                      className="min-w-0 flex-1 border-0 bg-transparent py-3 pr-2 text-sm outline-none ring-0 placeholder:text-jc-muted/60"
                      placeholder="Item code or product name"
                      autoComplete="off"
                    />
                    <button
                      type="button"
                      className="shrink-0 rounded-xl bg-jc-brand px-4 py-2.5 text-sm font-semibold text-white shadow-md transition hover:bg-jc-brand-light disabled:opacity-55"
                      onClick={() => void runSearch()}
                      disabled={shopLoading}
                    >
                      {shopLoading ? "…" : "Search"}
                    </button>
                  </div>
                  {shopSuggestOpen && shopSuggestions.length > 0 ? (
                    <ul className="absolute left-0 right-0 top-full z-20 mt-2 max-h-52 overflow-auto rounded-xl border border-jc-border bg-white py-1 shadow-jc-lg">
                      {shopSuggestions.map((s) => (
                        <li key={s.catalog_product_id}>
                          <button
                            type="button"
                            className="w-full px-4 py-2.5 text-left text-sm hover:bg-jc-bg"
                            onMouseDown={(e) => e.preventDefault()}
                            onClick={() => pickSuggestion(s)}
                          >
                            <span className="font-medium text-jc-ink">{s.our_product_id}</span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              </div>

              {shopErr ? (
                <p className="mx-5 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800 sm:mx-8">
                  {shopErr}
                </p>
              ) : null}

              {!shopDidSearch && !shopLoading && !shopErr && shopResults.length === 0 ? (
                <div className="mx-5 mb-6 flex flex-col items-center rounded-2xl border border-dashed border-jc-border/90 bg-gradient-to-b from-jc-bg/80 to-white px-6 py-10 text-center sm:mx-8">
                  <span className="text-4xl" aria-hidden>
                    🛍️
                  </span>
                  <p className="mt-4 font-display text-lg font-semibold text-jc-ink">Start with a search</p>
                  <p className="mt-2 max-w-sm text-sm text-jc-muted">
                    Type a product name or your usual item code, then tap Search.
                  </p>
                </div>
              ) : null}

              {shopLoading ? (
                <div className="grid gap-6 px-5 pb-8 sm:grid-cols-2 sm:px-8">
                  {[0, 1, 2, 3].map((i) => (
                    <div
                      key={i}
                      className="animate-pulse overflow-hidden rounded-3xl border border-jc-border/60 bg-jc-bg-deep/30"
                    >
                      <div className="aspect-square bg-jc-bg-deep/50" />
                      <div className="space-y-3 p-5">
                        <div className="h-4 w-3/4 max-w-[12rem] rounded-lg bg-jc-border/90" />
                        <div className="h-4 w-1/3 max-w-[5rem] rounded-lg bg-jc-border/80" />
                        <div className="h-9 w-full rounded-xl bg-jc-border/70" />
                      </div>
                    </div>
                  ))}
                </div>
              ) : shopResults.length > 0 ? (
                <div className="grid gap-6 px-5 pb-8 sm:grid-cols-2 sm:px-8">
                  {shopResults.map((p) => {
                    const avail = availabilityLine(p.stock_status);
                    const canOrder = p.stock_status !== "out_of_stock";
                    return (
                      <article
                        key={p.catalog_product_id}
                        className="flex flex-col overflow-hidden rounded-3xl border border-jc-border/90 bg-white shadow-jc ring-1 ring-black/[0.04] transition hover:shadow-jc-lg"
                      >
                        <div className="relative aspect-square w-full bg-gradient-to-b from-jc-bg-deep to-jc-bg/80">
                          {p.image_url ? (
                            // eslint-disable-next-line @next/next/no-img-element
                            <img
                              src={p.image_url}
                              alt={p.our_product_id}
                              className="h-full w-full object-contain object-center p-3"
                            />
                          ) : (
                            <div className="flex h-full min-h-[160px] flex-col items-center justify-center gap-2 text-jc-muted">
                              <span className="text-4xl opacity-35" aria-hidden>
                                ✨
                              </span>
                              <span className="text-sm">Photo coming soon</span>
                            </div>
                          )}
                          <span
                            className={`absolute right-3 top-3 max-w-[11rem] truncate rounded-full px-3 py-1 text-xs font-semibold ring-1 ${stockPillClass(p.stock_status)}`}
                          >
                            {avail.title}
                          </span>
                        </div>
                        <div className="flex flex-1 flex-col gap-3 p-5">
                          <div className="flex flex-wrap items-start justify-between gap-3">
                            <p className="font-display text-lg font-semibold leading-snug text-jc-ink">
                              {p.our_product_id}
                            </p>
                            <div className="text-right">
                              <span className="block text-[10px] font-semibold uppercase tracking-wider text-jc-muted">
                                Our price
                              </span>
                              <span className="text-xl font-bold tabular-nums text-jc-brand">₹{p.selling_price}</span>
                            </div>
                          </div>
                          <p className="line-clamp-2 text-xs leading-relaxed text-jc-muted">{avail.hint}</p>
                          {p.stock_status === "out_of_stock" && p.alternatives.length === 0 ? (
                            <p className="text-xs font-medium text-jc-muted">
                              No substitute SKU in stock with us right now.
                            </p>
                          ) : null}
                          <div className="mt-auto flex flex-wrap items-end gap-3 border-t border-jc-border/60 pt-4">
                            <label className="block text-sm font-medium text-jc-ink">
                              Qty
                              <input
                                type="number"
                                min={1}
                                max={MAX_ORDER_QTY}
                                value={qtyDraft[p.catalog_product_id] ?? "1"}
                                onChange={(e) => setQtyDraftFor(p.catalog_product_id, e.target.value)}
                                className="mt-1.5 w-24 rounded-xl border border-jc-border bg-jc-bg/30 px-3 py-2 text-sm shadow-inner"
                              />
                            </label>
                            <button
                              type="button"
                              disabled={!canOrder}
                              onClick={() => addProductToCart(p, qtyDraft[p.catalog_product_id] ?? "1")}
                              className="rounded-xl bg-jc-accent px-5 py-2.5 text-sm font-semibold text-white shadow-md transition hover:bg-jc-accent-hover disabled:cursor-not-allowed disabled:bg-neutral-300"
                            >
                              Add to bag
                            </button>
                          </div>
                        </div>
                        {p.alternatives.length > 0 ? (
                          <div className="border-t border-jc-border bg-jc-bg/50 px-5 py-4">
                            <p className="text-xs font-bold uppercase tracking-wide text-jc-muted">Similar in stock</p>
                            <ul className="mt-3 grid grid-cols-3 gap-2">
                              {p.alternatives.map((a) => (
                                <li
                                  key={a.catalog_product_id}
                                  className="flex flex-col overflow-hidden rounded-xl border border-jc-border bg-white p-2 shadow-sm"
                                >
                                  <div className="aspect-square w-full overflow-hidden rounded-lg bg-jc-bg-deep/40">
                                    {a.image_url ? (
                                      // eslint-disable-next-line @next/next/no-img-element
                                      <img
                                        src={a.image_url}
                                        alt=""
                                        className="h-full w-full object-contain object-center p-1"
                                      />
                                    ) : (
                                      <div className="flex h-full min-h-[72px] items-center justify-center text-[10px] text-jc-muted">
                                        —
                                      </div>
                                    )}
                                  </div>
                                  <p className="mt-1.5 truncate text-center text-[10px] font-semibold text-jc-ink">
                                    {a.our_product_id}
                                  </p>
                                </li>
                              ))}
                            </ul>
                          </div>
                        ) : null}
                      </article>
                    );
                  })}
                </div>
              ) : shopDidSearch && !shopLoading && !shopErr ? (
                <div className="mx-5 mb-8 flex flex-col items-center rounded-2xl border border-jc-border bg-jc-bg/40 px-6 py-10 text-center sm:mx-8">
                  <span className="text-3xl" aria-hidden>
                    🔎
                  </span>
                  <p className="mt-3 font-display text-base font-semibold text-jc-ink">No matches</p>
                  <p className="mt-2 max-w-sm text-sm text-jc-muted">
                    Try another code or name. Admin and this portal must share one database — check the API console for{" "}
                    <span className="font-mono text-[11px] text-jc-ink/80">[backend] database=…</span>.
                  </p>
                </div>
              ) : null}

              {cartLines.length > 0 ? (
                <div className="sticky bottom-0 z-10 mx-3 mb-3 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-jc-border bg-white/95 px-4 py-3.5 shadow-2xl shadow-black/10 backdrop-blur-md sm:mx-6 sm:mb-4 sm:px-6">
                  <div className="text-sm text-jc-ink">
                    <span className="font-semibold">{cartLines.length}</span> item(s) · Est.{" "}
                    <span className="font-bold tabular-nums text-jc-brand">₹{cartTotal.toFixed(2)}</span>
                  </div>
                  <button
                    type="button"
                    onClick={() => setPortalTab("order_now")}
                    className="rounded-xl bg-jc-accent px-5 py-2.5 text-sm font-semibold text-white shadow-md transition hover:bg-jc-accent-hover"
                  >
                    Go to bag
                  </button>
                </div>
              ) : null}
            </div>
          ) : portalTab === "order_now" ? (
            <div className="overflow-hidden rounded-3xl border border-jc-border/80 bg-jc-card shadow-jc-lg ring-1 ring-black/[0.03]">
              <div className="border-b border-jc-border/90 bg-gradient-to-r from-jc-bg-deep/80 to-white px-5 py-6 sm:px-8">
                <h3 className="font-display text-2xl font-semibold text-jc-ink">Your bag</h3>
                <p className="mt-1 max-w-2xl text-sm text-jc-muted">
                  Change quantities, then place your order. We confirm on WhatsApp if stock or price differs.
                </p>
              </div>
              <div className="space-y-6 p-5 sm:p-8">
                {orderMsg ? (
                  <p
                    className={`rounded-2xl border px-4 py-3 text-sm ${
                      orderMsg.startsWith("Order #")
                        ? "border-emerald-200 bg-emerald-50 text-emerald-900"
                        : "border-red-200 bg-red-50 text-red-800"
                    }`}
                  >
                    {orderMsg}
                  </p>
                ) : null}
                {cartLines.length === 0 ? (
                  <div className="mt-10 flex flex-col items-center rounded-2xl border border-dashed border-jc-border bg-jc-bg/50 px-6 py-14 text-center">
                    <span className="text-5xl opacity-90" aria-hidden>
                      🛒
                    </span>
                    <p className="mt-4 font-display text-lg font-semibold text-jc-ink">Your bag is empty</p>
                    <p className="mt-2 max-w-sm text-sm text-jc-muted">
                      Go to <strong className="text-jc-ink">Browse shop</strong> and add products.
                    </p>
                    <button
                      type="button"
                      onClick={() => setPortalTab("availability")}
                      className="mt-6 rounded-xl bg-jc-brand px-6 py-3 text-sm font-semibold text-white shadow-md transition hover:bg-jc-brand-light"
                    >
                      Browse shop
                    </button>
                  </div>
                ) : (
                  <>
                    <div className="mt-6 space-y-3 md:hidden">
                      {cartLines.map(({ p, qty }) => {
                        const unit = parseFloat(p.selling_price || "0") || 0;
                        const line = unit * qty;
                        const av = availabilityLine(p.stock_status);
                        return (
                          <div
                            key={p.catalog_product_id}
                            className="flex gap-3 rounded-2xl border border-jc-border bg-white p-3 shadow-sm"
                          >
                            <div className="relative h-24 w-24 shrink-0 overflow-hidden rounded-xl bg-jc-bg-deep/60 ring-1 ring-jc-border/80">
                              {p.image_url ? (
                                // eslint-disable-next-line @next/next/no-img-element
                                <img
                                  src={p.image_url}
                                  alt=""
                                  className="h-full w-full object-cover"
                                />
                              ) : (
                                <div className="flex h-full items-center justify-center text-[10px] text-jc-muted">
                                  No photo
                                </div>
                              )}
                            </div>
                            <div className="min-w-0 flex-1">
                              <p className="font-semibold leading-snug text-jc-ink">{p.our_product_id}</p>
                              <p className="mt-1 text-xs text-jc-muted">{av.title}</p>
                              <p className="mt-2 text-sm">
                                <span className="text-jc-muted">₹{p.selling_price}</span>
                                <span className="mx-1 text-jc-border">·</span>
                                <span className="font-semibold tabular-nums text-jc-brand">₹{line.toFixed(2)}</span>
                              </p>
                              <div className="mt-2 flex flex-wrap items-center gap-2">
                                <input
                                  type="number"
                                  min={1}
                                  max={MAX_ORDER_QTY}
                                  value={qty}
                                  onChange={(e) => setLineQty(p.catalog_product_id, e.target.value)}
                                  className="w-20 rounded-lg border border-jc-border px-2 py-1.5 text-right text-sm"
                                />
                                <button
                                  type="button"
                                  className="text-xs font-semibold text-red-700 underline-offset-2 hover:underline"
                                  onClick={() => removeLine(p.catalog_product_id)}
                                >
                                  Remove
                                </button>
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                    <div className="mt-6 hidden overflow-x-auto rounded-2xl border border-jc-border shadow-inner md:block">
                      <table className="w-full min-w-[640px] border-collapse text-sm">
                        <thead>
                          <tr className="border-b border-jc-border bg-jc-bg-deep/70 text-left text-[11px] font-bold uppercase tracking-wide text-jc-muted">
                            <th className="px-4 py-3">Item</th>
                            <th className="px-4 py-3 text-right">Price</th>
                            <th className="px-4 py-3">Stock</th>
                            <th className="px-4 py-3 text-right">Qty</th>
                            <th className="px-4 py-3 text-right">Line</th>
                            <th className="px-4 py-3" />
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-jc-border bg-white">
                          {cartLines.map(({ p, qty }) => {
                            const unit = parseFloat(p.selling_price || "0") || 0;
                            const line = unit * qty;
                            const av = availabilityLine(p.stock_status);
                            return (
                              <tr key={p.catalog_product_id}>
                                <td className="px-4 py-3 font-medium text-jc-ink">{p.our_product_id}</td>
                                <td className="px-4 py-3 text-right tabular-nums">₹{p.selling_price}</td>
                                <td className="px-4 py-3 text-xs text-jc-muted">{av.title}</td>
                                <td className="px-4 py-3 text-right">
                                  <input
                                    type="number"
                                    min={1}
                                    max={MAX_ORDER_QTY}
                                    value={qty}
                                    onChange={(e) => setLineQty(p.catalog_product_id, e.target.value)}
                                    className="w-20 rounded-lg border border-jc-border px-2 py-1.5 text-right text-sm"
                                  />
                                </td>
                                <td className="px-4 py-3 text-right font-medium tabular-nums text-jc-ink">
                                  ₹{line.toFixed(2)}
                                </td>
                                <td className="px-4 py-3">
                                  <button
                                    type="button"
                                    className="text-xs font-semibold text-red-700 underline-offset-2 hover:underline"
                                    onClick={() => removeLine(p.catalog_product_id)}
                                  >
                                    Remove
                                  </button>
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                    <div className="mt-6 flex flex-col gap-4 rounded-2xl border border-jc-border bg-gradient-to-br from-jc-bg/80 to-white p-5 sm:flex-row sm:items-center sm:justify-between">
                      <div className="flex-1">
                        <p className="font-display text-lg font-semibold text-jc-ink">
                          Estimated total{" "}
                          <span className="text-2xl tabular-nums text-jc-brand">₹{cartTotal.toFixed(2)}</span>
                        </p>
                        <label className="mt-3 block text-sm text-jc-ink">
                          Order notes (optional)
                          <textarea
                            value={orderNotes}
                            onChange={(e) => setOrderNotes(e.target.value)}
                            rows={2}
                            placeholder="e.g. Please make it urgent / Send via XYZ transport"
                            className="mt-1 w-full rounded-xl border border-jc-border bg-white px-3 py-2 text-sm text-jc-ink placeholder-neutral-400 focus:outline-none focus:ring-1 focus:ring-jc-brand"
                          />
                        </label>
                      </div>
                      <button
                        type="button"
                        disabled={orderSubmitting}
                        onClick={() => void placeOrder()}
                        className="w-full rounded-xl bg-jc-brand py-3.5 text-sm font-semibold text-white shadow-lg transition hover:bg-jc-brand-light disabled:bg-neutral-300 sm:w-auto sm:min-w-[220px]"
                      >
                        {orderSubmitting ? "Sending…" : "Place order"}
                      </button>
                    </div>
                  </>
                )}
              </div>
            </div>
          ) : (
            <div className="overflow-hidden rounded-3xl border border-jc-border/80 bg-jc-card shadow-jc-lg ring-1 ring-black/[0.03]">
              <div className="flex flex-col gap-4 border-b border-jc-border/90 bg-gradient-to-r from-white via-jc-bg/30 to-jc-bg-deep/40 px-5 py-6 sm:flex-row sm:items-center sm:justify-between sm:px-8">
                <div>
                  <h3 className="font-display text-2xl font-semibold text-jc-ink">Your orders</h3>
                  <p className="mt-1 text-xs text-jc-muted">
                    Confirmed → billed → shipped. We ping you on WhatsApp.
                  </p>
                </div>
                <button
                  type="button"
                  className="shrink-0 self-start rounded-xl border border-jc-border bg-white px-4 py-2.5 text-xs font-semibold text-jc-muted shadow-sm transition hover:bg-jc-bg sm:self-auto"
                  onClick={() => token && void loadMyOrders(token, orderStatusFilter)}
                >
                  Refresh
                </button>
              </div>
              <div className="p-5 sm:p-8">
                <div className="flex flex-wrap items-center gap-3">
                  <span className="text-xs font-semibold uppercase tracking-wide text-jc-muted">Filter</span>
                  <select
                    value={orderStatusFilter}
                    onChange={(e) => setOrderStatusFilter(e.target.value)}
                    className="rounded-xl border border-jc-border bg-white px-4 py-2.5 text-sm font-medium text-jc-ink shadow-sm"
                  >
                    <option value="">All statuses</option>
                    <option value="confirmed">Confirmed</option>
                    <option value="billed">Billed</option>
                    <option value="shipped">Shipped</option>
                    <option value="cancelled">Cancelled</option>
                  </select>
                </div>
                {ordersErr ? (
                  <p className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">{ordersErr}</p>
                ) : null}
                {ordersLoading ? (
                  <div className="mt-6 space-y-4" aria-busy="true">
                    {[0, 1, 2].map((i) => (
                      <div
                        key={i}
                        className="h-28 animate-pulse rounded-2xl border border-jc-border/60 bg-jc-bg-deep/40"
                      />
                    ))}
                  </div>
                ) : myOrders.length === 0 ? (
                  <div className="mt-10 flex flex-col items-center rounded-2xl border border-dashed border-jc-border bg-jc-bg/40 px-6 py-14 text-center">
                    <span className="text-5xl" aria-hidden>
                      📦
                    </span>
                    <p className="mt-4 font-display text-lg font-semibold text-jc-ink">No orders yet</p>
                    <p className="mt-2 max-w-sm text-sm text-jc-muted">Place an order from Your bag — it will show up here.</p>
                  </div>
                ) : (
                  <ul className="mt-6 space-y-4">
                    {myOrders.map((o) => (
                      <li
                        key={o.id}
                        className="overflow-hidden rounded-2xl border border-jc-border/90 bg-white shadow-jc ring-1 ring-black/[0.03] sm:rounded-3xl"
                      >
                        <div className="border-l-4 border-jc-brand bg-gradient-to-r from-jc-bg/50 to-white px-4 py-4 sm:px-6 sm:py-5">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <span className="font-display text-lg font-semibold text-jc-ink">Order #{o.id}</span>
                            <span
                              className={`rounded-full px-3 py-1 text-xs font-bold ${orderBadgeClass(o.status)}`}
                            >
                              {statusBadge(o.status)}
                            </span>
                          </div>
                          <p className="mt-2 text-sm text-jc-muted">
                            Total{" "}
                            <span className="text-base font-bold tabular-nums text-jc-ink">₹{o.total_amount}</span>
                          </p>
                          <ul className="mt-4 space-y-2 border-t border-jc-border/70 pt-4 text-sm text-jc-ink">
                            {o.items.map((it) => (
                              <li
                                key={`${o.id}-${it.catalog_product_id}`}
                                className="flex flex-wrap justify-between gap-2 rounded-lg bg-white/60 px-2 py-1.5"
                              >
                                <span className="font-medium">{it.our_product_id}</span>
                                <span className="tabular-nums text-jc-muted">
                                  × {it.quantity}{" "}
                                  <span className="text-xs">(@ ₹{it.unit_price})</span>
                                </span>
                              </li>
                            ))}
                          </ul>
                          {o.customer_confirmed_delivery_at ? (
                            <p className="mt-3 text-xs font-semibold text-emerald-800">
                              You marked delivered {fmtTs(o.customer_confirmed_delivery_at)}.
                            </p>
                          ) : null}
                          {o.status === "shipped" ? (
                            <div className="mt-4">
                              <button
                                type="button"
                                disabled={confirmBusyId === o.id}
                                className="rounded-xl border-2 border-jc-brand bg-white px-5 py-2.5 text-sm font-bold text-jc-brand shadow-sm transition hover:bg-jc-bg disabled:opacity-50"
                                onClick={() => void confirmReceived(o.id)}
                              >
                                {confirmBusyId === o.id ? "Saving…" : "I received my order"}
                              </button>
                            </div>
                          ) : null}
                          {o.status === "shipped" || o.status === "delivered" ? (
                            <div className="mt-4 rounded-xl border border-jc-border bg-white/90 p-4 text-sm text-jc-ink shadow-inner">
                              <p className="text-[10px] font-bold uppercase tracking-widest text-jc-muted">
                                Delivery details
                              </p>
                              {o.shipment_receipt ? (
                                <p className="mt-2">
                                  <span className="text-jc-muted">Reference </span>
                                  {o.shipment_receipt}
                                </p>
                              ) : null}
                              {o.shipment_contact ? (
                                <p className="mt-1">
                                  <span className="text-jc-muted">Contact </span>
                                  {o.shipment_contact}
                                </p>
                              ) : null}
                              {o.shipment_notes ? (
                                <p className="mt-1">
                                  <span className="text-jc-muted">Note </span>
                                  {o.shipment_notes}
                                </p>
                              ) : null}
                              {!o.shipment_receipt && !o.shipment_contact && !o.shipment_notes ? (
                                <p className="mt-2 text-jc-muted">Tracking appears here when we dispatch.</p>
                              ) : null}
                            </div>
                          ) : null}
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
