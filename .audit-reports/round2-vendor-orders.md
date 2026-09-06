# Vendor Order / Receive / Bill Lifecycle — Functional Bug Audit (Round 2)

Scope: `JC/backend/app/routers/vendor_orders.py`, `stock.py`, `vendors.py`;
`app/services/stock_receipt.py`, `vendor_receive_bill.py`, `receipt_edit.py`,
`debit_notes.py`, `vendor_billing_math.py`, `ap_ledger.py`, `open_lines.py`,
`void_service.py`, `ledger.py`, `token_search.py`; models `vendor_order.py`,
`stock.py`, `vendor.py`, `vendor_open_line.py`; frontend `vendor-orders.js`,
`stock.js`, `vendors.js`, `debit-notes.js`. Investigation only — nothing was
fixed.

---

## CRITICAL

### C1. "Billed" tab drill-down is completely dead — every bill's expand/close/edit UI always shows empty, even though the tab lists real bills

**Files:**
- `JC/backend/app/routers/vendor_orders.py:149` (`_to_bill_summaries` always sets `id=0`)
- `JC/backend/app/routers/vendor_orders.py:205` (`_billed_summaries` always sets `id=0`)
- `JC/web/admin/js/vendor-orders.js:540-558` (`renderBilledHubCard` — row/"View vendor" wired to the broken id)
- `JC/web/admin/js/vendor-orders.js:761-769` (`toggleHubVendor` generic branch — falls back to empty `{placements: [], aggregated_lines: []}` for bucket `"billed"`)
- `JC/web/admin/js/vendor-orders.js:800-828` (`openDetail` — `match?.id` and `orderId > 0` are both always falsy for `"billed"`/`"received"` buckets, so `currentOrder` stays `null`)
- `JC/backend/app/routers/vendor_orders.py:998-1015` (`close_billed_placement` — 400s unconditionally, dead endpoint)

**Symptom a real user would see:** A staff member opens the "Billed" tab and sees a vendor card correctly summarizing "3 bills · 5 products · ₹42,000" (from `_billed_summaries`, which reads real `StockReceipt` rows). They tap the card (or "View vendor" from the "…" menu) to see the actual bills, amounts, debit notes, or to close/edit an individual bill — and it always renders **"No billed shipments yet."** / **"Nothing for this vendor in this stage."**, as if the vendor has no bills at all, directly contradicting the number they just saw on the card. The per-bill **"Close"** button (`closeBilledPlacement`, `vendor_orders.py:990` `close_billed_placement`) is unreachable from the UI and would 400 with "only billed placements can be closed" even if called directly, because a `VendorOrderPlacement` is never linked to a `VendorOrder` whose `bucket == "billed"` — the codebase's own comments elsewhere in this file confirm `VendorOrder.bucket` never transitions to `"billed"`/`"received"` in the one-receipt-per-bill model (see `_to_bill_summaries` and `_billed_summaries` docstrings), but the hub-expand (`toggleHubVendor`) and `openDetail` code for the `"billed"` bucket were never updated to match — they still assume a real `VendorOrder` id exists and silently degrade to an empty list when it (predictably) doesn't. The only working way to close a bill is the separate "Close" *batch* button, which correctly sources from `StockReceipt` via `/vendor-orders/closeable` — but "Edit bill", "Bill Receipt", "Vendor Bill" download, and "Debit Note" (all nested inside the broken per-bill expand) are effectively unreachable for a vendor from this tab.

**Recommended fix:** Give `toggleHubVendor`'s `"billed"` branch (and `openDetail`'s bucket-lookup fallback) a StockReceipt-backed data source analogous to the `"received"` branch's `/stock/vendor-order/{vendorId}/received` call — e.g. a new endpoint that returns pending/closed billed receipts with lines/amounts for a vendor — instead of trying to resolve a `VendorOrder` id that will never exist for this bucket. Also remove or repoint `close_billed_placement`, since it can never succeed as written.

---

### C2. Same root cause breaks the "To bill" tab's "View vendor" and the post-receive "View Received" button

