"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiUrl, fetchApi, formatApiError } from "@/lib/api";
import type {
  CustomerOrderPublic,
  CustomerPublic,
  ShopProductPublic,
  ShopSuggestionPublic,
} from "@/lib/types";

// ── helpers ──────────────────────────────────────────────────────────────────

function fmtDateTime(iso: string): string {
  try {
    const d = new Date(iso);
    return isNaN(d.getTime())
      ? iso
      : d.toLocaleString("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
  } catch { return iso; }
}

function fmtDate(iso: string): string {
  try {
    const d = new Date(iso);
    return isNaN(d.getTime()) ? iso : d.toLocaleDateString("en-IN", { day: "2-digit", month: "long", year: "numeric" });
  } catch { return iso; }
}

function orderBadgeClass(status: string): string {
  if (status === "closed")  return "bg-neutral-100 text-neutral-700";
  if (status === "billed")  return "bg-violet-100 text-violet-800";
  return "bg-amber-100 text-amber-800"; // received
}

function statusLabel(s: string): string {
  return { received: "Received", billed: "Billed", closed: "Closed" }[s] ?? s;
}

function stockPillClass(s: string): string {
  if (s === "in_stock")     return "bg-emerald-100 text-emerald-800 ring-emerald-200/70";
  if (s === "low_stock")    return "bg-amber-100 text-amber-800 ring-amber-200/70";
  if (s === "out_of_stock") return "bg-stone-100 text-stone-600 ring-stone-200/70";
  return "bg-stone-100 text-stone-700 ring-stone-200/70";
}

function stockLabel(s: string): string {
  if (s === "in_stock")     return "In Stock";
  if (s === "low_stock")    return "Limited Stock";
  if (s === "out_of_stock") return "Out of Stock";
  return "Unknown";
}

function availHint(s: string): string {
  if (s === "in_stock")     return "Available — place your order below.";
  if (s === "low_stock")    return "Limited units remaining. Order soon.";
  if (s === "out_of_stock") return "Not available right now.";
  return "";
}

function normalizeQ(s: string): string {
  return s.replace(/\u00a0/g, " ").trim().replace(/\s+/g, " ");
}

const MAX_QTY = 100_000_000;

// ── print receipt ─────────────────────────────────────────────────────────────

function printOrderReceipt(
  order: CustomerOrderPublic,
  profile: CustomerPublic | null,
  imageMap: Record<number, string>,
) {
  const rows = order.items.map((it) => {
    const imgSrc = imageMap[it.catalog_product_id];
    const imgTag = imgSrc
      ? `<img src="${imgSrc}" style="width:52px;height:52px;object-fit:contain;border-radius:6px;border:1px solid #e5e7eb;" />`
      : `<div style="width:52px;height:52px;border-radius:6px;border:1px solid #e5e7eb;background:#f9fafb;display:flex;align-items:center;justify-content:center;color:#d1d5db;font-size:18px;">✦</div>`;
    const category = (it as { category?: string }).category || "";
    return `
      <tr>
        <td style="padding:10px 8px;border-bottom:1px solid #f3f4f6;vertical-align:middle;text-align:center;">${imgTag}</td>
        <td style="padding:10px 8px;border-bottom:1px solid #f3f4f6;vertical-align:middle;">
          <div style="font-weight:700;font-size:13px;color:#1f2937;">${it.our_product_id}</div>
          <div style="font-size:12px;color:#374151;margin-top:2px;">${it.name || ""}</div>
          ${category ? `<div style="font-size:11px;color:#9ca3af;margin-top:1px;">${category}</div>` : ""}
        </td>
        <td style="padding:10px 8px;border-bottom:1px solid #f3f4f6;text-align:right;vertical-align:middle;font-variant-numeric:tabular-nums;">${it.quantity}</td>
        <td style="padding:10px 8px;border-bottom:1px solid #f3f4f6;text-align:right;vertical-align:middle;font-variant-numeric:tabular-nums;">₹${Number(it.unit_price).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</td>
        <td style="padding:10px 8px;border-bottom:1px solid #f3f4f6;text-align:right;vertical-align:middle;font-weight:600;font-variant-numeric:tabular-nums;">₹${Number(it.line_total).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</td>
      </tr>`;
  }).join("");

  const customerName = profile?.company_name || profile?.name || "—";
  const contactPerson = profile?.company_name && profile?.name && profile.name !== profile.company_name ? profile.name : "";

  const html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>Order Receipt #${order.id} — Jyoti Creative Cards</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: 'Helvetica Neue', Arial, sans-serif; color: #111827; background: #fff; padding: 36px; font-size: 13px; }
    @media print { body { padding: 18px; } @page { margin: 14mm; } }
    .header { display: flex; justify-content: space-between; align-items: flex-start; padding-bottom: 20px; margin-bottom: 22px; border-bottom: 3px solid #8B1C0A; }
    .logo-mark { width: 40px; height: 40px; border-radius: 10px; background: linear-gradient(135deg, #8B1C0A, #c0392b); display: flex; align-items: center; justify-content: center; color: white; font-weight: 900; font-size: 14px; margin-right: 12px; flex-shrink: 0; }
    .brand-name { font-size: 20px; font-weight: 800; color: #8B1C0A; letter-spacing: -0.3px; }
    .brand-sub  { font-size: 11px; color: #6b7280; margin-top: 2px; }
    .receipt-title { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; color: #9ca3af; text-align: right; }
    .receipt-id    { font-size: 28px; font-weight: 900; color: #111827; text-align: right; }
    .receipt-date  { font-size: 11px; color: #6b7280; text-align: right; margin-top: 3px; }
    .meta { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 26px; }
    .meta-card { background: #f9fafb; border-radius: 10px; padding: 14px 16px; border: 1px solid #f3f4f6; }
    .meta-card h4 { font-size: 9px; text-transform: uppercase; letter-spacing: 1px; color: #9ca3af; font-weight: 700; margin-bottom: 8px; }
    .meta-card .primary { font-size: 15px; font-weight: 800; color: #111827; }
    .meta-card p { font-size: 12px; color: #374151; line-height: 1.6; margin-top: 1px; }
    .status-badge { display: inline-block; padding: 2px 10px; border-radius: 20px; font-size: 11px; font-weight: 700; background: #fef3c7; color: #92400e; }
    table { width: 100%; border-collapse: collapse; margin-bottom: 18px; }
    thead tr { background: #111827; }
    thead th { padding: 9px 8px; color: white; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; text-align: left; }
    thead th:nth-child(n+3) { text-align: right; }
    tbody tr:nth-child(even) { background: #f9fafb; }
    .total-bar { display: flex; justify-content: flex-end; margin-top: 4px; }
    .total-inner { background: #8B1C0A; color: white; border-radius: 10px; padding: 12px 20px; display: flex; gap: 20px; align-items: center; }
    .total-label { font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: rgba(255,255,255,0.7); }
    .total-value { font-size: 24px; font-weight: 900; font-variant-numeric: tabular-nums; }
    .footer { margin-top: 30px; border-top: 1px solid #e5e7eb; padding-top: 14px; text-align: center; font-size: 11px; color: #9ca3af; line-height: 1.6; }
  </style>
</head>
<body>
  <div class="header">
    <div style="display:flex;align-items:center;">
      <div class="logo-mark">JC</div>
      <div>
        <div class="brand-name">Jyoti Creative Cards</div>
        <div class="brand-sub">Cards, Stationery &amp; Creative Supplies</div>
      </div>
    </div>
    <div>
      <div class="receipt-title">Order Receipt</div>
      <div class="receipt-id">#${order.id}</div>
      <div class="receipt-date">${fmtDateTime(order.created_at)}</div>
    </div>
  </div>

  <div class="meta">
    <div class="meta-card">
      <h4>Bill To</h4>
      <p class="primary">${customerName}</p>
      ${contactPerson ? `<p>${contactPerson}</p>` : ""}
      ${profile?.phone  ? `<p>${profile.phone}</p>`   : ""}
      ${profile?.address ? `<p>${profile.address}</p>` : ""}
      ${profile?.city   ? `<p>${profile.city}</p>`    : ""}
      ${profile?.gst_number ? `<p>GST: ${profile.gst_number}</p>` : ""}
    </div>
    <div class="meta-card">
      <h4>Order Details</h4>
      <p><span style="color:#9ca3af;">Order #</span> <strong>${order.id}</strong></p>
      <p><span style="color:#9ca3af;">Date</span> ${fmtDate(order.created_at)}</p>
      <p><span style="color:#9ca3af;">Time</span> ${new Date(order.created_at).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}</p>
      <p><span style="color:#9ca3af;">Status</span> <span class="status-badge">${statusLabel(order.status)}</span></p>
      ${order.notes ? `<p style="margin-top:6px;color:#6b7280;font-size:11px;">Note: ${order.notes}</p>` : ""}
    </div>
  </div>

  <table>
    <thead>
      <tr>
        <th style="width:60px;text-align:center;">Photo</th>
        <th>Item</th>
        <th style="text-align:right;">Qty</th>
        <th style="text-align:right;">Unit Price</th>
        <th style="text-align:right;">Amount</th>
      </tr>
    </thead>
    <tbody>${rows}</tbody>
  </table>

  <div class="total-bar">
    <div class="total-inner">
      <span class="total-label">Order Total</span>
      <span class="total-value">₹${Number(order.total_amount).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</span>
    </div>
  </div>

  ${(order as { customer_notes?: string }).customer_notes ? `
  <div style="margin-top:16px;border:1px solid #fde68a;background:#fffbeb;border-radius:8px;padding:12px 14px;">
    <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;color:#b45309;margin-bottom:4px;">Customer Note</div>
    <div style="font-size:13px;color:#374151;">${(order as { customer_notes?: string }).customer_notes}</div>
  </div>` : ""}

  <div class="footer">
    Jyoti Creative Cards · Cards, Stationery &amp; Creative Supplies<br/>
    Thank you for your order — we will confirm shortly on WhatsApp.
  </div>
</body>
</html>`;

  const win = window.open("", "_blank", "width=920,height=720");
  if (!win) return;
  win.document.write(html);
  win.document.close();
  win.focus();
  setTimeout(() => win.print(), 700);
}

// ── main ─────────────────────────────────────────────────────────────────────

type PortalTab = "search" | "my_orders";

export default function CustomerPortalPage() {
  const [loginMsg, setLoginMsg]   = useState("");
  const [profile, setProfile]     = useState<CustomerPublic | null>(null);
  const [profileLoading, setProfileLoading] = useState(false);
  const [token, setToken]         = useState<string | null>(null);
  const [portalTab, setPortalTab] = useState<PortalTab>("search");

  // search
  const [shopQ, setShopQ]               = useState("");
  const [suggestions, setSuggestions]   = useState<ShopSuggestionPublic[]>([]);
  const [suggestOpen, setSuggestOpen]   = useState(false);
  const [results, setResults]           = useState<ShopProductPublic[]>([]);
  const [searching, setSearching]       = useState(false);
  const [searchErr, setSearchErr]       = useState("");
  const [didSearch, setDidSearch]       = useState(false);
  const suggestTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [qtyDraft, setQtyDraft]         = useState<Record<number, string>>({});
  const [bookingId, setBookingId]       = useState<number | null>(null);
  const [bookedOrder, setBookedOrder]   = useState<CustomerOrderPublic | null>(null);
  // Note modal state: holds the product being booked until customer adds note + confirms
  const [pendingBook, setPendingBook]   = useState<{ product: ShopProductPublic; qty: number } | null>(null);
  const [noteInput, setNoteInput]       = useState("");
  const [imageMap, setImageMap]         = useState<Record<number, string>>({});

  // orders
  const [myOrders, setMyOrders]             = useState<CustomerOrderPublic[]>([]);
  const [ordersLoading, setOrdersLoading]   = useState(false);
  const [ordersErr, setOrdersErr]           = useState("");
  const [statusFilter, setStatusFilter]     = useState("");

  // ── auth ───────────────────────────────────────────────────────────────────

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

  useEffect(() => {
    try {
      const t = sessionStorage.getItem("token");
      if (t) { setToken(t); void loadMe(t); }
    } catch { /* ignore */ }
  }, [loadMe]);

  async function onLogin(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setLoginMsg("");
    const fd = new FormData(e.currentTarget);
    const r = await fetchApi(apiUrl("auth/login"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phone: String(fd.get("phone") || ""), password: String(fd.get("password") || "") }),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) { setLoginMsg(formatApiError(data) || r.statusText); return; }
    const t = data.access_token as string;
    sessionStorage.setItem("token", t);
    setToken(t);
    await loadMe(t);
  }

  function logout() {
    try { sessionStorage.removeItem("token"); } catch { /* ignore */ }
    setToken(null); setProfile(null); setLoginMsg("");
    setShopQ(""); setResults([]); setSuggestions([]); setDidSearch(false);
    setMyOrders([]); setPortalTab("search"); setBookedOrder(null);
  }

  // ── suggestions ────────────────────────────────────────────────────────────

  useEffect(() => {
    const qn = normalizeQ(shopQ);
    if (!token || qn.length < 1) { setSuggestions([]); return; }
    if (suggestTimer.current) clearTimeout(suggestTimer.current);
    suggestTimer.current = setTimeout(async () => {
      const r = await fetchApi(apiUrl(`shop/products/suggestions?q=${encodeURIComponent(qn)}`), {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await r.json().catch(() => []);
      setSuggestions(r.ok && Array.isArray(data) ? (data as ShopSuggestionPublic[]) : []);
    }, 220);
    return () => { if (suggestTimer.current) clearTimeout(suggestTimer.current); };
  }, [shopQ, token]);

  // ── search ─────────────────────────────────────────────────────────────────

  const runSearch = useCallback(async () => {
    setSearchErr(""); setResults([]);
    if (!token) return;
    const q = normalizeQ(shopQ);
    if (q.length < 1) { setSearchErr("Enter a product code or name."); return; }
    setSearching(true);
    try {
      const r = await fetchApi(apiUrl(`shop/products/search?q=${encodeURIComponent(q)}`), {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await r.json().catch(() => null);
      if (!r.ok) { setSearchErr(formatApiError(data) || r.statusText); return; }
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
    } finally { setSearching(false); }
  }, [token, shopQ]);

  // ── book ───────────────────────────────────────────────────────────────────

  function startBook(p: ShopProductPublic, qtyStr: string) {
    if (!token || p.stock_status === "out_of_stock") return;
    const n = Math.floor(Number(qtyStr));
    const qty = Number.isFinite(n) ? Math.max(1, Math.min(n, MAX_QTY)) : 1;
    setNoteInput("");
    setPendingBook({ product: p, qty });
  }

  async function bookNow(note?: string) {
    if (!token || !pendingBook) return;
    const { product: p, qty } = pendingBook;
    setPendingBook(null);
    setBookingId(p.catalog_product_id);
    try {
      const r = await fetchApi(apiUrl("shop/orders"), {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ lines: [{ catalog_product_id: p.catalog_product_id, quantity: qty }], customer_notes: (note || "").trim() || null }),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) { alert(formatApiError(data) || r.statusText); return; }
      setBookedOrder(data as CustomerOrderPublic);
      void loadMyOrders(token, statusFilter);
    } finally { setBookingId(null); }
  }

  function resetSearch() {
    setShopQ(""); setResults([]); setDidSearch(false); setSearchErr(""); setBookedOrder(null);
  }

  // ── orders ─────────────────────────────────────────────────────────────────

  const loadMyOrders = useCallback(async (t: string, sf?: string) => {
    setOrdersErr(""); setOrdersLoading(true);
    try {
      const qs = sf && sf !== "all" ? `?status=${sf}` : "";
      const r = await fetchApi(apiUrl(`shop/orders${qs}`), { headers: { Authorization: `Bearer ${t}` } });
      const data = await r.json().catch(() => null);
      if (!r.ok) { setOrdersErr(formatApiError(data) || r.statusText); setMyOrders([]); return; }
      setMyOrders(Array.isArray(data) ? (data as CustomerOrderPublic[]) : []);
    } finally { setOrdersLoading(false); }
  }, []);

  useEffect(() => {
    if (!token || portalTab !== "my_orders") return;
    void loadMyOrders(token, statusFilter);
  }, [token, portalTab, statusFilter, loadMyOrders]);

  // ── render: login ──────────────────────────────────────────────────────────

  if (!token) {
    return (
      <section className="overflow-hidden rounded-3xl border border-jc-border/80 bg-jc-card shadow-jc-lg ring-1 ring-black/[0.04] lg:flex lg:min-h-[460px]">
        <div className="relative flex flex-col justify-center overflow-hidden bg-gradient-to-br from-jc-brand via-[#5a1a0a] to-jc-accent px-8 py-10 text-white lg:w-[42%] lg:shrink-0">
          <div className="pointer-events-none absolute -right-16 -top-16 h-48 w-48 rounded-full bg-white/10 blur-2xl" aria-hidden />
          <div className="pointer-events-none absolute -bottom-20 -left-10 h-56 w-56 rounded-full bg-black/20 blur-2xl" aria-hidden />
          <div className="relative z-10">
            <p className="text-xs font-semibold uppercase tracking-widest text-white/60">Dealer Portal</p>
            <h2 className="mt-3 font-display text-3xl font-semibold leading-tight sm:text-4xl">Welcome back</h2>
            <p className="mt-4 max-w-xs text-sm leading-relaxed text-white/85">
              Sign in to browse products, place orders, and track your deliveries.
            </p>
          </div>
        </div>
        <div className="flex flex-1 flex-col justify-center px-6 py-10 sm:px-10">
          <form onSubmit={onLogin} className="mx-auto w-full max-w-sm space-y-5">
            <label className="block text-sm font-medium text-jc-ink">
              Mobile number
              <input name="phone" data-testid="portal-phone" type="tel" inputMode="tel" autoComplete="tel" required
                className="mt-2 w-full rounded-xl border border-jc-border bg-white px-4 py-3.5 text-sm shadow-sm outline-none transition focus:border-jc-brand focus:ring-2 focus:ring-jc-brand/15" />
            </label>
            <label className="block text-sm font-medium text-jc-ink">
              Password
              <input name="password" data-testid="portal-password" type="password" autoComplete="current-password" required
                className="mt-2 w-full rounded-xl border border-jc-border bg-white px-4 py-3.5 text-sm shadow-sm outline-none transition focus:border-jc-brand focus:ring-2 focus:ring-jc-brand/15" />
            </label>
            <button type="submit"
              className="w-full rounded-xl bg-jc-brand px-4 py-3.5 text-sm font-semibold text-white shadow-md transition hover:bg-jc-brand-light">
              Sign in →
            </button>
            {loginMsg && <p className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">{loginMsg}</p>}
          </form>
        </div>
      </section>
    );
  }

  // ── render: portal ─────────────────────────────────────────────────────────

  const displayName = profile?.company_name || profile?.name;

  return (
    <div className="space-y-5">
      {/* Note modal — shown before confirming booking */}
      {pendingBook && (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-4 sm:items-center">
          <div className="w-full max-w-sm rounded-2xl bg-white p-6 shadow-2xl">
            <h3 className="text-base font-bold text-jc-ink">Add a note (optional)</h3>
            <p className="mt-1 text-sm text-jc-muted">
              Booking <strong>{pendingBook.product.our_product_id}</strong> × {pendingBook.qty}
            </p>
            <textarea
              autoFocus
              value={noteInput}
              onChange={(e) => setNoteInput(e.target.value)}
              placeholder="e.g. please deliver fast, send by bus…"
              rows={3}
              className="mt-3 w-full rounded-xl border border-jc-border bg-jc-bg px-3 py-2 text-sm text-jc-ink placeholder-jc-muted focus:outline-none focus:ring-2 focus:ring-jc-brand"
            />
            <div className="mt-4 flex gap-3">
              <button
                type="button"
                disabled={!!bookingId}
                onClick={() => void bookNow(noteInput)}
                className="flex-1 rounded-xl bg-jc-brand py-2.5 text-sm font-bold text-white transition hover:opacity-90 disabled:opacity-50"
              >
                {bookingId ? "Booking…" : "Confirm Booking"}
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
            : <p className="font-semibold text-jc-ink">{displayName || "—"}</p>}
          {!profileLoading && profile?.city && (
            <p className="mt-0.5 text-xs text-jc-muted">{profile.city}</p>
          )}
        </div>
        <button type="button" onClick={logout}
          className="rounded-xl border border-jc-border bg-white px-4 py-2 text-sm font-medium text-jc-muted transition hover:text-jc-ink">
          Sign out
        </button>
      </div>

      {/* Tabs */}
      <div className="flex gap-2">
        <button type="button" onClick={() => { setPortalTab("search"); setBookedOrder(null); }}
          className={`flex-1 rounded-xl py-3 text-sm font-semibold transition ${portalTab === "search" ? "bg-jc-brand text-white shadow-md" : "bg-white border border-jc-border text-jc-ink hover:bg-jc-bg"}`}>
          🔍 Search &amp; Order
        </button>
        <button type="button" onClick={() => setPortalTab("my_orders")}
          className={`flex-1 rounded-xl py-3 text-sm font-semibold transition ${portalTab === "my_orders" ? "bg-jc-brand text-white shadow-md" : "bg-white border border-jc-border text-jc-ink hover:bg-jc-bg"}`}>
          📦 My Orders {myOrders.length > 0 ? `(${myOrders.length})` : ""}
        </button>
      </div>

      {/* ── SEARCH TAB ── */}
      {portalTab === "search" ? (
        bookedOrder ? (
          /* Confirmation screen */
          <div className="overflow-hidden rounded-3xl border border-emerald-200 bg-white shadow-jc-lg">
            <div className="flex items-center gap-3 bg-emerald-600 px-6 py-5">
              <span className="text-3xl">✅</span>
              <div>
                <p className="text-lg font-bold text-white">Order placed!</p>
                <p className="text-sm text-emerald-100">Order #{bookedOrder.id} · We will confirm on WhatsApp shortly</p>
              </div>
            </div>
            <div className="p-6">
              <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-jc-muted">
                {fmtDateTime(bookedOrder.created_at)}
              </p>
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-jc-border text-xs font-bold uppercase tracking-wide text-jc-muted">
                    <th className="pb-2 text-left">Item #</th>
                    <th className="pb-2 text-left">Name / Category</th>
                    <th className="pb-2 text-right">Qty</th>
                    <th className="pb-2 text-right">Rate</th>
                    <th className="pb-2 text-right">Total</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-jc-border/60">
                  {bookedOrder.items.map((it) => (
                    <tr key={it.catalog_product_id}>
                      <td className="py-2.5 font-bold text-jc-ink">{it.our_product_id}</td>
                      <td className="py-2.5">
                        <div className="text-jc-ink">{it.name}</div>
                        {(it as { category?: string }).category && (
                          <div className="text-xs text-jc-muted">{(it as { category?: string }).category}</div>
                        )}
                      </td>
                      <td className="py-2.5 text-right tabular-nums">{it.quantity}</td>
                      <td className="py-2.5 text-right tabular-nums text-jc-muted">₹{it.unit_price}</td>
                      <td className="py-2.5 text-right font-semibold tabular-nums">₹{it.line_total}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr className="border-t-2 border-jc-ink/10">
                    <td colSpan={4} className="pt-3 text-right font-bold text-jc-ink">Order Total</td>
                    <td className="pt-3 text-right text-lg font-extrabold tabular-nums text-jc-brand">₹{bookedOrder.total_amount}</td>
                  </tr>
                </tfoot>
              </table>
              {bookedOrder.customer_notes && (
                <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
                  <p className="text-xs font-semibold uppercase tracking-wide text-amber-700">Your note</p>
                  <p className="mt-1 text-sm text-amber-900">{bookedOrder.customer_notes}</p>
                </div>
              )}
              <div className="mt-6 flex flex-wrap gap-3">
                <button type="button" onClick={resetSearch}
                  className="rounded-xl bg-jc-brand px-5 py-2.5 text-sm font-semibold text-white shadow-md transition hover:bg-jc-brand-light">
                  + Book More
                </button>
                <button type="button" onClick={() => { setPortalTab("my_orders"); void loadMyOrders(token!, statusFilter); }}
                  className="rounded-xl border border-jc-border bg-white px-5 py-2.5 text-sm font-semibold text-jc-ink shadow-sm transition hover:bg-jc-bg">
                  View All Orders
                </button>
                <button type="button" onClick={() => printOrderReceipt(bookedOrder, profile, imageMap)}
                  className="rounded-xl border border-jc-border bg-white px-5 py-2.5 text-sm font-medium text-jc-muted shadow-sm transition hover:bg-jc-bg">
                  🖨 Print / Save PDF
                </button>
              </div>
            </div>
          </div>
        ) : (
          /* Search panel */
          <div className="overflow-hidden rounded-3xl border border-jc-border/80 bg-jc-card shadow-jc-lg ring-1 ring-black/[0.03]">
            {/* Search header */}
            <div className="border-b border-jc-border/90 bg-gradient-to-br from-amber-50/90 via-white to-jc-bg-deep/60 px-5 py-6 sm:px-8">
              <h3 className="font-display text-2xl font-semibold text-jc-ink sm:text-[1.65rem]">Find Products</h3>
              <p className="mt-1 text-sm text-jc-muted">Search by product code or name — enter quantity and book.</p>
            </div>

            {/* Search bar */}
            <div className="relative px-5 py-5 sm:px-8">
              <div className="flex gap-1 rounded-2xl border-2 border-jc-border bg-white p-1 shadow-sm transition focus-within:border-jc-brand focus-within:shadow-md focus-within:ring-4 focus-within:ring-jc-brand/10">
                <span className="flex w-11 shrink-0 items-center justify-center text-lg opacity-60" aria-hidden>🔍</span>
                <input
                  value={shopQ}
                  onChange={(e) => { setShopQ(e.target.value); setSuggestOpen(true); }}
                  onFocus={() => setSuggestOpen(true)}
                  onBlur={() => setTimeout(() => setSuggestOpen(false), 180)}
                  onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void runSearch(); } }}
                  placeholder="Item code or product name…"
                  autoComplete="off"
                  className="min-w-0 flex-1 border-0 bg-transparent py-3 pr-2 text-sm outline-none ring-0 placeholder:text-jc-muted/50"
                />
                <button type="button" onClick={() => void runSearch()} disabled={searching}
                  className="shrink-0 rounded-xl bg-jc-brand px-5 py-2.5 text-sm font-semibold text-white shadow-md transition hover:bg-jc-brand-light disabled:opacity-50">
                  {searching ? "…" : "Search"}
                </button>
              </div>
              {suggestOpen && suggestions.length > 0 && (
                <ul className="absolute left-5 right-5 top-full z-20 -mt-2 max-h-52 overflow-auto rounded-xl border border-jc-border bg-white py-1 shadow-jc-lg sm:left-8 sm:right-8">
                  {suggestions.map((s) => (
                    <li key={s.catalog_product_id}>
                      <button type="button" className="w-full px-4 py-2.5 text-left text-sm hover:bg-jc-bg"
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => { setShopQ(s.our_product_id); setSuggestOpen(false); setSuggestions([]); }}>
                        <span className="font-medium text-jc-ink">{s.our_product_id}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              {searchErr && <p className="mt-3 text-sm text-red-700">{searchErr}</p>}
            </div>

            {/* Empty state */}
            {!didSearch && !searching && (
              <div className="mx-5 mb-8 flex flex-col items-center rounded-2xl border border-dashed border-jc-border/90 bg-gradient-to-b from-jc-bg/80 to-white px-6 py-10 text-center sm:mx-8">
                <span className="text-4xl" aria-hidden>🛍️</span>
                <p className="mt-4 font-display text-lg font-semibold text-jc-ink">Start with a search</p>
                <p className="mt-2 max-w-sm text-sm text-jc-muted">Type a product code or name, then tap Search.</p>
              </div>
            )}

            {/* Loading skeletons */}
            {searching && (
              <div className="grid gap-6 px-5 pb-8 sm:grid-cols-2 sm:px-8">
                {[0, 1, 2, 3].map((i) => (
                  <div key={i} className="animate-pulse overflow-hidden rounded-3xl border border-jc-border/60 bg-jc-bg-deep/30">
                    <div className="aspect-square bg-jc-bg-deep/50" />
                    <div className="space-y-3 p-5">
                      <div className="h-4 w-3/4 rounded-lg bg-jc-border/90" />
                      <div className="h-4 w-1/3 rounded-lg bg-jc-border/80" />
                      <div className="h-9 w-full rounded-xl bg-jc-border/70" />
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Results — big card layout */}
            {results.length > 0 && !searching && (
              <div className="grid gap-6 px-5 pb-8 sm:grid-cols-2 sm:px-8">
                {results.map((p) => {
                  const canOrder = p.stock_status !== "out_of_stock";
                  const busy = bookingId === p.catalog_product_id;
                  return (
                    <article key={p.catalog_product_id}
                      className="flex flex-col overflow-hidden rounded-3xl border border-jc-border/90 bg-white shadow-jc ring-1 ring-black/[0.04] transition hover:shadow-jc-lg">
                      {/* Product image — large */}
                      <div className="relative aspect-square w-full bg-gradient-to-b from-jc-bg-deep to-jc-bg/80">
                        {p.image_url ? (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img src={p.image_url} alt={p.our_product_id}
                            className="h-full w-full object-contain object-center p-3" />
                        ) : (
                          <div className="flex h-full min-h-[160px] flex-col items-center justify-center gap-2 text-jc-muted">
                            <span className="text-4xl opacity-35" aria-hidden>✨</span>
                            <span className="text-sm">Photo coming soon</span>
                          </div>
                        )}
                        <span className={`absolute right-3 top-3 rounded-full px-3 py-1 text-xs font-semibold ring-1 ${stockPillClass(p.stock_status)}`}>
                          {stockLabel(p.stock_status)}
                        </span>
                      </div>

                      {/* Card body */}
                      <div className="flex flex-1 flex-col gap-3 p-5">
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <p className="font-display text-lg font-semibold leading-snug text-jc-ink">{p.our_product_id}</p>
                          <div className="text-right">
                            <span className="block text-[10px] font-semibold uppercase tracking-wider text-jc-muted">Price</span>
                            <span className="text-xl font-bold tabular-nums text-jc-brand">₹{p.selling_price}</span>
                          </div>
                        </div>
                        <p className="line-clamp-2 text-xs leading-relaxed text-jc-muted">{availHint(p.stock_status)}</p>

                        {/* Qty + Book */}
                        <div className="mt-auto flex flex-wrap items-end gap-3 border-t border-jc-border/60 pt-4">
                          <label className="block text-sm font-medium text-jc-ink">
                            Qty
                            <input type="number" min={1} max={MAX_QTY}
                              value={qtyDraft[p.catalog_product_id] ?? "1"}
                              onChange={(e) => setQtyDraft((prev) => ({ ...prev, [p.catalog_product_id]: e.target.value }))}
                              className="mt-1.5 w-24 rounded-xl border border-jc-border bg-jc-bg/30 px-3 py-2 text-sm shadow-inner"
                            />
                          </label>
                          <button type="button" disabled={!canOrder || busy}
                            onClick={() => startBook(p, qtyDraft[p.catalog_product_id] ?? "1")}
                            className="rounded-xl bg-jc-accent px-5 py-2.5 text-sm font-semibold text-white shadow-md transition hover:bg-jc-accent-hover disabled:cursor-not-allowed disabled:bg-neutral-300">
                            {busy ? "Booking…" : "Book Now"}
                          </button>
                        </div>
                      </div>

                      {/* Alternatives */}
                      {p.alternatives.length > 0 && (
                        <div className="border-t border-jc-border bg-jc-bg/50 px-5 py-4">
                          <p className="text-xs font-bold uppercase tracking-wide text-jc-muted">Similar in stock</p>
                          <ul className="mt-3 grid grid-cols-3 gap-2">
                            {p.alternatives.map((a) => (
                              <li key={a.catalog_product_id}
                                className="flex flex-col overflow-hidden rounded-xl border border-jc-border bg-white p-2 shadow-sm">
                                <div className="aspect-square w-full overflow-hidden rounded-lg bg-jc-bg-deep/40">
                                  {a.image_url ? (
                                    // eslint-disable-next-line @next/next/no-img-element
                                    <img src={a.image_url} alt="" className="h-full w-full object-contain object-center p-1" />
                                  ) : (
                                    <div className="flex h-full min-h-[72px] items-center justify-center text-[10px] text-jc-muted">—</div>
                                  )}
                                </div>
                                <p className="mt-1.5 truncate text-center text-[10px] font-semibold text-jc-ink">{a.our_product_id}</p>
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

            {/* No results */}
            {didSearch && !searching && results.length === 0 && !searchErr && (
              <div className="mx-5 mb-8 flex flex-col items-center rounded-2xl border border-jc-border bg-jc-bg/40 px-6 py-10 text-center sm:mx-8">
                <span className="text-3xl" aria-hidden>🔎</span>
                <p className="mt-3 font-display text-base font-semibold text-jc-ink">No matches</p>
                <p className="mt-2 max-w-sm text-sm text-jc-muted">Try a different code or name.</p>
              </div>
            )}
          </div>
        )
      ) : (
        /* ── MY ORDERS TAB ── */
        <div className="overflow-hidden rounded-3xl border border-jc-border/80 bg-white shadow-jc-lg">
          <div className="flex items-center justify-between border-b border-jc-border/60 bg-jc-bg/30 px-6 py-5">
            <h3 className="font-display text-xl font-semibold text-jc-ink">My Orders</h3>
            <button type="button" onClick={() => token && void loadMyOrders(token, statusFilter)}
              className="rounded-xl border border-jc-border bg-white px-4 py-2 text-xs font-semibold text-jc-muted transition hover:bg-jc-bg">
              Refresh
            </button>
          </div>
          <div className="p-6">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold uppercase tracking-wide text-jc-muted">Filter</span>
              <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}
                className="rounded-xl border border-jc-border bg-white px-4 py-2 text-sm text-jc-ink shadow-sm">
                <option value="">All</option>
                <option value="">All</option>
                <option value="received">Received</option>
                <option value="billed">Billed</option>
                <option value="closed">Closed</option>
              </select>
            </div>
            {ordersErr && <p className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">{ordersErr}</p>}
            {ordersLoading ? (
              <div className="mt-6 space-y-3">
                {[0, 1, 2].map((i) => <div key={i} className="h-24 animate-pulse rounded-2xl border border-jc-border/60 bg-jc-bg-deep/30" />)}
              </div>
            ) : myOrders.length === 0 ? (
              <div className="mt-10 flex flex-col items-center rounded-2xl border border-dashed border-jc-border bg-jc-bg/40 py-14 text-center">
                <span className="text-5xl" aria-hidden>📦</span>
                <p className="mt-4 font-semibold text-jc-ink">No orders yet</p>
                <p className="mt-1 text-sm text-jc-muted">Place an order from the Search tab.</p>
              </div>
            ) : (
              <ul className="mt-5 space-y-4">
                {myOrders.map((o) => (
                  <li key={o.id} className="overflow-hidden rounded-2xl border border-jc-border/80 bg-white shadow-sm">
                    <div className="flex items-center justify-between border-l-4 border-jc-brand bg-jc-bg/30 px-5 py-4">
                      <div>
                        <span className="font-bold text-jc-ink">Order #{o.id}</span>
                        <span className="ml-2 text-xs text-jc-muted">{fmtDateTime(o.created_at)}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className={`rounded-full px-3 py-1 text-xs font-bold ${orderBadgeClass(o.status)}`}>
                          {statusLabel(o.status)}
                        </span>
                        <button type="button" onClick={() => printOrderReceipt(o, profile, imageMap)}
                          className="rounded-lg border border-jc-border bg-white px-3 py-1.5 text-xs font-medium text-jc-muted transition hover:bg-jc-bg">
                          🖨 Receipt
                        </button>
                      </div>
                    </div>
                    <div className="divide-y divide-jc-border/50 px-5">
                      {o.items.map((it) => (
                        <div key={it.catalog_product_id} className="flex items-center justify-between py-2.5 text-sm">
                          <div>
                            <span className="font-semibold text-jc-ink">{it.our_product_id}</span>
                            {it.name && <span className="ml-2 text-xs text-jc-muted">{it.name}</span>}
                            {(it as { category?: string }).category && (
                              <span className="ml-1 text-xs text-jc-muted/60">· {(it as { category?: string }).category}</span>
                            )}
                          </div>
                          <span className="tabular-nums text-jc-muted">× {it.quantity} · ₹{it.line_total}</span>
                        </div>
                      ))}
                    </div>
                    <div className="flex items-center justify-between bg-jc-bg/20 px-5 py-3">
                      <span className="text-sm font-bold text-jc-ink">Total ₹{o.total_amount}</span>
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
