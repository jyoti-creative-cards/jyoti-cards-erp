# Round 3 audit — Reports / Documents / Share / Staff / Shared UI helpers

Scope: `JC/web/admin/js/{reports,documents,share,staff,table-utils,ui,cache}.js`,
cross-referenced against `JC/backend/app/routers/{reports,staff,share,documents}.py`,
`app/services/{reports,reports_extended,biz_date,permissions}.py`. Investigation
only — no code was modified. Findings below are ordered by severity; each was
traced onclick → JS function → API call → backend behavior before being
included. Items already reported in round 2 (`round2-staff-permissions.md`,
`round2-freight-pdf.md`) are not repeated except where this round's own
verification produced a materially new result (see #1).

**Important environment note:** the working tree currently has *uncommitted*
changes that revert several backend/frontend fixes shipped in commit
`17fcfbc` ("fix(staff/permissions): fix Sell preset, one-time legacy
migration, admin-only expense delete"), including `JC/web/admin/js/staff.js`
itself. Finding #1 below describes the code **as it currently sits on disk**,
which is the reverted (buggy) state, not the fixed state at `HEAD`.

---

## Summary table

| # | Severity | Area | File:Line |
|---|----------|------|-----------|
| 1 | **Critical** | "Sell" role preset is back to granting `vendor_orders.*` instead of `customer_orders.*`/`returns.*` — round 2's fix exists in git history but is reverted by an **uncommitted** working-tree change | `JC/web/admin/js/staff.js:117` |
| 2 | High | "Today" date used by the whole Reports screen is computed from the browser's **UTC** clock, not IST — wrong day for ~5.5h every night | `JC/web/admin/js/reports.js:7` |
| 3 | High | "Stock" role preset grants zero stock permissions (`stock.read`/`stock.write` missing) despite being named "Stock" | `JC/web/admin/js/staff.js:126-129` |
| 4 | High | Date-range picker is shown but has **zero effect** on 3+ report screens whose backend endpoints don't accept a date filter at all (Ledgers→Customers/Vendors/Expenses list, Low-stock) | `JC/web/admin/js/reports.js:260-261, 596-597, 722-780` |
| 5 | Medium-High | Daybook's "Excel" button always exports the full, unfiltered, all-time `sales_bills.xlsx` — unrelated to the single day being viewed and missing purchases/payments/expenses shown on screen | `JC/web/admin/js/reports.js:399, 441-448` |
| 6 | Medium-High | "Buy" preset's hint promises "stock" access but the granted keys omit `stock.read`/`stock.write` | `JC/web/admin/js/staff.js:120-123` |
| 7 | Medium | Shared `TableUtils.sort()` does a string/lexicographic compare for every column, silently mis-sorting any numeric column (`On Hand` qty in Stock, `#` vendor number in Vendors) | `JC/web/admin/js/table-utils.js:33-41` |
| 8 | Medium | P&L screen shows a "Freight paid" line but drops the backend's own `note` explaining it's already counted inside "Expenses" — replaced with a hand-written note that never mentions freight | `JC/web/admin/js/reports.js:700-720` |
| 9 | Low | Routes ledger list never shows the "Due" amount the API already computes (Freight's near-identical list does show it) | `JC/web/admin/js/reports.js:783-793` |
| 10 | Low | Payments report rows have no click-through to the underlying bill/receipt/ledger, unlike every other doc-list report | `JC/web/admin/js/reports.js:470-485` |
| 11 | Low | `DocShare.pdfPath`'s `bill`/`daybook`/`ageing` branches inside `shareFlow()` are dead code — every real caller of those three kinds calls `openPdf` directly with a hand-built path instead | `JC/web/admin/js/share.js:85-92` |

Checked and found OK — see bottom of report.

---

## Finding 1 — CRITICAL: "Sell" preset regression — fixed in git history, reverted on disk

**File:** `JC/web/admin/js/staff.js:114-118`

```114:118:JC/web/admin/js/staff.js
    {
      id: "sell",
      label: "Sell",
      hint: "Customers + selling orders",
      keys: ["customers.read", "customers.write", "vendor_orders.read", "vendor_orders.write", "catalog.read", "addons.read"],
    },
```

This round's brief asked to verify round 2's Critical finding #1 ("Sell" preset grants
`vendor_orders.*`/buying permissions instead of `customer_orders.*`/`returns.*`)
was actually fixed. **It was fixed — commit `17fcfbc` changed line 117 to**
`["customers.read", "customers.write", "customer_orders.read", "customer_orders.write", "returns.read", "returns.write", "catalog.read", "addons.read"]`
**— but the file currently on disk does not contain that fix.** `git diff HEAD --
JC/web/admin/js/staff.js` shows an uncommitted working-tree change that reverts
exactly this line (plus a related whatsapp-notification improvement in `save()`)
back to the pre-fix state. The same uncommitted revert also reappears in
`JC/backend/app/routers/expenses.py` (re-widens `DELETE /expenses/{id}` back to
`finance.write`, undoing round 2 finding #3) and `JC/backend/app/db/session.py`
(re-enables the legacy permission auto-expansion migration on every boot,
undoing round 2 finding #2) — i.e. the entire fix commit's diff is present but
un-applied in the working tree, on both backend and frontend files.

**Symptom (current code):** identical to round 2 finding #1 — any staff account
created or edited with the "Sell" quick-role button today gets buying/vendor-PO
permissions and zero selling-order access, the opposite of what the button
promises.

**Recommended fix:** `git diff HEAD` shows the exact patch already sitting in
the working tree in *reverse*; either discard the uncommitted changes to
`staff.js` (and the sibling backend files) with `git checkout HEAD -- <path>`
per file, or confirm whether this revert was intentional (e.g. a deliberate
rollback in progress) before anything is deployed — right now `main`/`HEAD`
has the fix, but whatever is currently loaded from disk does not.

---

## Finding 2 — HIGH: Reports' "Today" is the browser's UTC calendar day, not IST

**File:** `JC/web/admin/js/reports.js:7`

```7:7:JC/web/admin/js/reports.js
  const today = () => new Date().toISOString().slice(0, 10);
```

`Date.prototype.toISOString()` always returns the **UTC** wall-clock date,
never the local/IST one. This single helper backs every "Today" surface in
the Reports screen: the initial `daybookDate` (line 8), `applyDatePreset("today")`
(lines 90-91, sets `fromDate = toDate = today()`), `setDayToday()` (line 311),
and the fallback base inside `shiftDate()` (line 78) used by the ← / → day
steppers.

The backend's entire `biz_date.py` module exists specifically to avoid this
class of bug — its own docstring warns that a naive UTC-based day boundary
"can put created_at rows near midnight in the wrong calendar day", and
`reports_extended.py`/`reports.py` correctly route every date-ranged query
through `ist_day_bounds_utc`/`ist_range_bounds_utc` (IST midnight → UTC).
The frontend's `today()` never does this conversion.

**Concrete effect:** IST is UTC+5:30. For the first 5 hours 30 minutes of
every IST calendar day (00:00–05:29 IST, i.e. 18:30–23:59 UTC the *previous*
day), `today()` returns **yesterday's** date string. Anyone opening Reports
during that window and clicking "Today" (daybook) or the "Today" date preset
(Sales bills / Purchase bills / Payments / Customer sales / Vendor purchases /
Item sales / Item purchases / Fast-slow movers / GST sales / GST purchases /
Cash book / Expense by category / P&L) is silently shown **yesterday's IST
data mislabeled as today's**, with no indication anything is off — the date
picker itself will even show the (wrong) date correctly reflecting what was
requested, compounding the confusion. This is exactly the scenario
`biz_date.py` was written to prevent, just on the client instead of the
server.

Note this exact anti-pattern (`new Date().toISOString().slice(0, 10)` used as
"today") also appears in `finance.js` and `vendors.js` (outside this round's
scope) — it is a repo-wide habit, not unique to Reports, but Reports is the
screen where it does the most damage since almost every chip is date-scoped.

**Recommended fix:** add an IST-aware `todayIST()` helper (e.g.
`new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" })`, which
returns `YYYY-MM-DD`) and use it everywhere `reports.js` currently calls
`today()`.

---

## Finding 3 — HIGH: "Stock" role preset grants catalog permissions but no stock permissions at all

**File:** `JC/web/admin/js/staff.js:126-130`

```126:130:JC/web/admin/js/staff.js
    {
      id: "stock",
      label: "Stock",
      hint: "Catalog + on-hand",
      keys: ["catalog.read", "catalog.write", "addons.read", "addons.write"],
    },
```

The preset is literally named **"Stock"**, with a hint explicitly promising
"on-hand" visibility, yet its `keys` list contains only `catalog.*`/`addons.*`
(product-definition permissions) — no `stock.read`, no `stock.write`.

Traced against the backend: `GET /stock/products`, `GET /stock/products/{id}`,
and `GET /stock/ledger/{id}` (`app/routers/stock.py:152,271,354`) — the
endpoints that back the Stock screen's product list, product detail, and
stock-ledger views — are all gated on `require_permission("stock.read")`,
with no `catalog.read` fallback. The admin frontend (`stock.js`) never checks
`stock.read`/`stock.write` before rendering (confirmed by grep — zero
matches), so nothing hides the Stock tile or its contents for a staffer
missing that permission; the screen renders normally and every API call
inside it 403s.

**Symptom:** an admin who onboards a warehouse/stock-keeping staffer with the
"Stock" quick-role button (reasonably assuming it does what its own label
says) produces an account that can fully create/edit/delete catalog product
records and add-ons, but cannot view a single stock quantity, cannot open the
stock ledger, and (since receiving/billing against a vendor order also needs
`vendor_orders.*`, which this preset also lacks) cannot receive or bill any
stock either. The one thing named in the button's own hint — "on-hand" — is
the one thing it doesn't grant.

**Recommended fix:** add `"stock.read", "stock.write"` to the `stock` preset's
`keys` (and consider whether it should also carry `vendor_orders.read`/`write`
so a "Stock" role can actually receive/bill against placed orders — as-is,
even with the missing `stock.*` added, this role still can't process a vendor
receipt).

---

## Finding 4 — HIGH: Date-range picker renders and is interactive on report screens whose backend never accepts a date filter

**File:** `JC/web/admin/js/reports.js:260-261` (`noDates` allow-list), `596-597`
(`renderLow`), `722, 731` (`renderLedgers`)

`renderDateBar()` decides whether to show the "Today / 7 days / This month /
All / Custom" preset row + From/To inputs based on an explicit exclusion list:

```260:261:JC/web/admin/js/reports.js
    const noDates = chip === "valuation" || chip === "ageing"
      || (chip === "ledgers" && ["products", "staff", "routes", "freight"].includes(ledgerKind));
```

This list is incomplete. Two real gaps, both traced end-to-end:

**(a) Low stock (`chip === "low"`).** Not in `noDates`, so the full date-preset
UI renders (Today/7 days/This month/All/Custom + From/To). But `renderLow()`
never applies it:

```596:598:JC/web/admin/js/reports.js
  async function renderLow(body) {
    const data = await ctx.api(`/reports/stock/low?threshold=${lowThreshold}`, {}, 0);
```

— no `rangeQs()`. The backend endpoint (`GET /reports/stock/low`,
`app/routers/reports.py:145-151` → `ext.low_stock(db, threshold)`) has no
`from_date`/`to_date` parameter at all; low stock is a point-in-time snapshot
of current on-hand vs. threshold and conceptually can't be date-ranged. A
staffer can click "This month" or type a custom From/To on this screen and
the table never changes — no error, no "not applicable" message, just silent
no-op.

**(b) Ledgers → Customers / Vendors / Expenses** (`chip === "ledgers"`, one of
the three `ledgerKind`s **not** in the exclusion array). The date bar renders,
but `renderLedgers()` calls the same undated endpoint regardless of
`fromDate`/`toDate`:

```722:731:JC/web/admin/js/reports.js
  async function renderLedgers(body) {
    if (ledgerKind === "cash") { ... return; }
    const data = await ctx.api(`/reports/ledgers/${ledgerKind}`, {}, 0);
```

`GET /reports/ledgers/customers` and `GET /reports/ledgers/vendors`
(`app/routers/reports.py:224-243`) accept no date params whatsoever — they're
lifetime aggregates (`list_ledger_customers`/`list_ledger_vendors`), and
drilling into a specific customer/vendor (`openLedger` → `/reports/ledgers/
customers/{id}`) *also* takes no date range, so for these two the date picker
is 100% non-functional end-to-end, at both the list and the detail level.
`ledgerKind === "expenses"` is a softer variant of the same bug: the outer
category-rollup list ignores the date bar exactly the same way, but the
per-category **detail** screen (`openExpenseLedger` → `/reports/ledgers/
expenses/{category}${rangeQs()}`) *does* honor the same `fromDate`/`toDate` —
so the control the user is looking at (above the aggregate table) silently
does nothing, while the identical control does work one click later, on a
different screen, with no visual distinction between the two.

Compare with the chips that get this right immediately next to these ones in
the same "Books" mode — `customer-sales`, `vendor-purchases`, `item-sales`,
`item-purchases` (lines ~487-522) all correctly call `rangeQs()` and the
backend correctly filters — which confirms this is an oversight in the
`noDates` list, not an intentional design choice.

**Recommended fix:** add `chip === "low"` to `noDates`, and change the
ledgers condition to exclude dates for `["products", "staff", "routes",
"freight", "customers", "vendors", "expenses"]` (i.e. every `ledgerKind`
except `cash`, whose own detail screen genuinely uses the range) — or, more
robustly, make each report chip declare `supportsDateRange: bool` once
instead of maintaining a hand-written exclusion list that has to be kept in
sync with every backend endpoint's actual signature.

---

## Finding 5 — MEDIUM-HIGH: Daybook's "Excel" button exports an unrelated, unfiltered, all-time report

**File:** `JC/web/admin/js/reports.js:396-400` (button wiring), `441-448`
(`exportExcel`)

```396:400:JC/web/admin/js/reports.js
      ${DocShare.toolbarHtml({
        printOnclick: "Reports.shareDaybook(true)",
        pdfOnclick: "Reports.shareDaybook(false)",
        waOnclick: "Reports.waDaybook()",
        excelOnclick: "Reports.exportExcel('sales_bills')",
      })}
```

The Daybook screen is scoped to a single IST calendar day (`daybookDate`) and
mixes multiple entry types — sales bills, purchase bills, AR/AP payments,
expenses, freight settlements, credit/debit notes (see `svc.daybook()`,
`app/services/reports.py:250-406`). Its Print/PDF/WhatsApp buttons all
correctly target that one day (`/share/daybook/pdf?day=...`). The Excel
button does not: `exportExcel('sales_bills')` calls
`DocShare.downloadExport('sales_bills')` → `GET /export/sales_bills.xlsx`
(`app/routers/export.py:61-77`), which takes **no date parameter at all** and
always dumps every sales bill ever created (`export_sales_bills`, unfiltered,
all-time).

**Symptom:** a staffer viewing, say, "Daybook — 3 Sep 2026" and clicking
"Excel" (reasonably expecting a spreadsheet of that day's daybook — the same
document the Print/PDF/WhatsApp buttons next to it produce) instead silently
downloads a file named `sales_bills.xlsx` containing the entire lifetime sales
register, with zero rows for that day's purchases, payments, or expenses that
were visible on screen. There is no scope indicator in the download itself
(filename is just `sales_bills.xlsx`, not date-stamped) to reveal the
mismatch.

**Recommended fix:** either remove the Excel button from the Daybook toolbar
(Print/PDF/WhatsApp already cover "share this day"), or wire it to a
day-scoped export — `GET /export/{kind}.xlsx` would need a `from_date`/
`to_date` (or `day`) parameter added server-side for this to be meaningful,
since the endpoint currently supports no filtering for any kind.

*(Secondary, lower-confidence note: the Ageing screen's Excel button —
`Reports.exportExcel('${side}')`, line 530 — has the same "no date filtering
possible" limitation, but is at least topically consistent: it exports the
current full AR/AP ledger while viewing a current-day ageing snapshot, so the
mismatch there is far less surprising than the Daybook case.)*

---

## Finding 6 — MEDIUM-HIGH: "Buy" preset's hint promises stock access it doesn't grant

**File:** `JC/web/admin/js/staff.js:120-124`

```120:124:JC/web/admin/js/staff.js
    {
      id: "buy",
      label: "Buy",
      hint: "Vendors + buying orders + stock",
      keys: ["vendors.read", "vendors.write", "vendor_orders.read", "vendor_orders.write", "catalog.read", "catalog.write", "addons.read", "addons.write"],
    },
```

The hint explicitly says "…+ stock", but (same trace as Finding 3) viewing
stock quantities/ledger requires `stock.read`, which this preset never
grants. Unlike the "Stock" preset, the "Buy" preset's `vendor_orders.write`
does let the resulting staffer actually receive and bill against a vendor
order (those endpoints are gated on `vendor_orders.*`, not `stock.*` —
`app/routers/stock.py:764,786,798`), so the *operational* buying flow works.
But the standalone Stock tile/screen (on-hand quantities, per-product ledger)
— the specific thing the hint calls out — 403s for this role exactly as in
Finding 3.

**Recommended fix:** add `"stock.read"` (and arguably `"stock.write"`, since
the hint says "stock" not "view stock") to the `buy` preset's `keys`.

---

## Finding 7 — MEDIUM: shared `TableUtils.sort()` does a string compare on every column, mis-ordering numeric ones

**File:** `JC/web/admin/js/table-utils.js:33-41`

```33:41:JC/web/admin/js/table-utils.js
    if (s.sort) {
      const col = cols.find(c => c.key === s.sort);
      if (col) {
        out.sort((a, b) => {
          const av = norm(col.get(a));
          const bv = norm(col.get(b));
          const cmp = av < bv ? -1 : av > bv ? 1 : 0;
          return s.dir === "asc" ? cmp : -cmp;
        });
      }
    }
```

`norm()` (line 14-17) is `String(v).toLowerCase()` — every column, regardless
of the underlying value's type, is compared as a string. This is fine for
text columns but silently wrong for any numeric column: string comparison
orders `"10"` before `"2"` (lexicographic, not numeric), so a table with
on-hand quantities `2, 9, 10, 21, 100` sorted "ascending" by this helper comes
out as `10, 100, 2, 21, 9`.

This is not theoretical — two real call sites already feed numeric values
into sortable `TableUtils` columns:

- `JC/web/admin/js/stock.js:37`: `{ key: "qty", label: "On Hand", get: p => String(p.quantity_on_hand) }` — explicitly pre-stringified, so clicking the "On Hand" column header in the Stock table sorts on-hand quantities alphabetically, not numerically.
- `JC/web/admin/js/vendors.js:12`: `{ key: "vendor_number", label: "#", get: v => v.vendor_number || 0, exactNumeric: true }` — the `exactNumeric` flag only affects the *filter* input (`table-utils.js:24-26`, correctly exact-matches digits so "1" doesn't also match "11"); it has no effect on `sort()`, so clicking the "#" column header still string-sorts vendor numbers.

Because `TableUtils` is shared across Stock, Catalog, Add-ons, and Vendors
(all four `register()` this module), any current or future numeric sortable
column in those screens inherits this bug silently — exactly the kind of
"one shared helper, many screens affected" risk this audit round was asked to
hunt for.

**Recommended fix:** let column definitions declare `numeric: true`
(alongside the existing `exactNumeric`/`filterable`/`sortable` flags) and, in
`sort()`, compare `Number(col.get(a))`/`Number(col.get(b))` numerically for
those columns instead of always falling through to `norm()`.

---

## Finding 8 — MEDIUM: P&L screen drops the backend's own double-counting caveat about freight

**File:** `JC/web/admin/js/reports.js:700-720`

```709:719:JC/web/admin/js/reports.js
      ${ctx.reviewRow("Expenses", fmtPrice(data.expenses))}
      ${ctx.reviewRow("Freight paid", fmtPrice(data.freight_paid))}
      ${ctx.reviewRow("Manual losses", fmtPrice(data.manual_losses))}
      ${ctx.reviewRow("Net profit", fmtPrice(data.net_profit))}
      ${ctx.reviewRow("Cash collected", fmtPrice(data.cash_collected))}
      ${ctx.reviewRow("Bill count", data.bill_count)}
    </div>
    <p class="fin-panel-sub" style="margin-top:12px;">Net profit = net sales (ex-GST, net of returns) − net COGS (purchases, net of vendor debit notes) − expenses − manual losses. Still a management approximation, not true inventory-costed accounting.</p>`;
```

The API response (`ext.pnl_detail`, `app/services/reports_extended.py:681-770`)
includes its own `note` field specifically to flag a non-obvious accounting
quirk: `"...Freight settle counted once via expenses (not again via
freight_paid)."` (line 767-768) — because a freight settlement posts an
`Expense` row that is *already* inside the "Expenses" total shown one row
above "Freight paid". The frontend fetches this `data` object but never reads
`data.note`; instead it renders its own hand-written footnote that describes
the sales/COGS/expenses/losses formula but never mentions freight at all.

**Symptom:** a bookkeeper looking at "Expenses ₹X, Freight paid ₹Y, Net profit
₹Z" with a note that says "Net profit = ... − expenses − manual losses" (no
mention of freight) has no way to know from the UI whether "Freight paid" is
included in, or separate from, "Expenses" — and if they try to hand-check the
arithmetic assuming it's a fifth separate deduction, the numbers won't
reconcile, with nothing on screen explaining why.

**Recommended fix:** render `data.note` (or fold its wording into the
existing footnote) instead of the current hardcoded string, so the freight
caveat the backend already computed is actually shown to the person reading
the P&L.

---

## Finding 9 — LOW: Routes ledger list never shows the amount actually due

**File:** `JC/web/admin/js/reports.js:783-793`

```783:793:JC/web/admin/js/reports.js
    const isRoute = ledgerKind === "routes";
    const isFreight = ledgerKind === "freight";
    body.innerHTML = items.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
      <th>Name</th>
      <th>${isRoute ? "Customers" : isFreight ? "Due" : "Opening"}</th>
      ${!isRoute && !isFreight ? "<th>Due</th>" : ""}
    </tr></thead><tbody>
      ${items.map(it => `<tr class="clickable" onclick="Reports.openLedger('${ledgerKind}', ${it.id})">
        <td><strong>${ctx.esc(it.label)}</strong></td>
        <td>${isRoute ? (it.customer_count ?? 0) : isFreight ? `<strong>${fmtPrice(it.outstanding)}</strong>` : fmtPrice(it.opening_total)}</td>
        <td>${isRoute ? (it.customer_count ?? 0) : isFreight ? `<strong>${fmtPrice(it.outstanding)}</strong>` : fmtPrice(it.opening_total)}</td>
      </tr>`).join("")}
```

`list_ledger_routes` (`app/services/reports_extended.py:927-937`) computes and
returns `outstanding` (sum of customer dues on that route) for every route,
same as it does for freight agents. But the Routes list only ever renders
`customer_count` — the "Due" column that Freight gets (a single relabeled
stat column) is simply never given to Routes, so the one number most likely
to matter when triaging routes ("which route has the most money outstanding")
is only visible after clicking into a route's detail page.

**Recommended fix:** give Routes the same treatment as Freight — a second
column (or the same relabeled single column) showing `fmtPrice(it.outstanding)`.

---

## Finding 10 — LOW: Payments report has no click-through, unlike every sibling doc list

**File:** `JC/web/admin/js/reports.js:470-485`

`renderDocList` (Sales bills / Purchase bills) attaches
`onclick="Reports.openDoc(...)"` to every row. `renderPayments` — the
"Payments" chip right next to them under "Today" — renders a plain, non-
clickable `<tr>` for every AR/AP/freight payment row, with no way to jump to
the underlying customer/vendor ledger or payment document from this screen,
even though `party_id` is present in the API response
(`app/services/reports.py:187-244`) and would be enough to route to
`Reports.openLedger('customers'|'vendors', party_id)`. Minor — likely just an
oversight rather than a functional break — but inconsistent with the rest of
the "Today" mode's rows.

---

## Finding 11 — LOW: dead code — three `DocShare.pdfPath` branches are unreachable via `shareFlow`

**File:** `JC/web/admin/js/share.js:85-92`

```85:92:JC/web/admin/js/share.js
  function pdfPath({ kind, id, day, side }) {
    if (kind === "bill") return `/share/bills/${id}/pdf`;
    if (kind === "ar_statement") return `/share/statements/ar/${id}/pdf`;
    if (kind === "ap_statement") return `/share/statements/ap/${id}/pdf`;
    if (kind === "freight_statement") return `/share/statements/freight/${id}/pdf`;
    if (kind === "freight_payment") return `/share/freight-payments/${id}/pdf`;
    if (kind === "daybook") return `/share/daybook/pdf?day=${encodeURIComponent(day)}`;
    if (kind === "ageing") return `/share/ageing/pdf?side=${encodeURIComponent(side || "ar")}`;
    finally
```

A repo-wide search for `DocShare.shareFlow(` (the only caller of `pdfPath`)
finds five call sites — all in `finance.js` — using only
`ar_statement`/`ap_statement`/`freight_statement`/`freight_payment`. Every
caller that needs `bill`/`daybook`/`ageing` (all inside `reports.js` and the
bill-viewing screens) calls `DocShare.openPdf()` directly with a hand-built
URL instead of going through `shareFlow`/`pdfPath`. Not a bug (the paths are
correct if ever exercised), just latent/untested code — worth trimming or,
if `shareFlow`'s nicer three-button "Print / Download / WhatsApp" sheet was
meant to eventually replace the bespoke daybook/ageing button rows in
`reports.js`, worth finishing that migration instead.

---

## Checked and found OK (no bug found)

- **Documents.js write-gating (`canWrite()` = `isAdmin()`) matches the backend
  exactly** — every mutating endpoint in `documents.py` (`upload`, `folder`,
  `rename`, `move`, `delete`) *and* the read endpoint (`browse_documents`)
  are all `require_admin`-only, and the frontend correspondingly only shows
  the "Documents" tile at all when `isAdmin()` (`app.js:79`) — no staff
  account can reach a 403 dead-end here.
- **Reports tile visibility matches backend exactly** — every single endpoint
  in `reports.py` is `require_admin`-only (no staff-permission variant
  exists for any report), and `app.js:63` correctly hides `more-tile-reports`
  unless `isAdmin()`. Same for `setup-tile-staff` (staff management) vs.
  `staff.py`'s all-`require_admin` router.
- **`Reports.openDoc` doc-type dispatch**: the only two `doc_type` values the
  backend ever emits into a clickable report row (`"sales_bill"` from
  `list_sales`, `"purchase_bill"` from `list_purchases`,
  `app/services/reports.py:124,163`) are both handled correctly by
  `openDoc()` (`reports.js:927-930`), routed to `CustomerOrders.openBillDoc`
  and `Stock.openReceiptDetail` respectively, with the id field (`b.id` /
  `e.receipt_id or e.id`) matching what each opener expects.
- **GST purchase register's "not captured yet" disclaimer** (`reports.js:645`)
  matches the backend's own reasoning (`gst_purchase_register`'s docstring
  and hardcoded `gst_enabled: False`) verbatim in substance.
- **`fmtPrice()` (reports.js:69-75)**: handles `null`/`""`/`NaN`/negative
  values correctly (renders `—`, and a leading `-₹` rather than `₹-` for
  negatives) — no edge-case bug found across the ~40 call sites in this file.
- **`Cache`/`ctx.api()` TTL usage**: every single `ctx.api(...)` call in
  `reports.js`, `staff.js`, and `documents.js` passes `ttl = 0` (no caching),
  so none of the staleness/race concerns that a TTL cache could introduce
  apply to this module — reports always hit the network fresh.
- **`TableUtils.apply()`'s `exactNumeric` filter path** (line 24-26) is
  correctly implemented — `"1"` filtering an ID column does not also match
  `"11"`/`"111"`, per its own comment; the bug in Finding 7 is isolated to
  `sort()`, not `apply()`'s filtering.
- **Staff wizard/edit form pre-fill**: `openEdit()` (`staff.js:214-230`)
  correctly pre-fills name, phone, and the full permission checklist (via
  `permCheckboxes(s.permissions)`) from the staff record being edited; no
  stale-state leak between opening the "New Staff" wizard and an "Edit"
  wizard was found (`editingId` is reset to `null` in both `openWizard()`
  and `closeModal()`).
- **Permission checklist completeness**: every key in
  `ALL_STAFF_PERMISSIONS` (`app/services/permissions.py`) has a
  corresponding checkbox rendered by `permCheckboxes()` (which iterates
  `permGroups`, itself fetched live from `GET /staff/permissions` — not a
  hardcoded frontend list), so the checklist can never drift out of sync
  with the backend's permission set, and no extra/phantom checkboxes exist.