**Files:**
- `JC/web/admin/js/vendor-orders.js:451` (`renderReceivedHubCard` → "View vendor" → `openDetail(o.id||0,'received',...)`)
- `JC/web/admin/js/vendor-orders.js:354` (same pattern from the combined "Open" tab's to-bill cards)
- `JC/web/admin/js/stock.js:1787` (the "Goods received" success screen's **"View Received"** button calls `VendorOrders.openDetail(0,'received',savedVendorId)`)
- Backend: `JC/backend/app/routers/vendor_orders.py:149` (`_to_bill_summaries` id=0)

**Symptom:** Immediately after successfully receiving goods, the confirmation screen offers **"View Received"** — tapping it always lands on an empty "Nothing for this vendor in this stage" page instead of the receipt just created. The same happens from "View vendor" on the "To bill" tab's "…" menu. (Unlike the "Billed" tab, the *row-click*/"Show lines" expand on "To bill" cards does work correctly, because `toggleHubVendor`'s `"received"` branch happens to use the correct `/stock/vendor-order/{id}/received` endpoint — only the `openDetail`-based navigation paths are broken.) This is confusing and inconsistent: two different buttons that both claim to show the same vendor's pending-to-bill items give different (one wrong) results.

**Recommended fix:** Point both call sites at the same working `/stock/vendor-order/{vendorId}/received`-based view instead of `VendorOrders.openDetail(0, 'received', vendorId)`.

---

## HIGH

### H1. "Open in Orders" on every vendor-ledger "Bills / received" card always fails with "Order link missing"

**Files:**
- `JC/web/admin/js/vendors.js:301` and `:376-384` (`openOrderFromLedger`, requires `d.vendor_order_id`)
- `JC/backend/app/services/ledger.py:150-160` (the `stock_received` ledger entry's `details` dict — only has `receipt_id`, `order_receipt_number`, `expected_bill_amount`, `lines`; never `vendor_order_id`)

**Symptom:** On a vendor's Activity tab, every "Bills / received" card has an "Open in Orders" button (`vendors.js:301`). Clicking it always shows the toast **"Order link missing"** and does nothing, because `build_vendor_ledger`'s `stock_received`/`vendor_bill` entries never populate `details.vendor_order_id` (only `order_placed`/`order_cancelled` placement entries do — see `ledger.py:88-90`). A staff member trying to jump from a receipt straight to the order screen for that vendor gets a dead-end error every single time.

**Recommended fix:** Either remove the "Open in Orders" button from receipt/bill ledger cards, or wire it to `VendorOrders.setBucket('placed')` + `VendorOrders.openDetail(0,'placed',vendorId)` (vendor-scoped, no order id needed) instead of relying on a `vendor_order_id` that receipts never carry.

---

### H2. `_get_or_create_open` (vendor open-pending-line upsert) has no race-condition retry despite a real unique constraint backing it

**File:** `JC/backend/app/services/open_lines.py:11-48` (`_get_or_create_open`, called by `add_to_open` from `create_placement`, `update_line`, and `_edit_receive`)

**Symptom:** `VendorOpenLine` has a real `UniqueConstraint("vendor_id", "catalog_product_id")` (`app/models/vendor_open_line.py:18`) — this is exactly the same shape of "find existing open row, else create" pattern that caused the customer-order and vendor-order-bucket duplicate-row bug this audit is chasing. But unlike `get_or_create_open_order` (`stock_receipt.py:24-40`), which correctly wraps its insert in `db.begin_nested()` + `IntegrityError` retry, `_get_or_create_open` does a plain `db.add(row); db.flush()` with no retry. If two requests place/edit orders for the same vendor+product at nearly the same instant, both can pass the "no existing row" check, and the second `flush()` raises an uncaught `IntegrityError` that aborts the whole request (the staff member's order-placement or receipt-edit fails with a raw 500) instead of gracefully merging into the winning row the way `get_or_create_open_order` does.

**Recommended fix:** Wrap `_get_or_create_open`'s insert in `db.begin_nested()`/`IntegrityError` retry, mirroring `get_or_create_open_order`.

---

## MEDIUM

### M1. Duplicate/redundant unique index for the same vendor-order-open-bucket race

**File:** `JC/backend/app/db/session.py:1136-1139` (`uq_jc_vendor_orders_one_open`, inside `_migrate_indexes`) vs. `session.py:232-236` (`uq_jc_vendor_orders_open`, inside `_migrate_vendor_order_unique_open`)

**Symptom:** No functional bug today (both are `CREATE UNIQUE INDEX IF NOT EXISTS`, so they don't conflict), but two differently-named partial-unique indexes exist on the exact same `(vendor_id, bucket) WHERE is_open = true` predicate. This is confusing dead weight in precisely the migration file that a future engineer will read when hunting this class of bug again, and doubles the write-time index-maintenance cost on every vendor-order insert for no benefit.

**Recommended fix:** Drop one of the two (keep `uq_jc_vendor_orders_open`, since `_migrate_vendor_order_unique_open` is the one with the pre-migration dedup logic) and remove the redundant `CREATE UNIQUE INDEX` statement from `_migrate_indexes`.

---

### M2. Dead "already billed" guard in receipt-edit reads as an active safety check but can never fire

**File:** `JC/backend/app/services/receipt_edit.py:196-217` (`_edit_receive`)

**Symptom:** This code fetches `VendorOrderLine` rows via `receipt.received_placement_id` to compute `already_billed`, then blocks reducing received qty below it. But `received_placement_id` is hardcoded to `None` at receipt-creation time (`vendor_receive_bill.py:89`) and is never set anywhere else in the codebase (confirmed by full-repo search) — so `placement_lines` is always empty and `already_billed` is always `0`. The guard happens to be harmless only because `_edit_receive` is only reachable while `bill_status != "billed"` (at which point `quantity_billed` is always 0 anyway) — but the code reads as though editing a receipt is protected against under-cutting an already-billed quantity, when it is not actually enforced by this path at all. A future change to allow partial billing before this status flips would silently lose this protection.

**Recommended fix:** Either delete the dead `received_placement_id`/`placement_lines` block (and its comment implying it's load-bearing), or replace it with a real check against `StockReceiptLine.quantity_billed` for the line being edited.

---

### M3. `close_billed_placement` endpoint can never succeed

**File:** `JC/backend/app/routers/vendor_orders.py:998-1015`

**Symptom:** This endpoint 400s with "only billed placements can be closed" on every call, because it requires `order.bucket == "billed"`, but (per the codebase's own comments and confirmed by grep) no `VendorOrder` ever has `bucket == "billed"` — only `"placed"` and `"cancelled"` are ever created. This is the same root cause as C1; listed separately here because it's an independent dead code path worth removing regardless of the frontend fix.

**Recommended fix:** Remove this endpoint (superseded by `/vendor-orders/close-batch`, which correctly closes `StockReceipt` rows) or repoint it at `StockReceipt`.

---

## LOW

### L1. Two near-identical migration functions for the vendor-order-open unique index (see M1) also exist as a maintenance/readability hazard for whoever revisits `session.py` for this exact bug class next.

*(Same finding as M1 — included here only to flag it explicitly for someone re-reading `session.py` top-to-bottom for “missing unique index” bugs; the presence of *two* indexes for the same thing could cause someone to assume the constraint is stronger/newer than it is, or waste time trying to find a difference between them.)*

---

## Areas checked and found correct (no bug)

- **Vendor-order open-bucket uniqueness** (`jc_vendor_orders`): a real partial unique index exists (`uq_jc_vendor_orders_open`, `session.py:234`) and `get_or_create_open_order` (`stock_receipt.py:24`) correctly retries on `IntegrityError` — this is the "already fixed" reference implementation the audit was told to check against, and it holds up.
- **`VendorOpenLine` uniqueness**: real `UniqueConstraint(vendor_id, catalog_product_id)` exists at the model level (see H2 for the one gap in *using* it).
- **Billing %/GST % override never mutates the vendor profile**: verified in both `bill_receipt` (`vendor_receive_bill.py:213-229`) and `_edit_bill` (`receipt_edit.py:313-332`) — overrides are stored only on `StockReceipt.billing_pct_applied`/`gst_rate_pct_applied` (per-receipt snapshot columns), and `PATCH /vendors/{id}/billing-terms` (`vendors.py:170`) is a completely separate, explicit, admin-gated endpoint never called from the bill-save flow. No accidental persistence path found.
- **Debit note sign conventions**: traced `normalize_signed_values` → `debit_note_payable_effect` → `post_debit_note_entry` end to end. "Short delivery"/"Bill overcharged" correctly reduce AP; "Extra goods"/"Bill undercharged" correctly increase it. Frontend (`debit-notes.js`) preview matches backend math.
- **Debit note edit** (`PATCH /debit-notes/{id}`) correctly reverses the old ledger/stock effect and creates a fresh note rather than mutating history in place.
- **Void/restore of receipts** (`void_service.py`): stock, AP, and debit-note effects are symmetrically reversed/reapplied; open-line give-back is correctly gated on `placed_order_id is not None` so offline receipts aren't double-counted.
- **Vendor unique-# search**: `token_match`'s `exact_int_columns` handling for `vendor_number` is correct — exact match for numeric tokens on the ID column, normal substring match elsewhere, `#` prefix stripped before search.
- **"Placed"/"To receive" and "Cancelled" buckets**: these buckets *do* have real, non-zero `VendorOrder` ids, so `openDetail`/`toggleHubVendor` work correctly there — the C1/C2 bug is specific to `"received"`/`"billed"`.
