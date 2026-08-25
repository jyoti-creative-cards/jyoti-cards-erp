# Vendor billing model redesign

Date: 2026-08-25
Status: approved in chat; pending user review of this file

## Goal

Replace the JSON `billing_context` blob on vendors with explicit typed columns. Simplify the receive→bill flow from "aggregate any unbilled receipts into one bill" to "one receive batch = one bill". At bill time, always let staff type the real invoice total (never lock it); auto-suggest debit notes when billed quantity differs from received quantity, or when the calculated expected total differs from the entered total. Post one AP entry for 100%-billing vendors, two for split-billing vendors (e.g. VEE PEE).

## Data cleanup (do first, before any schema change)

Current DB state (checked 2026-08-25): 84 `vendor_receive` receipts are real (sequential receipt numbers, real vendors, back to 2026-06-30) and already reflect real stock — **do not touch**. Only 4 `vendor_bill` receipts exist and all are test/demo data:

- `test vendor` — bill `1234`, ₹1000
- `delete ven` — bills `886` (₹8000) and `8757` (₹45688)
- `DEV PRINT & PACK PRIVATE LIMITED` — bill labelled `"direct opening demo"`, ₹15000

Delete these 4 `StockReceipt` rows + their `StockReceiptLine`s, the 1 associated `DebitNote` (tied to `delete ven`), and the associated `ApLedgerEntry` rows (`bill`, `debit_note`, `payment`, `payment_reversal` types tied to `test vendor` / `delete ven`). Soft-delete (`is_active=false`, `deleted_at=now`) the junk vendors: `test vendor`, `delete ven`, `agrawal test vendor`. Leave everything else — including the legitimate `opening_balance` AP entries and all 84 receive batches — untouched.

## Vendor billing columns

Add to `jc_vendors` (replaces reliance on `billing_context` JSON; that column stays in the table unused, nothing reads it after this ships):

| Column | Type | Default | Meaning |
|---|---|---|---|
| `billing_pct` | Numeric(5,2) | 100 | % of actual price the vendor bills on paper (50 or 100) |
| `additional_charge` | Numeric(10,2) | 100 | Flat Rs added per bill |
| `additional_charge_label` | String(50) | `"Additional charge"` | Display label — "Packing charges", "Freight charges", etc, per vendor |
| `discount_pct` | Numeric(5,2) | 0 | % discount vendor gives on item subtotal |
| `gst_included` | Boolean | true | Whether GST applies |
| `gst_rate_pct` | Numeric(5,2) | 18 | GST % when included |
| `billing_notes` | Text | null | Optional reminder shown to staff at billing time |

Migration seed values:

| Vendor | billing_pct | additional_charge | label | discount_pct | gst_included | gst_rate_pct |
|---|---|---|---|---|---|---|
| VEE PEE CREATIONS | 50 | 100 | Packing charges | 0 | true | 18 |
| SINGHAL PRINT & GRAPHICS | 100 | 0 | Additional charge | 0 | true | 18 |
| GARG ENTERPRISES | 100 | 100 | Freight charges | 6 | true | 18 |
| all other vendors | 100 | 100 | Additional charge | 0 | true | 18 |

Editing these columns stays admin-only (`PATCH /vendors/{id}/billing-context` becomes `PATCH /vendors/{id}/billing-terms`, same admin-only guard as today). `VendorBillingContext` Pydantic schema is replaced by a flat `VendorBillingTerms` schema with these 7 fields; `invoice_qty_unit` and `allow_override` are dropped (no longer needed — bill total is always editable, and per-1000 price display is dropped since the total is now typed by hand rather than derived).

### Calculation formula

```
line_value(qty)   = buying_price × billing_pct/100 × qty
item_subtotal     = sum of line_value across billed lines
after_discount     = item_subtotal × (1 − discount_pct/100)
base               = after_discount + additional_charge
gst_amount         = base × gst_rate_pct/100   (if gst_included, else 0)
bill_total         = base + gst_amount                                  # "Entry 1" — the paper invoice amount
extra_cash         = sum(buying_price × (1 − billing_pct/100) × qty)    # "Entry 2" — only if billing_pct < 100
```

Confirmed against real vendor math for VEE PEE, SINGHAL, GARG.

