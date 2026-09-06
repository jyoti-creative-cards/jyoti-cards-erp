# Round 3 audit — Vendor order / vendor / stock FRONTEND correctness

Scope: `JC/web/admin/js/vendor-orders.js`, `vendors.js`, `stock.js` (+ cross-referenced
`debit-notes.js`, `order-menus.js`, and backend routers/services). Investigation only,
no code changed. Findings below are traced end-to-end (onclick → JS function → API call
→ backend behavior) and verified against the current `HEAD` of the repo — Round 2's fixes
(Billed-tab drill-down, masked-price wizard total, dead close-batch/close-placement
endpoints, etc.) are confirmed working and **not** re-reported here.

All `VendorOrders.*` / `Stock.*` / `Vendors.*` onclick references were cross-checked
programmatically against each module's exports — no dangling/undefined-function
button existed anywhere in these three files at the time of this audit.

---

## Critical

### C1. Bill wizard shows "NaN" / silently bills ₹0 for lines when the biller lacks `costs.read`

**Files:**
- `JC/web/admin/js/stock.js:403-411` (`selectPendingReceipt` — new bill)
- `JC/web/admin/js/stock.js:1888-1897` (`openEditReceipt` — edit existing bill)
- Rendered at `JC/web/admin/js/stock.js:590` and `:1052` (`Rate billed` input),
  `:591` and `:1053` (`Amount billed` input)
- Backend acceptance: `JC/backend/app/services/vendor_receive_bill.py:207-208` and
  `:313-314`, `JC/backend/app/services/receipt_edit.py:~290-310`

**What happens:** `buying_price` comes back from the API as the literal string `"—"`
(not `null`, not a number) when the viewer lacks `costs.read` — see
`cost_visibility.hide_cost`. Both `selectPendingReceipt` and `openEditReceipt` seed the
bill-wizard line state directly from `buying_price` without going through any
"masked → unknown" guard (unlike `vendor-orders.js`'s `priceOrNull`, which was added
specifically to fix this exact class of bug for the order-placement wizard — see the
comment at `vendor-orders.js:1840-1848`):

```javascript
// stock.js:403-408 (selectPendingReceipt)
billed_amount: (Number(l.quantity_received) || 0) * (Number(l.buying_price) || 0),
billed_rate: l.buying_price,
```

- `Number("—")` is `NaN`. `NaN || 0` → `0`, so `billed_amount` silently becomes **0**
  for every masked line (looks like a real, submittable value — not blank).
- `billed_rate` is set to the raw string `"—"`. The "Rate billed" input then renders
  `Number("—").toFixed(2)` → the literal text **`"NaN"`** in an editable number input
  (`stock.js:590`, `:1052`), sitting directly next to a "Price" column that correctly
  shows `—` via `fmtPrice` — the inconsistency is visible in the same row.
- The running "Total" footer (`wizardQtySum("billed_amount")`, `stock.js:368`, `:1064`)
  and the review-step "Bill amount" (`calcReviewTotals`) sum these zeros in, so the
  bill preview looks like a plausible, low-but-real total instead of an honest
  "unknown, enter manually" state.

**Why it's Critical, not cosmetic:** these client-computed `billed_rate`/`billed_amount`
values are exactly what gets submitted in `POST /stock/receipts/{id}/bill` and
`PATCH` (edit). Backend only falls back to its own (real, unmasked) `buying_price` when
the client sends `null`/omits the field — `vendor_receive_bill.py:207-208`:
`raw_amt = raw_amt if raw_amt is not None else (ln.buying_price * bq)`. Since the
frontend sends an explicit **`0`**, not `null`, the backend has no signal that this
value is bogus and records `ln.billed_amount = 0` as-is. A staffer who has
`vendor_orders.write` but not `costs.read` (a completely plausible permission
combination — e.g. purchase/warehouse staff barred from margin data) can bill a vendor
order and, unless they manually notice the "NaN" and hand-type every rate, end up
recording **₹0 owed** for real goods received — a genuine AP/accounting data-integrity
bug, not just a display glitch. Same defect on both create (`selectPendingReceipt`) and
edit (`openEditReceipt`) paths.

