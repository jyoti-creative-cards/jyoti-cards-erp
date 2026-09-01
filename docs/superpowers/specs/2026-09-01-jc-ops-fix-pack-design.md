# JC ERP ops fix pack

Date: 2026-09-01
Status: design approved in chat; this file is the signed-off spec
Scope: one backend + admin ship. Six isolated fixes. JC ERP only (`JC/backend/`, `JC/web/admin/`).

This spec is the single implementation-plan input. Do not split into six plans.

## Context / problem

Staff hit six separate ops bugs in daily Buying / Money / Selling work. None needs a new product surface. Each is a small rule or display gap in code that already exists.

1. **Extra collection.** Customer collect and vendor pay reject `amount > outstanding`. Staff often receive or pay more than the books due. That leftover is an advance. The signed ledger already allows negative outstanding; the API does not.
2. **Collection date.** Collect (and AP pay) forms have no date. Ledger rows already have unused `value_date`. Daybook and payment lists filter on `created_at`, so a backdated collection lands on the wrong IST day.
3. **Zero-amount / sample bills.** Billing refuses `selling_price is None or <= 0` with "sell price not set". FOC samples need sell price 0, grand total 0, stock movement, and a printable PDF.
4. **Vendor alias.** Vendor picker and hub labels are `business — city`. Alias exists on `jc_vendors` and is already searched on People. Receive / bill pickers and Buying hub cards omit it, so search misses the name staff actually type.
5. **Vendor stuck in To bill.** Buying Open → To bill is `StockReceipt.bill_status == pending_bill`. After a successful vendor bill the party can still appear there (status not flipped, or hub list stale).
6. **Receive goods purchase rate.** Against-order Receive Goods lines do not reliably show buying price. Offline receive already shows price in the product picker. Staff need the rate on the receive line. No quantity-total footer.

## Goals

- One payment may exceed current due. Extra is advance. Outstanding may go negative. One ledger payment row for the full amount.
- Collect / pay forms accept an IST calendar date, stored as `value_date`, used for ledger display and daybook bucketing.
- A customer bill with sell price 0 and grand total 0 succeeds. Stock still moves. AR posts 0. PDF still prints.
- Vendor search and cards include alias on receive, bill, and Buying hub/list surfaces that currently omit it.
- After a vendor bill saves, that receipt is `billed`. The vendor leaves To bill if they have no remaining `pending_bill` receipts. The Open list refreshes.
- Against-order Receive Goods lines show purchase rate (buying price). Same cost-visibility rules as today.

## Non-goals

- Customer (Selling) to-bill stuck. This pack is Buying vendor to-bill only.
- Total-qty footer on Receive Goods.
- New FOC / sample badge on bill UI or PDF.
- Split payment into "due" + "advance" rows, or a new `advance` entry type on AR/AP.
- Freight settle / freight advance (already a separate flow).
- Standalone "pay when nothing is due" advance when outstanding is already `<= 0`. Extra-as-advance applies only when there is a due and the amount exceeds it.
- Schema migrations. `value_date`, `bill_status`, `alias`, and signed amounts already exist.
- Changing signed-ledger math, `dues_snapshot()`, or IST date-bound helpers.

## Architecture

Six isolated units. One deploy. Shared interfaces only where they already exist.

| Unit | Purpose | Talks to | Does not own |
|---|---|---|---|
| U1 Extra collection | Drop the exceed-due cap on AR/AP settle + record-payment | `post_payment_entry`, signed outstanding | Freight, new entry types |
| U2 Collection date | Date on collect/pay → `value_date` → daybook | `ArSettlementIn` / `ApSettlementIn`, `post_payment_entry`, daybook/payment lists | Bill dates, expense dates |
| U3 FOC bills | Allow sell price 0 and grand total 0 | `customer_bill_process`, order-flow price checks | Catalog price editor UX, FOC badge |
| U4 Vendor alias | Search + show alias on Buying pickers and hub cards | Vendor payloads, `OrdersUI.filterAndRankParties` | Customer alias (already works) |
| U5 To-bill flip | Receipt leaves `pending_bill` after bill; hub reloads | `bill_receipt`, Buying Open list | Customer orders hub |
| U6 Receive rate | Show buying price on against-order receive lines | Placed-order line payload, Receive Goods table | Qty footer, cost-visibility policy |