## Receive → bill lifecycle (simplified to one-to-one)

Today, billing aggregates unbilled quantity across *all* past receive-batches for a vendor (`unbilled_received_qty_by_product`, `reduce_unbilled_received`). This is replaced: **each receive action is its own unit that flows straight to its own bill.**

- **Placed** (to receive): unchanged. `VendorOrder`/`VendorOrderPlacement`/`VendorOrderLine` still track ordered-but-not-yet-received qty via `quantity_remaining`, exactly as today.
- **Receive**: same UI (pick products + qty, enter receipt number, submit). Behind the scenes: create one `StockReceipt` + its `StockReceiptLine`s + `add_stock()` calls — no more shadow placement/line rows in a "received" `VendorOrder` bucket. At this moment, compute and freeze `expected_bill_amount` (and `expected_extra_cash` if `billing_pct < 100`) using the formula above and the vendor's *current* billing columns, using `received_qty` as the quantity input. This is a stable reference — it does not change if the vendor's billing settings change later.
- **To bill**: list of `StockReceipt` rows with `bill_status = 'pending_bill'`, each showing its frozen expected amount.
- **Bill**: pick one receipt. Wizard shows its lines (received qty read-only, price), a billed-qty input pre-filled with received qty (editable), and a "Total bill amount" input pre-filled with the frozen `expected_bill_amount` (**always editable**, never locked). On submit, the same `StockReceipt` row transitions to `bill_status = 'billed'` and gets `bill_number`, `total_billed_amount`, `actual_ap_amount` set.

### Schema changes

`jc_stock_receipts`:
- Add `bill_status: String(20) NOT NULL DEFAULT 'pending_bill'` (`pending_bill` | `billed`). Replaces relying on `receipt_type` + separate row per stage.
- Add `expected_bill_amount: Numeric(14,2) NULL` — frozen at receive time.
- Add `expected_extra_cash: Numeric(14,2) NULL` — frozen at receive time, only set when `billing_pct < 100`.
- `receipt_type` stays `vendor_receive` for the whole lifecycle of a batch (no more separate `vendor_bill` rows created at bill time — billing updates the existing row in place).

`jc_debit_notes`:
- Add `source: String(10) NOT NULL DEFAULT 'manual'` (`auto` | `manual`) — so the UI can badge auto-suggested notes and so we never confuse an auto quantity-check note with a manual physical-stock-correction note.

Removed going forward (code deleted, tables kept as-is since old rows may still reference them for historical/audit reasons, just no longer written to for new receipts): creation of `VendorOrderPlacement`/`VendorOrderLine` rows for the `received` and `billed` `VendorOrder` buckets. `unbilled_received_qty_by_product`, `reduce_unbilled_received` are removed. `StockReceipt.billed_placement_id`/`received_placement_id` stop being populated for new rows (existing columns, just left null going forward — not dropped, since old rows still use them).

Existing `StockReceipt` columns `additional_charges`, `total_billed_amount`, `actual_ap_amount`, `bill_number`, `bill_file_key` are unchanged and continue to be set at bill time (`additional_charges` gets frozen from `vendor.additional_charge` at bill submission, same pattern as the new `expected_*` columns at receive time).

## Bill wizard — two independent auto-debit-note checks

1. **Quantity check** (per line): compare billed qty (operator-entered, defaults to received qty) against received qty (physical count, frozen at receive). On mismatch, auto-suggest a `note_type='value'`, `source='auto'` debit note worth `(received_qty − billed_qty) × buying_price × billing_pct/100`, tagged with `catalog_product_id`/`our_product_id`/`quantity` for audit but **never calling `add_stock()`** — stock already reflects physical reality from the receive step and is not touched by billing discrepancies.
2. **Amount check** (whole bill): compare the formula's `bill_total` (computed from the *billed* quantities just entered) against the actual total the operator typed. On mismatch, auto-suggest one more `note_type='value'`, `source='auto'` debit note for the difference.

Both suggestions appear pre-filled and editable/removable before confirming; the operator can also add manual debit notes exactly as today (`source='manual'`), which still call `add_stock()` when they're item-type (e.g. a genuinely damaged/returned unit).