**Fix:** reuse `priceOrNull`-style handling in `stock.js`: when `buying_price` is not a
finite number, leave `billed_rate`/`billed_amount` `null` (render the inputs blank with
a "Vendor's paper rate — you don't have cost visibility, enter manually" placeholder)
instead of coercing to `0`/`"—"`. Block submit (or force a confirm) if any line still has
a `null` billed_amount when Save is pressed, mirroring `fmtPrice`'s `—` handling used
one column over.

---

## High

### H1. "Received" tab's full vendor-detail page is data-empty — stat pills always 0, no line items

**File:** `JC/web/admin/js/vendor-orders.js`
- Bug source: `openDetail()`, `received` branch, `:828-843` — hardcodes
  `aggregated_lines: []`
- Broken consumers: `renderDetail()`'s `isReceived` branch, `:1020-1029`
  (`Received qty`/`Unbilled` stat pills computed from `aggregated_lines`, always 0;
  `linesForPlacement(p.id)` at `:1031` always returns `[]` so every receipt card shows
  `0 products` and its expand table never renders, `:1034`, `:1039-1041`)
- Dead code left behind by the fix: `renderReceivedExpand` (`:462-486`) is fully
  defined but **never called anywhere** — `grep` confirms zero call sites — it looks
  like the intended renderer for this exact view that never got wired up.

**Trace:** When a user opens a vendor's **Received** bucket from the full detail page
(via "View vendor" on the Received hub card, or `VendorOrders.openDetail(id,'received',vendorId)`),
`openDetail` builds `currentOrder` from `/stock/vendor-order/{vendorId}/received`, but
only maps `receipts` into `placements` — it never populates `aggregated_lines`
(comment at `:826-828` explains *why* a real order id can't be looked up, but the
follow-on data (line items per receipt) was never fetched either). Every other
line-reading helper in this file (`linesForPlacement`, and everything that flows from
it) reads exclusively from `aggregated_lines`, so:
- Stat pills "Received qty" and "Unbilled" always show **0** regardless of real data.
- Every receipt card in the list shows "**0** products" and has no expand — the
  per-product breakdown that Round 2 already fixed for the *Billed* tab's equivalent
  view was never extended to *Received*.

This is the same underlying gap Round 2 fixed for Billed (`build_vendor_billed_detail`)
— **Received** never got the equivalent line-level data, and the leftover
`renderReceivedExpand` function suggests this was the intended fix that didn't land.
Users aren't fully blocked (the receipt's "Edit" button still opens the real line
data via `Stock.openEditReceipt`), which is why this is High rather than Critical, but
the primary "Received" detail screen is misleading/useless for its stated purpose.

**Fix:** extend `stock.py`'s `/vendor-order/{vendor_id}/received` (or add a sibling
endpoint) to return per-line breakdowns like `build_vendor_billed_detail` does, and
either wire `renderReceivedExpand` into `renderDetail`'s `isReceived` branch or drop it
and reuse `linesForPlacement` against the newly-populated `aggregated_lines`.

---

## Medium

### M1. Debit-note "item" preview shows "AP reduces/increases by ₹0" when biller lacks `costs.read`

**File:** `JC/web/admin/js/debit-notes.js:214-238` (`calcEffect`), rendered at
`:240-253` (`updatePreview`)

```javascript
const price = Number(line.buying_price) || 0;   // "—" → NaN → 0
```

For an item-type (quantity mismatch) debit note, `calcEffect()` computes
`price = Number(line.buying_price) || 0`. When `buying_price` is masked (`"—"`), this
silently becomes `0`, so the live preview under the quantity field reads e.g.
**"Short delivery · 3 × ₹0 — AP reduces by ₹0"**, and the confirm-dialog summary
(`review()`, `:269`) repeats the same wrong ₹0 figure — actively misleading about the
financial effect of the note being created.

Unlike C1 above, this **does not corrupt submitted data**: `buildPayload()` for
`note_type: "item"` (`:288-296`) only ever sends `catalog_product_id`/`quantity`/
`direction` — no `amount` field — so the backend recomputes the real (unmasked)
amount server-side. This is a display/preview-only bug, but still a real instance of
the exact "masked price coerced to a confident-looking 0" pattern the codebase has
already fixed elsewhere (`priceOrNull` in `vendor-orders.js`).

**Fix:** mirror `priceOrNull` here too — if `Number(line.buying_price)` isn't finite,
render "Effect unknown — you don't have cost visibility; the real amount will be
calculated when saved" instead of a fabricated ₹0.

