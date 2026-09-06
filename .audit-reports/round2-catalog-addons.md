# Round 2 Audit — Catalog / Stock / Add-ons / Recycle Bin

Scope: `JC/backend/` + `JC/web/admin/` only. Investigation only, no fixes applied.

---

## CRITICAL

### C1. Bill PDF regeneration silently rewrites historical add-on data with today's catalog state

**File:** `JC/backend/app/services/doc_gen.py:109` (`generate_customer_bill_document`), root cause in `JC/backend/app/services/catalog_addons.py:41-87` (`attach_addons_to_totals` / `addon_snapshots_map`)

**Symptom:** Every time a customer bill's PDF is (re)generated — which happens on every "View/Print" from the admin UI, every WhatsApp share (`share.py`), every customer portal download (`shop.py:514`), and automatically whenever a bill is edited (`edit_customer_bill` sets `bill.document_key = None` to force regen) — `generate_customer_bill_document` calls `attach_addons_to_totals(db, dict(bill.totals_json or {}))`. That function looks up the catalog product's *currently linked, currently active* add-ons via `addon_snapshots_map` and, for any line whose product still has at least one live add-on link, **unconditionally overwrites** `line["addons"]` with today's snapshot (`catalog_addons.py:78-83`: `if live: row["addons"] = live`). The result — including the now-wrong `totals_json` — is then written back to the DB (`bill.totals_json = totals; flag_modified(...)`) and committed by every caller (`doc_gen.py:139-140`, committed at `customer_orders.py:1138`, `shop.py:515`, `share.py:54/64/178`). So if the add-on links on that product change after the bill was issued (quantity changed, one add-on swapped for another, a new add-on added, etc.), re-opening/reprinting/re-sharing an old, already-invoiced bill will show — and permanently persist — a *different* add-on list than what the customer actually received at billing time. This corrupts a customer-facing, quasi-legal accounting document after the fact, with no audit trail of the change. (By contrast, the customer *order* PDF correctly prefers the frozen `CustomerOrderLine.addons_json` snapshot and only falls back to live data for legacy rows without one — `doc_gen.py:61`. The bill path has no such guard.)

**Recommended fix:** In `generate_customer_bill_document`, never call `attach_addons_to_totals` against an existing bill's stored `totals_json`; only stamp add-ons once, at bill-creation/edit time (as `_persist_totals_addons` already does in `customer_bill_process.py`), and have PDF regeneration read whatever is already frozen in `totals_json`/`CustomerBillLine`. If a bill's totals are missing add-ons (legacy rows), backfill once and never overwrite again.

---

## HIGH

### H1. Soft-deleted ("recycle-binned") add-ons keep auto-moving stock behind the scenes

**File:** `JC/backend/app/services/addon_stock.py:49-89` (`deduct_addons_for_product`), contrast with `JC/backend/app/routers/addons.py:275-280` (`delete_addon`) and `:245-273` (`receive_addon_stock`/`adjust_addon_stock`)

**Symptom:** `deduct_addons_for_product` (called from `reserve_stock`/`restore_stock` on every customer order placement/cancel, and from `customer_returns.py`/`void_service.py` on every return void/restore) fetches `CatalogAddonLink` rows by `catalog_product_id` only and calls `add_addon_stock` on every linked add-on **without checking `AddonProduct.is_active` or `deleted_at`**. Its only guard is a `try/except ValueError`, which only fires if the add-on row is hard-*purged* (gone from the DB), not soft-deleted. Meanwhile the manual endpoints a staff member would use to touch a deleted add-on's stock (`POST /addons/{id}/adjust-stock`, `POST /addons/{id}/receive-stock`) both correctly 404 with `if not row or not row.is_active`. Net effect: a staff member "deletes" (recycle-bins) an add-on expecting it to be inert, but every customer order/cancel/return on any catalog product still linked to it keeps silently debiting/crediting its `quantity_on_hand` and writing `AddonStockLedger` rows the whole time it sits in the recycle bin — while the admin UI has no way to inspect or correct that stock (the detail/adjust screens are only reachable for active add-ons). When the add-on is eventually restored, its on-hand count reflects however much order activity happened while it was "deleted," which will look inexplicable to staff and won't match the number they saw right before deleting it.