Each unit can be implemented and tested without the others. Ship together.

Existing conventions stay:

- Money: one signed payment row via `as_signed_decrease`. Outstanding = sum of signed amounts. UI must not re-sum raw rows; use `dues_snapshot()` / existing totals helpers.
- Dates: `created_at` stays real UTC. Report/daybook IST days use `ist_day_bounds_utc` / `ist_range_bounds_utc`.
- Soft delete: ledger aggregates keep `deleted_at is None`.
- Cost visibility: `hide_cost` / `costs.read` unchanged. Receive rate is visible only when the actor can already see buying price (admin or `costs.read`). Staff without that permission still see "—".

## 1. Extra collection (AR + AP)

### Current

`POST /accounts-receivable/customer/{id}/settle` and `.../record-payment` (`JC/backend/app/routers/accounts_receivable.py`) reject `outstanding <= 0` and `amount > outstanding`.

`POST /accounts-payable/vendor/{id}/settle` and `.../record-payment` (`JC/backend/app/routers/accounts_payable.py`) do the same.

`post_payment_entry` in `ar_ledger.py` / `ap_ledger.py` already stores a single negative signed payment. Totals and People cards already color negative outstanding as credit.

Admin collect/pay modals in `JC/web/admin/js/finance.js` do not cap amount client-side. Accountant `record-payment` prompt flows also send a single amount.

### Change

- Keep reject when `outstanding <= 0` (nothing to settle). Same messages as today.
- Keep `amount > 0`.
- Remove the `amount > outstanding` reject on all four endpoints.
- Post **one** payment entry for the full amount. Do not split. Do not add an `advance` entry type.
- After save, outstanding may be negative. That leftover is the advance.
- Same rule for customer collect (AR settle + record-payment) and vendor pay (AP settle + record-payment).
- UI: do not add a client-side max. Optional one-line hint when amount > due: extra will sit as credit. Do not block submit.
- Success copy may show the new outstanding (including negative). Do not invent a second "advance" balance field.

### Files likely touched

- `JC/backend/app/routers/accounts_receivable.py`
- `JC/backend/app/routers/accounts_payable.py`
- `JC/web/admin/js/finance.js` (hint / success outstanding only, if needed)
- Tests under `JC/backend/tests/` (new cases; see Testing)

## 2. Collection date

### Current

`ArSettlementIn` and `ApSettlementIn` have no date field. `post_payment_entry` (AR and AP) does not set `value_date`. Collect and AP pay modals have amount / mode / ref / comment only.

Ledger models already have nullable `value_date`. Bill posting already sets it. Opening balances already set it. Finance ledger UI already prefers `value_date` when present.

Daybook and `list_payments` in `JC/backend/app/services/reports.py` filter and display AR/AP payments by `created_at`. A backdated collection therefore appears on the save day, not the collection day.

### Change

- Add an optional `value_date` (`date`) on `ArSettlementIn` and `ApSettlementIn`.
- Admin collect modal and AP pay modal: date picker, default today IST (`today_ist()` / existing admin `localToday()` equivalent). Required in the form (browser date input, not empty).
- Persist that date as `value_date` on the payment row. `created_at` stays the real UTC save time.
- If the API omits `value_date` (accountant prompt `record-payment`), default to today IST. Do not leave payment `value_date` null for new payments from these four endpoints.
- Reject an unparseable date with HTTP 400. Do not accept a time-of-day; calendar date only.
- Pass `value_date` through `post_payment_entry` (AR and AP). Do not change bill / opening-balance posting.
- Daybook `payment_in` / `payment_out` and `list_payments` AR/AP payment rows: include a row on the IST day of `value_date` when set, else `created_at`. Keep using `ist_day_bounds_utc` / `ist_range_bounds_utc` for timestamp fallback. For a date-only `value_date`, match the IST calendar day equal to that date.
- Ledger / finance tables that already show `value_date` stay as they are.
- Accountant prompt `record-payment` does not gain a date picker in this pack (defaults to today IST).

