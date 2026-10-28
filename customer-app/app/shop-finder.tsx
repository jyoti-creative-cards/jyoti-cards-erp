"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { apiUrl, fetchApi } from "@/lib/api";
import type { ShopSuggestionPublic } from "@/lib/types";

export type ShopSearchOutcome = "ok" | "error" | "stale";

const MAX_ORDER_QTY = 100_000_000;

export function normalizeShopQuery(s: string): string {
  return s.replace(/\u00a0/g, " ").trim().replace(/\s+/g, " ");
}

export function validLot(raw: string): number | null {
  const text = raw.trim();
  if (!/^[0-9]+$/.test(text)) return null;
  const n = Number(text);
  if (!Number.isSafeInteger(n) || n < 50 || n > MAX_ORDER_QTY || n % 50 !== 0) return null;
  return n;
}

export default function ShopFinder({
  token,
  active,
  loadFailed,
  onSearch,
  onInvalidate,
}: {
  token: string;
  active: boolean;
  loadFailed: boolean;
  onSearch: (query: string, qty: number) => Promise<ShopSearchOutcome>;
  onInvalidate: () => void;
}) {
  const [moment, setMoment] = useState<"search" | "qty">("search");
  const [draft, setDraft] = useState("");
  const [committed, setCommitted] = useState("");
  const [qty, setQty] = useState("");
  const [suggestions, setSuggestions] = useState<ShopSuggestionPublic[]>([]);
  const [suggestOpen, setSuggestOpen] = useState(false);
  const [pinTop, setPinTop] = useState(88);
  const [focusSearchTick, setFocusSearchTick] = useState(0);
  const [focusQtyTick, setFocusQtyTick] = useState(0);

  const searchRef = useRef<HTMLInputElement>(null);
  const qtyRef = useRef<HTMLInputElement>(null);
  const qtyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const req = useRef(0);
  const lastSent = useRef("");
  const committedRef = useRef("");
  const onSearchRef = useRef(onSearch);
  const onInvalidateRef = useRef(onInvalidate);
  onSearchRef.current = onSearch;
  onInvalidateRef.current = onInvalidate;
  committedRef.current = committed;

  function clearQtyTimer() {
    if (qtyTimer.current) {
      clearTimeout(qtyTimer.current);
      qtyTimer.current = null;
    }
  }

  function dropInFlight() {
    req.current += 1;
    lastSent.current = "";
    clearQtyTimer();
    onInvalidateRef.current();
  }

  async function fireSearch(n: number, force: boolean) {
    const query = committedRef.current;
    if (!query) return;
    const key = `${query}:${n}`;
    if (!force && key === lastSent.current) return;
    clearQtyTimer();
    lastSent.current = key;
    const id = ++req.current;
    const outcome = await onSearchRef.current(query, n);
    if (req.current !== id) return;
    if (outcome === "ok") qtyRef.current?.blur();
    if (outcome === "error") lastSent.current = "";
  }

  const fireSearchRef = useRef(fireSearch);
  fireSearchRef.current = fireSearch;

  useLayoutEffect(() => {
    const header = document.querySelector("header");
    if (!header) return;
    const apply = () => setPinTop(Math.ceil(header.getBoundingClientRect().height));
    apply();
    const observer = new ResizeObserver(apply);
    observer.observe(header);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!active || moment !== "search") return;
    searchRef.current?.focus({ preventScroll: true });
  }, [active, moment, focusSearchTick]);

  useEffect(() => {
    if (moment !== "qty") return;
    qtyRef.current?.focus({ preventScroll: true });
  }, [focusQtyTick, moment]);

  useEffect(() => {
    if (active) return;
    searchRef.current?.blur();
    qtyRef.current?.blur();
  }, [active]);

  useEffect(() => {
    if (moment !== "qty") return;
    const n = validLot(qty);
    if (n == null) return;
    clearQtyTimer();
    qtyTimer.current = setTimeout(() => {
      void fireSearchRef.current(n, false);
    }, 400);
    return () => clearQtyTimer();
  }, [qty, moment]);

  useEffect(() => {
    if (!active || moment !== "search") {
      setSuggestions([]);
      return;
    }
    const qn = normalizeShopQuery(draft);
    if (!token || qn.length < 1) {
      setSuggestions([]);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(async () => {
      const r = await fetchApi(apiUrl(`shop/products/suggestions?q=${encodeURIComponent(qn)}`), {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await r.json().catch(() => []);
      if (cancelled) return;
      if (!r.ok) {
        setSuggestions([]);
        return;
      }
      setSuggestions(Array.isArray(data) ? (data as ShopSuggestionPublic[]) : []);
    }, 220);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [active, draft, moment, token]);

  function commitItem(raw: string) {
    const q = normalizeShopQuery(raw);
    if (!q) return;
    setDraft(q);
    setCommitted(q);
    committedRef.current = q;
    setQty("");
    setMoment("qty");
    setSuggestOpen(false);
    setSuggestions([]);
    dropInFlight();
    qtyRef.current?.focus({ preventScroll: true });
    setFocusQtyTick((tick) => tick + 1);
  }

  function changeItem() {
    setQty("");
    setMoment("search");
    setSuggestOpen(true);
    dropInFlight();
    searchRef.current?.focus({ preventScroll: true });
    setFocusSearchTick((tick) => tick + 1);
  }

  const lot = validLot(qty);
  const qtyBad = qty.trim() !== "" && lot == null;
  const showSuggestions = moment === "search" && suggestOpen && suggestions.length > 0;

  const fieldClass =
    "h-[4.5rem] w-full rounded-2xl border-2 border-jc-border bg-white px-4 text-2xl font-semibold text-jc-ink outline-none placeholder:text-lg placeholder:font-medium placeholder:text-jc-muted/50 focus:border-jc-brand focus:ring-4 focus:ring-jc-brand/15";
  const parked = "pointer-events-none absolute left-0 top-0 h-px w-px overflow-hidden opacity-0";

  return (
    <div
      className="sticky z-20 border-y border-jc-border/80 bg-white px-5 py-3 shadow-sm sm:px-8"
      style={{ top: pinTop }}
      data-testid="shop-finder"
    >
      <div className={moment === "search" ? "relative" : ""}>
        <input
          ref={searchRef}
          value={draft}
          data-testid="shop-search"
          enterKeyHint="done"
          autoComplete="off"
          autoCorrect="off"
          autoCapitalize="off"
          spellCheck={false}
          placeholder="Item number"
          aria-label="Item number"
          aria-hidden={moment !== "search"}
          tabIndex={moment === "search" ? 0 : -1}
          onChange={(e) => {
            setDraft(e.target.value);
            setSuggestOpen(true);
          }}
          onFocus={() => setSuggestOpen(true)}
          onBlur={() => {
            setTimeout(() => setSuggestOpen(false), 180);
          }}
          onKeyDown={(e) => {
            if (e.key !== "Enter") return;
            e.preventDefault();
            commitItem(draft);
          }}
          className={moment === "search" ? fieldClass : parked}
        />
        {showSuggestions ? (
          <ul className="absolute left-0 right-0 top-full z-30 mt-2 max-h-64 overflow-auto rounded-2xl border border-jc-border bg-white py-1 shadow-jc-lg">
            {suggestions.map((s) => (
              <li key={s.catalog_product_id}>
                <button
                  type="button"
                  className="min-h-12 w-full px-4 py-3 text-left text-lg font-semibold text-jc-ink hover:bg-jc-bg"
                  onPointerDown={(e) => e.preventDefault()}
                  onClick={() => commitItem(s.our_product_id)}
                >
                  {s.our_product_id}
                </button>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
      <div>
        {moment === "qty" ? (
          <div className="mb-2 flex items-center justify-between gap-3">
            <p className="min-w-0 truncate text-lg font-semibold text-jc-ink">{committed}</p>
            <button
              type="button"
              data-testid="shop-change"
              onClick={changeItem}
              className="shrink-0 rounded-xl px-3 py-2 text-base font-semibold text-jc-brand"
            >
              Change
            </button>
          </div>
        ) : null}
        <input
          ref={qtyRef}
          value={qty}
          data-testid="shop-qty"
          inputMode="numeric"
          enterKeyHint="done"
          autoComplete="off"
          placeholder="How many?"
          aria-label="Quantity"
          aria-invalid={qtyBad}
          aria-hidden={moment !== "qty"}
          tabIndex={moment === "qty" ? 0 : -1}
          onChange={(e) => {
            setQty(e.target.value);
            dropInFlight();
          }}
          onKeyDown={(e) => {
            if (e.key !== "Enter") return;
            e.preventDefault();
            const n = validLot(qty);
            if (n == null) return;
            void fireSearchRef.current(n, true);
          }}
          className={moment === "qty" ? fieldClass : parked}
        />
        {moment === "qty" ? (
          loadFailed ? (
            <button
              type="button"
              data-testid="shop-load-error"
              onClick={() => {
                const n = validLot(qty);
                if (n == null) return;
                void fireSearchRef.current(n, true);
              }}
              className="mt-2 w-full rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-left text-sm font-semibold text-red-800"
            >
              Could not load. Try again.
            </button>
          ) : (
            <p className={`mt-2 text-sm ${qtyBad ? "font-semibold text-red-800" : "text-jc-muted"}`} data-testid="shop-qty-hint">
              {qtyBad ? "Use a lot of 50." : "Lots of 50."}
            </p>
          )
        ) : null}
      </div>
    </div>
  );
}
