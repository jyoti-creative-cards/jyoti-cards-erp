# JC ERP — Round 2 Audit: Customer Order Lifecycle (New → Confirm → Bill → Dispatch/Close, Returns)

Scope: full customer order lifecycle — online (shop portal) + offline (admin) placement,
New/Confirm/Billed/Cancelled/Closed buckets, returns, bill creation wizard, credit limit
checks, addon display, bill PDF generation, bill number/series allocation, void/restore.

Read-only review of `JC/backend/app/{routers,services,models}/customer_order*`,
`customer_bill*`, `customer_returns*`, `void_service.py`, `bill_series_alloc.py`,
`credit_limit.py`, `app/db/session.py` (runtime migrations), `app/routers/shop.py`, and
`JC/web/admin/js/{customer-orders.js,returns.js}`. Cross-referenced against the
previously-fixed race (`f7c0f07` — duplicate open `jc_customer_orders` rows) and the two
prior audit passes (`.audit-reports/customer.md`, commits `ddccd86`/`e6e5576`) to avoid
re-reporting already-fixed issues, and to check whether the *same bug class* recurs
elsewhere.

Method: traced every bucket's backend query, every `get_or_create_*`-style helper against
the models file's actual `UniqueConstraint`/partial-unique-index coverage, and every
button in `customer-orders.js`/`returns.js` from `onclick` → API call → resulting state.

---

## Findings

### CRITICAL