### Files likely touched

- `JC/backend/app/schemas/accounts_receivable.py`
- `JC/backend/app/schemas/accounts_payable.py`
- `JC/backend/app/services/ar_ledger.py` (`post_payment_entry`)
- `JC/backend/app/services/ap_ledger.py` (`post_payment_entry`)
- `JC/backend/app/routers/accounts_receivable.py`
- `JC/backend/app/routers/accounts_payable.py`
- `JC/backend/app/services/reports.py` (`daybook`, `list_payments`)
- `JC/web/admin/js/finance.js` (AR settle + AP settle modals)
- `JC/web/admin/index.html` only if the settle modal markup is static and needs a date field

## 3. Zero-amount / sample bills

### Current

Create-bill in `customer_bill_process.py` raises if `prod.selling_price is None or prod.selling_price <= 0`. Edit-bill raises if resolved `unit_price <= 0`. Order place / line update in `customer_order_flow.py` raise if `effective_selling_price(...) or 0` is `<= 0`.

`effective_selling_price` treats `None` as unset, and also treats sell == buy as unset. A true FOC is sell `0`.

Stock decrement and AR `post_bill_entry` already run after price checks. PDF generation is not gated on a positive total.

### Change

- Treat sell price `0` as set and valid. Still reject `selling_price is None` (or `effective_selling_price` unset when the stored sell is not explicitly `0`) with the existing "sell price not set" message.
- Allow grand total `0`. Do not add a minimum-total check.
- Stock still moves on FOC bills the same as paid bills.
- AR still posts one bill entry for `0`. No due is created. Do not skip the AR row.
- PDF still generates and prints. No new FOC badge on UI or PDF.
- Apply the same 0-allowed rule on create-bill, edit-bill, and order-flow paths that currently block `<= 0`, so a sample order can be placed and billed.
- If sell is explicitly `0`, do not treat it as unset even when buy is also `0`.

### Files likely touched

- `JC/backend/app/services/customer_bill_process.py`
- `JC/backend/app/services/customer_order_flow.py`
- `JC/backend/app/services/pricing.py` only if `effective_selling_price` / `coerce_selling_price` would collapse explicit `0` to unset
- `JC/backend/tests/test_bill_math.py` (extend) or a new focused test module

## 4. Vendor alias in billing

### Current

`Vendor.alias` is stored and returned on `/vendors` and `/catalog/vendors`. People vendor cards already show alias.

Buying hub summaries (`VendorOrderSummary`) have `vendor_name`, `vendor_city`, `vendor_label` only. `_vendor_label` is `business — city`. Hub search in `vendor-orders.js` rebuilds a party object from `vendor_label` and never sets `alias`, so `OrdersUI.filterAndRankParties` cannot match alias on the hub.

Receive / bill / offline vendor pickers in `stock.js` call `filterAndRankParties` on vendor rows that may include `alias`, but cards render only business name + city. Place-order picker in `vendor-orders.js` is the same.

### Change

- Search receive + bill vendor pickers by alias (and keep name / city / phone). If a picker list object lacks `alias`, populate it from the vendor API payload.
- Buying hub / list search must include alias. Add `alias` to `VendorOrderSummary` (and detail/hub payloads that feed the same cards) and pass it through `filterHubOrders`.
- Party cards on receive + bill pickers: alias on a second line under the business name when alias is present. Do not replace `business — city` as the primary title.
- Hub / list cards (`renderOpenHubCard`, placed / received / billed / closed cards that use `vendor_label` only): show alias under the title when present.
- Place-order vendor picker uses the same card + search rule so Buying is consistent.
- Empty alias: no extra line, no "—" placeholder.

### Files likely touched