### M2. `voidReceipt` uses a bare `prompt()` instead of the app's styled confirm pattern

**File:** `JC/web/admin/js/stock.js:2001-2007`

Every comparable destructive action in `vendor-orders.js` (cancel placement, cancel
pending, close billed shipment, cancel open line, …) goes through
`OrderMenus.openConfirm` / `openConfirmAction`: a styled modal with a details table
(vendor, bill/placement id, amounts) and a *required* reason field, wired to the
shared loading-overlay double-submit guard. `voidReceipt` instead uses a native
`window.prompt()` with no structured context (no bill number, vendor, or amount shown)
and an *optional* reason, despite being one of the more consequential actions in this
file (reverses stock and AP). Functionally it works and is guarded by `ctx.isAdmin?.()`,
so this is a UI-consistency finding, not a correctness bug.

**Fix:** route `voidReceipt` through `OrderMenus.openConfirm` with a details table
(bill/receipt number, vendor, amount) for consistency with every other void/cancel/close
action in the buying flow.

---

## Low

### L1. Entire "Open" bucket UI in `vendor-orders.js` is dead/unreachable code

**File:** `JC/web/admin/js/vendor-orders.js`

`currentBucket` can only ever be one of `PAST_BUCKETS = ["placed","received","billed","cancelled","closed"]`
(`:38`) — `setBucket` clamps to `"placed"` for anything else (`:248`), and
`openDetail` explicitly maps `b === "open"` → `"placed"` (`:792`) and clamps again with
`if (!PAST_BUCKETS.includes(b)) b = "placed"` (`:793`). The global `openOrder` variable
is initialized to `null` and is never populated by any list-fetch (only reassigned
after a `PATCH` in `saveEdit`, `:2272`, which requires `openEditOpenLine` to have already
found a line in `openOrder.lines` — impossible since `openOrder` is never seeded).

As a result, all of the following are unreachable from any current UI path
(confirmed via `grep` — none of these render functions are invoked, and none of these
onclick targets exist outside the dead code itself):
- `renderOpenHubCard`, `renderOpenExpand`, `openKindOf` (`:64`, `:345-398`)
- `renderDetail()`'s `currentBucket === "open"` branch (`:940-970`)
- `closeVendorOpen`, `cancelVendorOpen`, `closeAllOpenLines`, `cancelAllOpenLines`,
  `closeOpenLine`, `cancelOpenLine` (`:1464-1595`)
- `openEditOpenLine`, `closeEdit`, `saveEdit` and the `#vo-edit-modal` markup they drive
  (`:2242-2282`, `JC/web/admin/index.html:926-930`)

(`renderOpenBillExpand`, defined alongside `renderOpenExpand`, is *not* dead — it's
reused by the live "Received" hub card, `:457`.)

This is ~150 lines of maintenance surface with no way to exercise or regression-test it,
and it references backend endpoints (`/vendor-orders/vendor/{id}/open`,
`/vendor-orders/open-lines/{id}/close|cancel`) purely from dead call sites — a future
reader could reasonably think this is live functionality.

**Fix:** delete the dead branch/functions and the `#vo-edit-modal` markup, or if an
"Open" (pre-placement) stage is still planned, wire a real entry point (hub card +
bucket chip) to it.

---

## Summary by severity

| # | Severity | Finding |
|---|----------|---------|
| C1 | Critical | Bill wizard (`stock.js`) coerces masked buying price to `NaN`/`0` and **submits** a ₹0 billed amount for staff without `costs.read`, on both bill-create and bill-edit paths |
| H1 | High | "Received" tab full-page vendor detail is data-empty (`aggregated_lines: []` hardcoded) — stat pills always 0, no per-receipt line items; matching renderer (`renderReceivedExpand`) is dead code |
| M1 | Medium | Debit-note "item" preview shows a fabricated ₹0 effect for masked buying price (display-only, not submitted) |
| M2 | Medium | `voidReceipt` uses a bare `prompt()` instead of the app's shared styled-confirm pattern used everywhere else in buying/stock |
| L1 | Low | ~150 lines of fully unreachable "Open" bucket UI (hub card, detail branch, edit modal, 8 handler functions) in `vendor-orders.js` |

Full report: `/Users/sourabh/Desktop/personal/anshul/.audit-reports/round3-vendor-stock.md`