**A bill whose lines are all "Closed" can never leave the "Billed" tab, and can never be Voided either — a permanent stuck/duplicate-listed row, the same bug class as the original New-tab bug.**
`JC/backend/app/routers/customer_orders.py:305-326` (list) and `:457-464` (detail) —
the `bucket == "billed"` query is `CustomerBill.cancelled_at.is_(None)` only. It never
checks whether every `CustomerBillLine` on that bill has been closed via
`close_bill_line()` (`JC/backend/app/services/customer_bill_process.py:636-666`). Nothing,
anywhere, ever moves the *bill itself* out of the "Billed" bucket or marks it done —
`close_bill_line` only flips the individual `CustomerBillLine.status` and creates a
**separate** history placement under the customer's "closed" `CustomerOrder` bucket. So
once every line on a bill is closed: (1) the same commercial transaction is now visible
under **both** "Billed" (the original bill, unchanged) **and** "Closed" (the new history
placement) at the same time — a direct violation of "one bucket at a time"; and (2) the
stale bill in "Billed" can never be cleaned up, because `void_customer_bill()`
(`JC/backend/app/services/void_service.py:305-333`) calls `cancel_customer_bill()` first
whenever the bill isn't already cancelled, and `cancel_customer_bill()`
(`customer_bill_process.py:519-522`) hard-blocks with `HTTPException(400, "cannot cancel —
some lines already closed")` — the exact state a settled bill is always in. A real
2-week-old, fully-collected, fully-dispatched bill sits in the "Billed" actionable
backlog forever; the only "fix" staff can attempt (clicking admin-only "Void") fails with
a confusing 400 error that gives no indication the block is permanent. This is precisely
the class of bug already found and fixed once for New/Confirmed (stale row never leaves
its bucket), recurring one stage later in the same lifecycle.
**Fix:** once every `CustomerBillLine` on a bill is closed, either flip the bill out of
the "billed" list query (e.g. add `NOT EXISTS (open bill lines)` to the bucket filter) or
give the bill itself a `closed_at`; separately, let `void_customer_bill`/`cancel_customer_bill`
handle bills whose lines are *all* closed (nothing left to reverse) instead of blocking —
or if void must stay blocked there, surface a real message ("already fully closed —
nothing to void") instead of the generic cancel error.

---

### HIGH

**1. Editing an existing bill shows a Review total that ignores GST and additional charges — the number staff approve is not the number that gets saved.**
`JC/web/admin/js/customer-orders.js:1984-2013` — when `editBillId` is set, step 5
("Review") is built by a **client-side** recomputation instead of calling the backend
preview endpoint (the create-bill path at `:2021-2028` does call
`/customer-orders/customer/{id}/process/preview` and shows the real server-computed
totals). This client calc sums `line_total + freight_charges + packaging_charges` only —
it never adds GST (`gst_enabled`/`gst_rate_percent`, both editable in step 3 for edits too)
or `additional_charges` (also editable in step 3 for edits) into `grand_total`. Staff
editing a GST-enabled bill, or one with an additional charge line, sees a materially
*lower* "Grand total" on the confirmation screen than what `PUT /customer-orders/bills/{id}`
actually computes and persists server-side (via `edit_customer_bill` →
`compute_bill_totals`, which does apply GST/extra charges correctly). The bill they end up
saving/printing/sending to the customer will not match what they approved on screen.
**Fix:** call the same `/process/preview`-style computation (or a dedicated `PUT .../preview`)
for the edit-bill review step instead of a divergent client-side reimplementation, or at
minimum add GST + additional-charges into the client calc so it matches
`compute_bill_totals`.

**2. `_get_or_create_open_line` has no unique-constraint race handling despite the table having a real unique index — a concurrent cancel/edit-bill will 500 instead of retrying.**
`JC/backend/app/services/customer_order_flow.py:41-77` — `CustomerOpenLine` genuinely has
`UniqueConstraint("customer_id", "catalog_product_id")` at the model level
(`JC/backend/app/models/customer_order.py:74-75`), unlike `jc_customer_orders`
(which needed the `f7c0f07` fix). But unlike `get_or_create_customer_order()`
(`customer_order_flow.py:23-38`, which wraps the insert in `db.begin_nested()` +
`IntegrityError` retry) and unlike `get_or_create_open_order` for vendors
(`stock_receipt.py`), `_get_or_create_open_line` does a plain check-then-insert with no
retry. It is called from two multi-step, otherwise-transactional flows: cancelling a bill
(`customer_bill_process.py:573`, inside `cancel_customer_bill`) and editing a bill's qty
upward for a brand-new product (`customer_bill_process.py:1027`, inside
`_apply_bill_qty_delta_to_order`). If two staff concurrently cancel/edit bills that touch
the same customer+product for the first time, one request's `INSERT` wins and the other
raises an unhandled `IntegrityError`, which is not caught anywhere in the call chain up to
the router — the whole cancel-bill or edit-bill request 500s and rolls back, even though
the underlying business action (the other request) genuinely succeeded. Staff sees a raw
500/generic error toast on an action that should have just been retried transparently.
**Fix:** wrap `_get_or_create_open_line`'s insert in the same `db.begin_nested()` +
`IntegrityError`-retry pattern already used by `get_or_create_customer_order`.

---

### MEDIUM

**3. Credit-limit "override" is still fully dead end-to-end (confirmed still open from the prior audit pass).**
`JC/backend/app/services/credit_limit.py:46-56` (`assert_credit_allows_bill` — comment
says outright "Always allows billing... never blockers", `force` param unused) and
`JC/web/admin/js/customer-orders.js:1899` (`setForceCredit` is defined and exported at
`:2733` but grep shows **zero** callers anywhere in the file — no checkbox/toggle ever
invokes it). This was flagged as MEDIUM in `.audit-reports/customer.md` and was not part
of either subsequent fix commit (`ddccd86`, `e6e5576`) — re-verified still present as of
this pass. Directly relevant to this round's scope (credit limit checks): the "⚠ Over
limit" banner (`creditBannerHtml`, `customer-orders.js:1334-1367`) reads as a real
soft-block staff can consciously override, but nothing is blocked and no override control
exists to click. Flagging again since it sits squarely in this round's requested scope.
**Fix:** unchanged recommendation — either wire a real override checkbox that the backend
actually branches on, or reword the banner to be purely informational.

**4. "Billed" list's `placement_count` field secretly means "bill count" here — a latent footgun, not (yet) user-visible.**
`JC/backend/app/routers/customer_orders.py:322-334` — the `bucket == "billed"` branch
populates `CustomerOrderSummary.placement_count` with the *count of `CustomerBill` rows*
for that customer (`func.count(CustomerBill.id)`), not a count of placements (there is no
placement query at all in this branch — `id=0`, no real order). The frontend happens to
relabel it correctly today (`js/customer-orders.js:539`: `` `${o.placement_count ||
o.bill_count || 0} bill${...}` ``, and `:1173` similarly falls back to `bill_count`), so
there's no current visible mislabel. But the schema field name lies about its contents,
and the frontend's `|| o.bill_count` fallback references a field the backend never sends —
dead code that looks like it's guarding against a rename that never happened correctly.
Any future dev who trusts the field name (e.g. on a placements-count display elsewhere)
will silently show the wrong number.
**Fix:** rename to `bill_count` in the schema/response for the billed branch (or add a
real distinct field) instead of overloading `placement_count`.

**5. `CustomerOpenLine.status = "open"` is set as a no-op in two "fully billed" branches — confusing dead code, currently harmless only because of a second filter.**
`JC/backend/app/services/customer_bill_process.py:290-296` (inside `process_customer_bill`)
and `:1006-1012` (inside `_apply_bill_qty_delta_to_order`) — when an open line's
`quantity_open` drops to 0 (fully billed), the code explicitly sets
`open_row.status = "open"` — i.e. re-asserts the status it already had; the only two
statuses this model ever uses are `"open"` and `"cancelled"` (verified via grep across
`customer_order_flow.py`/`customer_bill_process.py` — no `"billed"`/`"closed"` status
value exists for this table). Every query that lists the "Confirmed" bucket additionally
filters `CustomerOpenLine.quantity_open > 0`, so a fully-billed line is correctly hidden
today regardless of this no-op — not currently user-visible. But it reads exactly like a
bug (dead branch that looks like it should transition state to something else), and it's
the kind of code the next person "fixes" by making it a genuine no-op removal or, worse,
copies the pattern somewhere that isn't double-gated by the qty filter.
**Fix:** remove the redundant assignment, or replace with a comment explaining the qty
filter is the only thing hiding fully-billed rows.

---

### LOW

**6. "Closed"/"Cancelled" bucket's Today/Past day filter scopes by the shared bucket-order's `updated_at`, not by each placement's own timestamp — count can mix days.**
`JC/backend/app/routers/customer_orders.py:338-350` (generic bucket branch, used for
`cancelled`/`closed`) filters `CustomerOrder.updated_at` (bumped on *every* new
cancel/close action for that customer, e.g. `customer_order_flow.py:356-357`,
`customer_bill_process.py:667`) to decide if the *row* shows in "Today" mode, but
`_summary()` (`customer_orders.py:180-217`) then counts **all** placements ever attached
to that shared order, not just today's. A customer who had one cancellation yesterday and
another today will show up correctly in "Today" (since `updated_at` was just bumped), but
the placement/line counts on the card include yesterday's cancellation too — a minor
scope-mismatch between "why this card is visible" and "what number it shows."
**Fix:** if per-day counts matter here, derive them from `CustomerOrderPlacement.placed_at`
within the day window rather than from the whole order's lifetime count.

**7. `create_customer_return` doesn't check `customer.deleted_at`, unlike almost every other write endpoint in this module.**
`JC/backend/app/services/customer_returns.py:117-119` — only checks `if not customer`,
not soft-deleted state (contrast e.g. `customer_orders.py:770`,
`:801-802`, `shop.py` flows, which all check `customer.deleted_at`). A return could in
theory be filed against a customer that's been moved to the recycle bin. Low likelihood
in practice (the UI's customer picker for returns filters `is_active !== false` but not
`deleted_at` explicitly either — `returns.js:328`), but inconsistent with the rest of the
module's guard pattern.
**Fix:** add the same `customer.deleted_at` check used elsewhere.

---

## Verified NOT bugs (checked because they matched the requested bug class, ruled out)

- **`jc_customer_orders` duplicate-open-row race** — already fixed in commit `f7c0f07`
  (real partial unique index `uq_jc_customer_orders_open` on `(customer_id, bucket) WHERE
  is_open`, backed by `_migrate_customer_order_unique_open()` in `app/db/session.py`, with
  `get_or_create_customer_order`'s existing `IntegrityError` retry now actually able to
  fire). Verified the index exists and the retry path is correct.
- **A customer having both an open "New" row and an open "Confirmed" row simultaneously**
  — intentional, not a duplicate: New = not-yet-confirmed placement, Confirmed = previously
  confirmed backlog awaiting billing. Different buckets, both legitimately open at once.
- **"Dispatch" button shown on every Billed card, even self-pickup customers** — verified
  against `freight_parcels.list_parcels()`: self-pickup bills *do* need an explicit "Mark
  dispatched" action to clear the pending-dispatch queue, so the button is correct for
  every transport mode, not just bus/agent freight.
- **Addon quantity scaling (`addonsUnderHtml` / PDF `_addon_qty`)** — checked all call
  sites (open lines, received lines, bill lines, process wizard, PDF); each correctly
  scales by that context's own remaining/shipped/placed quantity, not a copy-pasted
  sibling field.
- **`_line_net_rate` matching bill totals by `catalog_product_id`** — could misattribute
  if a bill had two lines for the same product, but `process_customer_bill`/`edit_customer_bill`
  both key their line-building dicts by `catalog_product_id`, so a bill can never carry two
  rows for the same product; not reachable.
- **Double-submit on wizard "Save"/"Submit" buttons without an explicit `disabled` attribute**
  (e.g. `returns.js` "Submit return") — the app's global `#loading` overlay
  (`position:fixed; inset:0; z-index:9999`, no `pointer-events:none`) is invoked
  synchronously before every `await ctx.api(...)` call across both files and blocks clicks
  underneath it; this closes the double-submit window in practice for the flows checked,
  unlike the previously-fixed vendor-edit Save button (which apparently didn't have this
  guard at the time).

---

*Report generated via static code review — no code was modified. Findings above are new
for this round; already-known issues from `.audit-reports/customer.md` are not repeated
except where explicitly re-verified as still open (§3) because they sit inside this
round's requested scope.*