- `JC/backend/app/schemas/vendor_order.py`
- `JC/backend/app/routers/vendor_orders.py` (summary/detail builders)
- `JC/web/admin/js/stock.js` (receive + bill + offline picker cards)
- `JC/web/admin/js/vendor-orders.js` (hub filter + hub/list cards + place-order picker)
- `JC/web/admin/js/orders-ui.js` only if `partyCard` needs a subtitle slot; prefer existing meta/title HTML

## 5. Vendor still in To bill after bill created

### Current

Open → To bill is vendors with at least one `StockReceipt` where `bill_status == pending_bill` and `deleted_at is None` (`vendor_orders.py` open bucket).

`bill_receipt` in `vendor_receive_bill.py` already sets `receipt.bill_status = "billed"` after a successful bill. Stock wizard `submitReceipt` already `invalidateCache("/vendor-orders")` and calls `VendorOrders.refreshIfOpen`.

If the party still appears after a real bill, either that receipt never left `pending_bill` (wrong endpoint, failed commit path, or another pending receipt for the same vendor), or the Open list is stale (cache key / `refreshIfOpen` no-op when Buying hub is not the active view, or list not reloaded on return).

### Change

- After a successful vendor bill, the billed receipt **must** be `bill_status = "billed"` (keep the in-place one-to-one model). No new receipt row.
- If the vendor has no remaining non-deleted `pending_bill` receipts, they disappear from Open → To bill.
- They appear in the billed / next stage the hub already uses for billed receipts (`billed` bucket / vendor billed detail). Do not invent a new stage.
- If the vendor still has other `pending_bill` receipts, they remain in To bill for those only. That is correct, not a bug.
- After save: invalidate `/vendor-orders` and `/stock` (already done) **and** reload the Open list when the user is on Buying, including when they dismiss the success panel and return to the hub. `refreshIfOpen` must clear that vendor's hub expand cache and refetch; if Buying was not mounted, the next `loadList` must not reuse a cached pending list.
- Confirm every bill save path used by the admin wizard (`POST /stock/receipts/{id}/bill` and any edit-as-bill path) goes through `bill_receipt` or applies the same status flip. Do not add a second billing service.

### Files likely touched

- `JC/backend/app/services/vendor_receive_bill.py` (verify / fix status flip if a path skips it)
- `JC/backend/app/routers/stock.py` (bill endpoint wiring)
- `JC/backend/app/routers/vendor_orders.py` only if the open query is wrong
- `JC/web/admin/js/stock.js` (`submitReceipt` refresh)
- `JC/web/admin/js/vendor-orders.js` (`refreshIfOpen`, cache keys, `loadList`)

## 6. Receive goods purchase rate

### Current

Against-order Receive Goods (`stock.js`, `wizardMode === "receive_goods"`, step 2) already has a Price column bound to `l.buying_price` from `GET /stock/vendor-order/{id}/placed`. That endpoint sets `buying_price=hide_cost(format(prod.buying_price), auth)`.

Offline product picker already shows `buying_price` the same way.

If staff with `costs.read` (or admin) still see a blank rate on against-order lines, the placed-order mapper is dropping or not attaching `buying_price` on some lines. Staff without `costs.read` correctly see "—".

### Change

- Show purchase rate (catalog buying price) on each against-order Receive Goods line.
- Use the same number the offline picker shows for that product. Do not invent a second price source.
- Keep `hide_cost`: no rate for actors without cost visibility.
- Do not add a total-qty footer. Do not add a line-amount or receive-total column in this pack.
- Review step may keep showing rate if it already does; do not add a new totals footer there either.

### Files likely touched

- `JC/backend/app/routers/stock.py` (`get_placed_order_for_receipt`) if the payload omits price
- `JC/web/admin/js/stock.js` (receive_goods line table; ensure `buying_price` is copied onto `wizardLines` and rendered)

## Data flow