**Recommended fix:** In `deduct_addons_for_product`, join/filter on `AddonProduct.is_active.is_(True), AddonProduct.deleted_at.is_(None)` the same way `addon_snapshots_for_product`/`addon_snapshots_map` already do, and skip (with the same "not blocking" logging) any link whose add-on is currently soft-deleted.

---

## MEDIUM

### M1. Low-stock badge boundary disagrees between products and add-ons for the *same* threshold value

**Files:** `JC/backend/app/services/stock_levels.py:4-27` (`stock_status_label` / `admin_stock_status_label`, used for catalog products) vs. `JC/backend/app/routers/addons.py:31-39` (`_stock_status`, used for add-ons)

**Symptom:** Both are meant to be the same "low/out/negative" language (the addons.py docstring at line 22-24 explicitly says it mirrors `admin_stock_status_label`), but the boundary condition differs by one: products use `quantity < max(threshold, 1)` (line 15) — so `quantity == threshold` is **"in stock"** — while add-ons use `qty <= int(row.low_stock_threshold or 5)` (line 38) — so `quantity == threshold` is **"low stock"**. The same frontend component renders both with identical visual language (`Products.stockStatusMeta` in `products.js:508-516`, and `stockBadge` in `addon-products.js:61-70`), so a product sitting exactly at its threshold shows a green "In stock" badge while an add-on sitting exactly at the same threshold number shows an amber "Low stock" badge — with no visible reason for the difference. This directly undermines the "addons and regular products use consistent visual language" expectation from the audit brief.

**Recommended fix:** Make both use the same comparator (recommend addons.py switch to `qty < max(threshold, 1)` to match products, since `stock_levels.admin_stock_status_label` is the more carefully documented/tested version), or extract one shared helper both call.

### M2. "Void (recycle bin)" on a Confirmed-bucket order doesn't do what its own tooltip promises

**Files:** `JC/backend/app/services/void_service.py:379-406` (`void_customer_placement`), `JC/web/admin/js/customer-orders.js:1252-1261` (`voidPlacement`), button surfaced at `customer-orders.js:858` and `:898`

**Symptom:** The "Void (recycle bin)" action is offered on every placement row in every bucket an admin can view, including the "Confirmed" (`open`) bucket — see the generic history renderer at `customer-orders.js:878-903` which is reached for `currentBucket === "open"`. Its confirm prompt explicitly tells the admin: *"Void order — Admin-only, moves to recycle bin, restorable later. **Cancels unbilled qty first if still open.**"* But the backend only performs that cancel step when `placement.status == "received"` (`void_service.py:390`): `if placement.status == "received": try: cancel_customer_placement(...)`. Once an order has been confirmed via "Confirm order," `confirm_received_order` flips every one of its placements to `status = "open"` (`customer_order_flow.py:518-524`), so this condition is now false for exactly the "still open" orders the tooltip is talking about — voiding one of these just sets `deleted_at` and hides it, with **no** call to release any reserved/unbilled quantity. The reserved stock and the customer's running `CustomerOpenLine` balance are left completely untouched (which may be intentional given the FIFO-merge design documented at the top of `void_service.py`), but the tooltip's plain-language promise is simply false for this common case, and the placement's own paperwork/audit trail disappears into the recycle bin while its stock effect keeps living on, unlinked to any visible order.

