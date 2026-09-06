# JC ERP — Finance (AP/AR/Expenses/Reports/Dashboard) Functional Audit — Round 2

Scope: `JC/backend/app/routers/{finance,accounts_payable,accounts_receivable,dashboard,expenses,reports,stock,customers,vendors}.py`,
`JC/backend/app/services/{ap_ledger,ar_ledger,ledger,finance_overview,dashboard,reports,reports_extended,cost_visibility,money,permissions,biz_date,freight_ledger,doc_gen}.py`,
`JC/web/admin/js/{finance,vendors,dashboard,reports,customer-orders,vendor-orders}.js`.

Investigation only — nothing changed in the codebase.

---

## CRITICAL

### C1. Vendor receipt/placement PDFs leak raw `buying_price` to staff without `costs.read`

- **Files/lines:**
  - `JC/backend/app/services/doc_gen.py:223-224` (`generate_vendor_placement_document` — `"unit_price": format(ln.buying_price, "f")`, `"line_total": format(Decimal(str(ln.buying_price)) * ln.quantity, "f")`)
  - `JC/backend/app/services/doc_gen.py:267,277-278` (`generate_vendor_receipt_document` — same pattern, `line_amt_str` and `"unit_price"`)
  - `JC/backend/app/routers/stock.py:929-953` (`GET /stock/receipts/{receipt_id}/document`, gated by `require_permission("vendor_orders.read")` only — no `costs.read` check — and it **regenerates the PDF fresh on every call**, line 940)
  - Contrast: `JC/backend/app/routers/stock.py:960-980` (`GET /stock/receipts/{receipt_id}/lines`, same permission, correctly calls `hide_cost(...)`)