```
U1  Collect/Pay amount
      → settle | record-payment
      → outstanding > 0 and amount > 0
      → one post_payment_entry(full amount)
      → outstanding = previous − amount  (may be < 0)

U2  Date picker (default today IST)
      → value_date on settlement body
      → post_payment_entry(..., value_date=)
      → ledger display uses value_date
      → daybook / list_payments bucket that IST day

U3  Bill / place order with selling_price == 0
      → price check allows 0, rejects None
      → stock out as today
      → AR bill entry amount 0
      → PDF as today

U4  Vendor row { business_name, city, alias, phone }
      → filterAndRankParties includes alias
      → card: title business; subtitle alias (if any) + city

U5  POST /stock/receipts/{id}/bill
      → bill_receipt sets bill_status=billed, posts AP
      → invalidate + reload Open
      → To bill = vendors with remaining pending_bill only

U6  GET placed lines (buying_price, hide_cost)
      → receive_goods wizardLines.buying_price
      → Price cell on each line
```

## Error handling

- **U1.** `outstanding <= 0`: keep current 400. `amount <= 0`: keep current 400 / form toast. Invalid payment mode: unchanged. Over-due amount: success, not 400.
- **U2.** Missing/invalid `value_date` on API: 400. Empty date in the modal: client toast, do not submit. Omitted `value_date` on record-payment: today IST, not 400.
- **U3.** `selling_price is None`: keep "sell price not set". Other bill errors (stock, product inactive) unchanged. Grand total 0 is not an error.
- **U4.** No alias: search and cards behave as today aside from alias. No 400s.
- **U5.** Billing a receipt that is not `pending_bill`: keep "receipt is not open for billing". Voided receipt: keep recycle-bin message. After success, do not toast success if the status flip failed; fail the request instead.
- **U6.** Missing buying price after hide_cost: show "—". Do not block receive.

## Testing

Run `cd JC/backend && python3 -m pytest tests/ -q` after implementation.

Required new/extended backend tests:

- **U1.** AR settle: due 100, pay 150 → 201, one `payment` row of signed −150, outstanding −50. Same for AP settle. `record-payment` over-due also 201. Pay when outstanding is 0 still 400. Pay `amount <= 0` still 400.
- **U2.** Settle with `value_date` in the past → row `value_date` equals that date; `created_at` is now. Daybook for that IST day includes the payment; daybook for the save-day does not (unless they are the same IST day). Omit `value_date` → stored as today IST.
- **U3.** Create (or bill-from-order) with `selling_price == 0` → 201, stock decremented, AR bill amount 0, grand total 0. `selling_price is None` still 400.
- **U5.** `bill_receipt` on a `pending_bill` receipt → `bill_status == billed`. Open-bucket query no longer returns that vendor unless another pending receipt exists.

Admin checks (manual or browser after code):

- Collect / AP pay: date defaults to today; over-due amount submits; ledger shows the chosen date.
- FOC bill prints.
- Receive + bill pickers: alias search hit; alias visible under name.
- Buying Open: after bill, vendor gone from To bill (no other pending receipts); billed bucket shows them.
- Against-order receive: purchase rate visible for admin / `costs.read`.

## Out of scope

- Customer / Selling to-bill stuck.
- Total-qty footer on Receive Goods (or receive review).
- FOC / sample badge on bill UI or PDF.
- Split payment entries, new AR/AP `advance` type, or freight-style "Pay advance" when outstanding is already `<= 0`.
- Changing cost-visibility policy.
- Unrelated dirty admin files already in the working tree (`catalog.js`, `products.js`, styles, and so on). This pack's implementation commit is separate from those.

## Implementation-plan scope

One plan, six units in this order (low coupling, dependency-friendly):

1. U1 extra collection
2. U2 collection date (same payment endpoints)
3. U3 FOC bills
4. U4 vendor alias
5. U5 to-bill flip + refresh
6. U6 receive purchase rate

U1 and U2 touch the same payment routers; the plan should sequence them so `value_date` and the over-due rule land in one pass on those files. U4 and U5 both touch Buying hub JS; keep their diffs in separate steps. No second spec.