**Recommended fix:** Either extend the cancel to also cover `status == "open"` placements with unbilled qty (if that's feasible given the FIFO merge), or fix the tooltip/confirm text so it accurately says stock is only released pre-confirmation ("New" bucket) and confirmed/open orders are hidden as-is.

---

## LOW

### L1. Add-on "Delete" confirm gives no warning that stock keeps moving while "deleted"

**File:** `JC/web/admin/js/addon-products.js:557-570` (`deleteAddon`)

**Symptom:** The only confirmation shown is `confirm("Move this addon product to recycle bin?")`. Given finding H1, this is actively misleading: the add-on's stock is *not* frozen once it's "deleted" — it keeps moving for as long as any catalog product remains linked to it. A staff member has no way to know this from the UI.

**Recommended fix:** Once H1 is fixed (deduction stops on delete), this is moot. Until then, warn in the confirm dialog if the add-on has any active `CatalogAddonLink`s, and/or surface an "Unlink before deleting" nudge.

### L2. Verified — not a bug: catalog/stock/add-on search never uses `exact_int_columns`

**Files:** `JC/backend/app/routers/catalog.py:401-412` (`list_products`), `JC/backend/app/routers/stock.py:165-179` (`list_stock`), `JC/backend/app/routers/addons.py:81-87` (`list_addons`)

All three use plain `lower(col) LIKE '%term%'` substring search on `our_product_id`/name/etc. — none of them import or use `token_search.py`'s `exact_int_columns` mechanism. That numeric-exact-match behavior (`token_search.py:15-38`) is deliberately scoped only to `vendor_number`/`party_number` in `vendors.py:105` / `customers.py:248`. So a catalog SKU like `"100 ENVELOPE"` fuzzy-matches normally when a user searches `"100"` — the concern raised in the audit brief does not materialize anywhere in the codebase today. Flagging as explicitly verified per the brief's request, no action needed.

### L3. Verified — not a bug: `_sync_addon_links` duplicate/add/remove/quantity-edit handling is correct

**File:** `JC/backend/app/routers/catalog.py:198-224`

Editing a product's add-on list does a full delete-then-recreate of `CatalogAddonLink` rows on every save, keyed by resolved `addon_product_id`, with an explicit `seen_aids` check that raises a clear `400` ("...is listed more than once for this product...") instead of hitting the `(catalog_product_id, addon_product_id)` unique constraint and 500ing, and instead of silently dropping the duplicate. Add/remove/quantity-change on save all behave correctly. No action needed.

### L4. Verified — not a bug (but worth knowing): "Restore" on a cancelled bill/order un-hides only, doesn't un-cancel

**Files:** `JC/backend/app/services/void_service.py:336-357` (`restore_customer_bill`), `:409-423` (`restore_customer_placement`)

This is a deliberate, documented design choice (module docstring in `void_service.py:280-289`: the shared FIFO `CustomerOpenLine` balance "isn't safely invertible once later orders/bills have touched the same customer+product"). The API response message and the recycle-bin detail pane both correctly disclose this ("Restoring un-hides the bill/order only — it stays cancelled if it already was," `app.js:2172`/`2182`). The one gap: this caveat is **only** shown after opening the item's detail page — the recycle-bin list row itself (`recycle_bin.py:144-151`, `:152-161`) gives no hint, so an admin skimming the list and clicking "Restore" straight from a row-level action (if one existed) wouldn't see it. Currently restore requires opening detail first, so this is low-risk as-is; flagging only in case a quick-restore-from-list action is ever added.

---

## Summary

| Sev | Finding | File:Line |
|---|---|---|
| Critical | C1 — bill PDF regen overwrites historical add-on data | `doc_gen.py:109`, `catalog_addons.py:78-83` |
| High | H1 — soft-deleted add-ons still auto-move stock | `addon_stock.py:65-89` |
| Medium | M1 — low-stock badge boundary mismatch (products vs add-ons) | `stock_levels.py:15` vs `addons.py:38` |
| Medium | M2 — "Void" tooltip claim false for Confirmed-bucket orders | `void_service.py:390`, `customer-orders.js:1253` |
| Low | L1 — no delete-time warning that add-on stock keeps moving | `addon-products.js:559` |
| Low | L2 — verified, no bug (exact-numeric search scope) | `catalog.py:401`, `stock.py:165`, `addons.py:81` |
| Low | L3 — verified, no bug (`_sync_addon_links` correctness) | `catalog.py:198-224` |
| Low | L4 — verified, minor caveat-visibility gap | `void_service.py:336-357` |

**Single most important finding: C1** — every time an already-issued customer bill's PDF is reprinted, shared, or regenerated, the system silently rewrites and permanently commits the bill's stored add-on data to whatever the *linked catalog product's add-ons happen to be today*, discarding what was actually billed. This is the one finding that corrupts a persisted financial/customer-facing record after the fact rather than just misbehaving in the UI.