- **Symptom:** The app's whole point of `cost_visibility.py` / the `costs.read` permission is that buying price (our cost) is hidden from staff unless explicitly granted. That redaction is applied correctly in every JSON ledger/list endpoint (`build_ap_ledger`, `build_vendor_ledger`, `get_receipt_lines`, catalog list, debit notes, etc.) — but the "Bill Receipt" PDF (opened from the vendor ledger's "Bill Receipt" button in `vendors.js`/`vendor-orders.js`, and the vendor order placement PDF) is generated in `doc_gen.py` straight from `StockReceiptLine.buying_price` / `VendorOrderLine.buying_price` with **no `hide_cost()` call at all**. Any staff member with only `vendor_orders.read` (a common, low-privilege permission — doesn't imply `costs.read`) can open this PDF and see the exact per-unit cost paid to every vendor for every line, completely bypassing the redaction system the rest of the app enforces.
- **Fix:** In `doc_gen.py`, thread `auth`/`can_see_cost(auth)` into `generate_vendor_receipt_document` and `generate_vendor_placement_document` and replace the raw `unit_price`/`line_total` with `hide_cost(...)` (or a PDF-appropriate `"—"`/omitted column) when the requesting actor lacks `costs.read`. Since the PDF is cached via `document_key` and reused, either generate a per-permission variant or force `costs.read` to view the artifact.

### C2. AR outstanding balance + credit limit leak through the customer directory, bypassing `ar.read`

- **Files/lines:**
  - `JC/backend/app/routers/customers.py:118-172` (`_to_public_many` — unconditionally computes `outstanding_map`/`outstanding_val` and passes it into every `CustomerPublic` row)
  - `JC/backend/app/routers/customers.py:60-90` (`_row_to_public` — always sets `outstanding_balance`, `available_credit` from whatever was passed in, no permission check)
  - `JC/backend/app/routers/customers.py:203` (`GET /customers` gated only by `require_permission("customers.read")`)
  - `JC/web/admin/js/customer-orders.js:2331-2344` (customer-order wizard renders "Outstanding: ₹X / Credit Limit / Available" straight from `GET /customers/{id}`)
  - Contrast: `JC/backend/app/schemas/vendor.py` / `app/routers/vendors.py` — `VendorPublic` has **no** `outstanding` field at all; AP outstanding is never returned by `/vendors`. This asymmetry is strong evidence the AR leak is an oversight, not a deliberate parity decision.

- **Symptom:** The app has a dedicated `ar.read`/`ar.write` permission specifically so that only accountant-type staff can "See customer outstanding, ledger & statements" (per `permissions.py`'s own description). But `GET /customers` and `GET /customers/{id}` — reachable by anyone with plain `customers.read` (needed just to see the customer directory) or by any order-taking staffer via the customer-order wizard — return the exact AR `outstanding_balance` and `available_credit`/`credit_limit` for every customer, with zero `ar.read` gate. A sales/order-taking staffer who was deliberately never granted AR visibility can see every customer's exact dues just by opening the customer picker. This also undermines the explicit "entry-only... never reveals outstanding/totals" guarantee documented in `accounts_receivable.py`'s `record_customer_payment` — that guarantee is moot if the same staffer can see the number one screen over.
- **Fix:** Gate `outstanding_balance`/`available_credit`/`credit_limit` in `_row_to_public` behind `auth.has("ar.read") or auth.has("ar.write") or auth.is_admin`, returning `None` (or a "credit-limit only" boolean like "over limit: yes/no" if order-blocking logic needs it) otherwise. If the credit-limit check itself is needed by order-taking staff, expose a narrower endpoint/field (e.g., `over_credit_limit: bool`) instead of the raw outstanding figure.

---

## HIGH

### H1. AP vendor statement subtotals silently stop adding up to Outstanding after a bill edit

- **Files/lines:**
  - `JC/backend/app/services/ap_ledger.py:380-412` (`vendor_ap_totals` — `bill_total` sums only `entry_type == "bill"` rows; `outstanding` sums **all** rows including `adjustment`)
  - `JC/backend/app/services/ap_ledger.py:600-654` (`list_ap_vendors` — same gap: `bill_sum` aggregate only cases on `entry_type == 'bill'`)
  - `JC/backend/app/services/receipt_edit.py:376-386` (editing a received bill posts a compensating `entry_type="adjustment"` row via `sync_receipt_bill_ledger` rather than mutating the original `bill` row — by design, to preserve history, per the comment in `ap_ledger.py:170` "never mutate / delete prior money history")
  - `JC/web/admin/js/finance.js:874-878` (vendor AP detail renders `Opening + Total bills + Bill corrections − Paid` as if it should reconcile to Outstanding)

- **Symptom:** Editing a receipt's bill (correcting the total, GST, or additional charges after the vendor's actual invoice arrives — a completely normal, frequent accountant task) posts a new `adjustment` ledger row instead of updating the `bill` row. `outstanding` (which sums every row type) correctly reflects the correction, but the displayed "Total bills" breakdown does not — it only ever sums original `bill` rows. So on the vendor statement screen, `Opening + Bills + Debit-note corrections − Paid` will not equal the displayed `Outstanding` whenever any bill on that vendor was ever corrected post-receipt, with no line item anywhere explaining the gap. To a non-technical accountant this reads as "the numbers don't add up" — exactly the class of bug called out in the audit brief.
- **Fix:** Either (a) include `entry_type == "adjustment"` rows whose `reverses_entry_id` points at a `bill` entry inside `bill_total` (mirroring how `debit_note_total` already folds in DN-reversing adjustments), or (b) add an explicit "Corrections" subtotal so the breakdown is complete and reconciles to `outstanding`.

### H2. Cost-redaction placeholder ("—") silently becomes a fake ₹0 in the vendor-order wizard

- **Files/lines:**
  - `JC/backend/app/routers/catalog.py:140,343` (`buying_price=hide_cost(...)` → returns the string `"—"` for staff without `costs.read`)
  - `JC/web/admin/js/vendor-orders.js:1832-1837` (`wizardCartTotal()` — `Number(p.buying_price) || 0`)
  - `JC/web/admin/js/vendor-orders.js:1998,2104` (footer renders `"N items · est. " + fmtPrice(wizardCartTotal())`)
  - `JC/web/admin/js/vendor-orders.js:2008,2023,2028` (Review step: per-line "Buy price"/"Line" columns use the same `Number(p.buying_price) || 0` pattern)

- **Symptom:** For a staff member with `vendor_orders.write` but not `costs.read`, the catalog API correctly returns `buying_price: "—"`. The vendor-order placement wizard then does `Number("—") || 0`, which evaluates to `0` — not `NaN`/blank. The wizard footer and the final "Review & Place" screen therefore show a fully-formed, real-looking total like **"5 items · est. ₹0"** and a "Buy price: ₹0 / Line: ₹0" table, instead of an honest "—" placeholder. This is exactly the failure mode called out in the audit brief: the redaction placeholder breaks downstream arithmetic and renders as a plausible (wrong) number rather than an obvious redaction. It doesn't corrupt any stored data (the backend computes real totals independently), but it actively misleads the staff member placing the order about how large an order they're committing to.
- **Fix:** Treat non-numeric `buying_price` as "unknown", not `0` — e.g. `const raw = p?.buying_price; const price = (raw != null && raw !== "—" && !Number.isNaN(Number(raw))) ? Number(raw) : null;` and render "est. —" / omit the column when any line price is unknown, rather than silently substituting 0.

---

## MEDIUM

### M1. Home "Cash out today" and Finance "Cash out" use different formulas

- **Files/lines:**
  - `JC/backend/app/services/dashboard.py:66-71` (`cash_out_raw` — sums only `jc_ap_ledger_entries` payment/payment_reversal rows for today; today's `Expense` rows are not included)
  - `JC/backend/app/services/finance_overview.py:73-77` (`cash_out = (expense_total + ap_paid)` — includes expenses)

- **Symptom:** Both screens use the label "Cash out" (Home's pulse bar vs. Finance's cash pulse), but Home's "today" figure excludes any expense recorded that day while Finance's headline figure always includes expenses. An accountant who logs a large rent/salary expense today will see Home under-report today's cash-out relative to what Finance shows for the same period, with no indication the two numbers are computed differently.
- **Fix:** Add today's `Expense.amount` sum (IST-bounded) into `cash_out_raw` in `build_dashboard`, matching `finance_overview`'s definition, or relabel one of the two to make the scope difference explicit (e.g. "Vendor payments today" vs. "Cash out today").

### M2. Freight dues rely on an unverified cache; the "integrity" check can't catch drift

- **Files/lines:**
  - `JC/backend/app/services/freight_ledger.py:242-267` (`list_freight_agents_dues` / `freight_dues_total` — read `FreightAgent.balance_due`, a cached column, not a live `SUM(FreightLedgerEntry.amount)`)
  - `JC/backend/app/services/freight_ledger.py:270-278` (`reconcile_all_freight_balances` — a manual repair job that exists specifically because this cache can drift)
  - `JC/backend/app/services/money.py:61-95` (`assert_dues_consistent` — for freight, only compares `dues_snapshot` vs. `finance_overview` vs. `list_freight_agents_dues`, all three of which read the **same** cached `balance_due`; it never compares against a live ledger `SUM`)

- **Symptom:** AR and AP dues (`ar_dues_total`, `ap_dues_total`) are always computed with a live `SUM(amount) ... GROUP BY` straight from the ledger table, so they can never drift from ground truth. Freight dues instead read a cached column that is only kept correct by every write path remembering to call `recompute_balance_due()`. If any future code path (a migration, an admin data fix, a new feature) writes a `FreightLedgerEntry` without calling that helper, the Home/Finance freight-due figure will silently go stale — and the app's own `/finance/dues/integrity` check would still report "ok" because it only cross-checks the cache against itself, not against the ledger.
- **Fix:** Either compute `freight_dues_total()` with a live `SUM(FreightLedgerEntry.amount) ... HAVING > 0` like AR/AP (dropping the cache, or using it only as a display optimization), or add a real check to `assert_dues_consistent` that compares cached `balance_due` per agent against a fresh ledger `SUM` for that agent.

### M3. Vendor ledger Cash/Bank filter drops payments with no recorded mode; no equivalent filter exists for AR

- **Files/lines:**
  - `JC/web/admin/js/vendors.js:100-103` (`payModeBucket` — returns `null` when `payment_mode` is falsy, not `"cash"` or `"bank"`)
  - `JC/web/admin/js/vendors.js:310-313` (filter: `payments.filter(e => payModeBucket(...) === vendorPayModeFilter)` — a `null` bucket never matches `"cash"` or `"bank"`)
  - No equivalent filter exists in the customer/AR ledger UI, despite `ArLedgerEntry.payment_mode` existing on the backend (`ar_ledger.py:300`, `build_ar_ledger`)

- **Symptom:** Any AP payment recorded without a payment mode (legacy payments from before the payment-modes feature existed, or ones recorded while zero active payment modes were configured) is invisible under both the "Cash" and "Bank" filter chips — it only shows under "All", with no "Unknown/Other" bucket to fall back on. An accountant reconciling a bank statement by clicking the "Bank" chip will silently miss real bank payments that happen to have no mode tagged, and have no way to know rows are missing. Separately, the same cash/bank split exists on the backend for customer (AR) payments but the customer ledger screen has no matching filter UI at all — an inconsistency between the two otherwise-symmetric AP/AR ledger views.
- **Fix:** Add an explicit "Unknown" bucket (or fold untagged payments into whichever filter is active with a visible "±N untagged" note) instead of silently dropping them; consider adding the same Cash/Bank filter to the customer ledger for parity.

### M4. No upper bound on payment amount vs. outstanding — riskiest exactly where staff can't see the number

- **Files/lines:**
  - `JC/backend/app/schemas/accounts_payable.py:68` / `JC/backend/app/schemas/accounts_receivable.py:64` (`amount: Decimal = Field(..., gt=0)` — no relation to current outstanding)
  - `JC/backend/app/routers/accounts_payable.py:170-227` (`record_vendor_payment` — "entry-only... never reveals outstanding/totals") and `JC/backend/app/routers/accounts_receivable.py:175-236` (`record_customer_payment`, same pattern)

- **Symptom:** `settle_vendor_ap`/`settle_customer_ar` (full `ap.write`/`ar.write` access) and the `finance.write`-only `record_vendor_payment`/`record_customer_payment` "quick entry" endpoints only reject `amount <= 0`; there is no check that `amount` doesn't wildly exceed the outstanding balance. This is low-risk for `ap.write`/`ar.write` staff, who can see the outstanding figure they're paying against before submitting — but the `finance.write`-only "quick entry" flow (`Finance.quickVendorPayment`/`quickCustomerPayment` in `finance.js`, using `prompt()` dialogs) is explicitly designed so that role **never sees the outstanding balance at all**. A typo or duplicate entry (e.g. entering ₹50,000 instead of ₹5,000) can silently flip a vendor/customer account into a large bogus negative balance, with no guardrail and no way for the person entering it to notice, since they have no visibility into what the "correct" ceiling would have been.
- **Fix:** For the entry-only endpoints specifically, add a sanity check (e.g. reject or require a second confirmation if `amount` would exceed `outstanding * 1.1` or similar), or surface a coarse-grained warning band (not the exact figure) back to the quick-entry UI.

---

## LOW

### L1. "To collect" and "To pay" lists are sorted by different criteria

- **Files/lines:** `JC/backend/app/services/ar_ledger.py:422` (`list_ar_customers` sorts alphabetically by `customer_label`) vs. `JC/backend/app/services/ap_ledger.py:708` (`list_ap_vendors` sorts by `outstanding` descending)
- **Symptom:** The AR ("Collect") and AP ("Pay") tabs in Finance are structurally identical UIs, but AR is ordered A→Z while AP is ordered biggest-debt-first. A staff member using both tabs day to day will notice the inconsistency (e.g. expecting the biggest customer due at the top of "Collect" the way it is on "Pay").
- **Fix:** Sort both the same way (outstanding-descending is the more useful default for a "who do I chase first" list).

### L2. Daybook omits manual losses that P&L/Overview include

- **Files/lines:** `JC/backend/app/services/reports.py:250-405` (`daybook` — builds rows from `CustomerBill`, `ApLedgerEntry`, `ArLedgerEntry`, `Expense`, `FreightLedgerEntry`; no `ManualLoss` query anywhere) vs. `JC/backend/app/services/reports_extended.py:733-741` (`pnl_detail` explicitly includes `ManualLoss` in its net-profit math) and `JC/backend/app/services/finance_overview.py:78-81,199-203` (`manual_losses` in `cash_pulse`)
- **Symptom:** If a manual loss (e.g. damaged/expired stock write-off) is recorded on a given day, it shows up in that period's P&L and in the Finance overview's cash pulse, but the same day's Daybook report (Reports → Today) will not list it at all and its day-level cash totals won't reflect it — two "for this day" views of the same money disagree.
- **Fix:** Add a `ManualLoss` row to `daybook()`'s entries (as its own `kind: "manual_loss"`), consistent with how it's already surfaced elsewhere.

---

## Summary table

| # | Severity | One-line |
|---|----------|----------|
| C1 | Critical | Vendor receipt/placement PDFs leak raw buying_price, bypassing `costs.read` |
| C2 | Critical | `/customers` leaks AR outstanding + credit limit, bypassing `ar.read` |
| H1 | High | AP statement subtotals don't reconcile to Outstanding after a bill edit |
| H2 | High | Redacted "—" buying_price becomes a fake ₹0 total in the vendor-order wizard |
| M1 | Medium | Home "Cash out today" excludes expenses; Finance "Cash out" includes them |
| M2 | Medium | Freight dues trust an unverified cache; integrity check can't detect drift |
| M3 | Medium | Vendor Cash/Bank filter drops untagged payments; no AR equivalent filter |
| M4 | Medium | No payment-amount ceiling, worst where the entry-only role can't see totals |
| L1 | Low | AR/AP due-list sort order inconsistent (alphabetical vs. by amount) |
| L2 | Low | Daybook omits manual losses that P&L/Overview include |