Sign convention (reuses existing `over`/`under` direction logic in `debit_notes.py`): amount that reduces net payable = `over` (vendor charged more than expected), amount that increases net payable = `under` (vendor charged less than expected).

## AP entries on submit

- **Entry 1** (`entry_type='bill'`): the amount the operator actually typed (`total_billed_amount`). Debit notes on top of this bring net payable to the calculated `bill_total` by default (operator can remove suggestions to accept the vendor's number as-is).
- **Entry 2** (`entry_type='bill'`, only if `billing_pct < 100`): `extra_cash`, computed fresh from final billed quantities — no GST, no discount, no additional charge, no debit-note check (there is no separate paper document for this half to compare against).
- 100%-billing vendors: only Entry 1, as before.

Both entries carry `receipt_id` pointing at the same `StockReceipt` row, so they show up together in the vendor ledger and AP screens.

## Vendor ledger

`build_vendor_ledger` (`app/services/ledger.py`) currently reads placement rows from the `received`/`billed` `VendorOrder` buckets we're removing. Rewrite it to read directly from `StockReceipt`/`StockReceiptLine` for both the "received" and "billed" events (it already has a partial fallback path doing this — make it the only path). No new ledger feature is added — this is purely keeping the existing vendor activity view correct under the simplified data model. Product-level ledger enrichment (order/receive/bill lifecycle events, not just stock deltas) is explicitly deferred to a future project.

## API changes

- `GET /vendors/{id}/billing-context` → `GET /vendors/{id}/billing-terms`, returns the 7 flat fields.
- `PATCH /vendors/{id}/billing-context` → `PATCH /vendors/{id}/billing-terms`, same admin-only guard.
- `VendorPublic` gains the 7 billing fields directly (replaces nested `billing_context` object).
- `GET /stock/vendor/{id}/to-bill` (or equivalent existing "received" list endpoint) filters `StockReceipt.bill_status == 'pending_bill'` instead of the old bucket-based query, and returns `expected_bill_amount`/`expected_extra_cash` per receipt.
- `POST /stock/receipts/vendor-bill` (existing bill-submission endpoint) takes a `receipt_id` (the specific pending-bill receipt) instead of a vendor-wide list of unbilled lines; it validates the receipt is still `pending_bill`, computes both auto-debit-note checks server-side (frontend also runs the same logic for the on-screen preview before submit), creates the debit notes, updates the receipt row in place, and posts 1 or 2 AP entries.

## Frontend changes

- `vendors.js`: vendor create/edit form gets the 7 billing fields (replacing the current "Billing terms (admin only)" JSON-editing section) with plain labeled inputs; label field lets each vendor customize what the additional charge is called.
- `stock.js` bill wizard:
  - "To bill" list shows one row per pending-bill receipt with its frozen expected amount.
  - Step "billed quantity" table: received (read-only) | price | billed qty (editable, defaults to received).
  - "Total bill amount" field: always visible and editable (removes the previous lock-when-`allow_override=false` behavior), pre-filled with `expected_bill_amount`.
  - Debit note step: auto-suggested notes (from both checks) appear pre-populated with an "auto" badge, editable/removable, plus the existing "add manual debit note" UI.
  - Review step: shows Entry 1 (and Entry 2 if split-billing) breakdown before confirming.

## Rollout

1. DB migration: add new vendor columns + seed 3 known vendors + defaults for the rest; add `bill_status`/`expected_bill_amount`/`expected_extra_cash` to `jc_stock_receipts`; add `source` to `jc_debit_notes`; backfill `bill_status='pending_bill'` for the 84 real `vendor_receive` rows (recompute their `expected_bill_amount` from each vendor's now-seeded billing columns).
2. Run the data cleanup (delete 4 test bills + test debit note + test AP entries; deactivate 3 junk vendors).
3. Backend: new schema, rewritten `vendor_receive_bill.py` service (receive freezes expected amount; bill mutates the same receipt row in place; two debit-note checks; 1-or-2 AP entries), rewritten `build_vendor_ledger`.
4. Frontend: vendor form fields, bill wizard changes.
5. Deploy via `scripts/prepare-publish.sh` → push to `_publish/jc-api` (Railway) and `_publish/jc-admin` (Vercel), per existing deployment process.
