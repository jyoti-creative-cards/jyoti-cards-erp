# Round 3 Audit — Catalog / Products / Add-ons Frontend

Scope: `JC/web/admin/js/catalog.js`, `JC/web/admin/js/products.js`, `JC/web/admin/js/addon-products.js` only (frontend correctness). Cross-referenced against `JC/backend/app/routers/catalog.py`, `addons.py`, `stock.py`, and `JC/backend/app/services/catalog_addons.py`, `addon_stock.py`, `stock_levels.py`, `cost_visibility.py`, `permissions.py`. Investigation only, no code modified. Round 2 findings (`round2-catalog-addons.md`) are not repeated except where explicitly re-verified below.

---

## CRITICAL

### C1. Editing a catalog product as a staff member without `costs.read` silently zeroes the buying price (cost) on save — even if they never touch the price field

**File:** `JC/web/admin/js/catalog.js:797` (render), `:911` (save). Root cause interacts with `JC/backend/app/services/cost_visibility.py:28-32` (`hide_cost`) and `JC/backend/app/routers/catalog.py:643-651` (`update_product`).

**Symptom:** `costs.read` is a permission independently gated from `catalog.write` (`JC/backend/app/services/permissions.py:10,21` — "Catalog" and "Costs" are separate groups; a catalog-editing staff role is not required to also see cost). For any such user, `GET /catalog/products/{id}` returns `buying_price: "—"` (the literal masked em-dash string from `hide_cost()`), because `_to_public()` wraps it in `hide_cost(...)` (`catalog.py:140`).

`Catalog.openEdit()` puts that value straight into a `type="number"` input:
```
<input id="ce-buying_price" class="input" type="number" min="0" step="0.01" value="${ctx.esc(p.buying_price)}" />
```
Per the HTML value-sanitization algorithm, a `type="number"` input can't hold the string `"—"` — the browser silently resets the field's `.value` to `""` on render. `Catalog.saveEdit()` then does:
```
buying_price: Number(document.getElementById("ce-buying_price").value),
```
`Number("")` evaluates to `0`, not `NaN` — so there is no validation error, and *every* save (even one where the user only changed, say, category or unit) unconditionally submits `buying_price: 0` in the `PATCH` body. `CatalogUpdate.buying_price` is `Optional[Decimal] = Field(None, ge=0)`, so `0` passes validation cleanly. `update_product()` then does `row.buying_price = data["buying_price"].quantize(...)`, permanently overwriting the real cost with ₹0, and also fires `record_price_change(...)`, writing a bogus "buying price → 0" entry into that product's price history. There is no confirmation, no warning, and the user has no way to know their save silently destroyed the product's cost data — they'd only discover it later via margin/report inconsistencies or by noticing the price history.

This will hit *any* staff member who has `catalog.write` (to manage the catalog) but not `costs.read` (kept from seeing vendor cost/margins) — an entirely realistic, independently-assignable permission combination per `permissions.py`.

**Recommended fix:** In `Catalog.openEdit`/`saveEdit`, detect the masked placeholder (e.g. compare `p.buying_price` to the literal `"—"`, or better, have the backend send a distinguishable sentinel/`null` instead of a display string for numeric fields) and, when masked, omit `buying_price` from the PATCH body entirely (like `selling_price` already conditionally omits when empty) rather than defaulting to `0`. At minimum, add the same `Number.isNaN`/negative guard that `AddonProducts.save()` already has (see H2) so a blank/invalid buying price blocks the save instead of silently coercing to zero.

---

## HIGH

### H1. Editing a catalog product's image via the single-file "replace" input deletes all of that product's *other* photos

**File:** `JC/web/admin/js/catalog.js:884-893`

**Symptom:** Catalog products can have multiple images — the bulk-create wizard's `Photos` column accepts `multiple` files per row (`catalog.js:358-361`) and uploads each with an incrementing `image_index`, producing an `image_keys` array with several entries. But `Catalog.openEdit()`'s image control is a single, non-multiple file input, and `saveEdit()` handles a new upload like this:
```js
let imageKeys = (document.getElementById("ce-image_keys")?.value || "")
  .split(",").map(s => s.trim()).filter(Boolean);
...
if (file) {
  const vendorId = Number(document.getElementById("ce-vendor_id")?.value || 0);
  const nextIndex = Math.max(1, imageKeys.length + 1);   // computed, but then unused
  const result = await uploadImage(vendorId, ourId, nextIndex, file);
  if (result?.key) imageKeys = [result.key];              // <-- discards every prior key
}
```
`nextIndex` is computed as if appending a new image after the existing ones, but the very next line throws away the entire existing `imageKeys` array and replaces it with a one-element array containing only the newly uploaded key. The `PATCH /catalog/products/{id}` body then sends this single-key array, and `update_product()` sets `row.image_keys` to exactly what was sent (`CatalogUpdate.image_keys: Optional[List[str]] = None`, applied via plain `setattr`). Any product that had 2+ photos from the wizard will silently lose all photos except the one just uploaded, the very next time someone "replaces the image" via Edit. The orphaned S3 objects remain in storage but are no longer referenced from any UI.

**Recommended fix:** Either support multiple files in the edit modal's file input and append (`imageKeys.push(result.key)` / `imageKeys[nextIndex-1] = result.key`) instead of overwriting, or, if only a single "cover" image is meant to be editable here, explicitly preserve the rest of the array (e.g. `imageKeys[0] = result.key` instead of `imageKeys = [result.key]`) so uploads beyond index 1 aren't dropped.

### H2. Add-on edit form cannot be saved at all by a staff member without `costs.read` — blocked by the same masked-price defect as C1, but manifesting as a hard block instead of silent corruption

**File:** `JC/web/admin/js/addon-products.js:493` (render), `:520` (save)

**Symptom:** Same root cause as C1 — `AddonPublic.buying_price` is `hide_cost()`-masked to `"—"` for non-`costs.read` staff, and `AddonProducts.openEdit()` puts it into a `type="number"` input which the browser sanitizes to `""`. But here, `save()` uses `parseFloat()` with an explicit guard:
```js
const price = parseFloat(document.getElementById("ae-buying_price").value);
if (Number.isNaN(price) || price < 0) return ctx.toast("Enter a valid buying price", "error");
```
`parseFloat("")` is `NaN`, so this *does* trip and block the save — but it blocks saving *any* field on the add-on (name, description, category, unit, image) for a user who never intended to touch the price and, since the field shows nothing they can meaningfully fill in (they can't see the real cost to re-type it), they have no way to get past this error at all without asking someone with `costs.read`/admin to make the edit for them. The error message ("Enter a valid buying price") is also misleading for someone who isn't trying to change the price.

**Recommended fix:** Same as C1's recommendation — when the incoming value is the masked placeholder, omit `buying_price` from the PATCH body (leave it untouched server-side) instead of forcing the user to re-supply a number they aren't allowed to see.

---

## MEDIUM

### M1. Add-on search silently ignores vendor/city/category even though the shared search box's placeholder promises it

**Files:** `JC/backend/app/routers/addons.py:81-87` (`list_addons` search) vs. `JC/web/admin/js/products.js:267-273` (`renderSearchBar`, placeholder `"Search product code, vendor, city, category…"`) and `js/catalog.js`'s equivalent server queries (`catalog.py:401-411`) / `stock.py:165-176`, which *do* search vendor name, city, category, series, and year group.

**Symptom:** The Products hub has a single search box shared by the "On hand" and "Catalog" tabs, filtered further by the "All / Products / Add-ons" segmented control — but it's the same input, same placeholder, same `Products.onSearch()` handler regardless of which segment is active. For catalog products and stock rows, the backend search genuinely does match vendor business name, city, category, series (`catalog.py:404-411`, `stock.py:166-174`). For add-ons, `list_addons()`'s search only checks `our_product_id`, `name`, and `vendor_product_id` — vendor name, city, and category are not searched at all:
```python
q = q.filter(or_(
    func.lower(AddonProduct.our_product_id).like(s),
    func.lower(AddonProduct.name).like(s),
    func.lower(AddonProduct.vendor_product_id).like(s),
))
```
So a staff member on the Add-ons segment who types a vendor's name or city (exactly what the placeholder invites them to do) gets zero results for add-ons that vendor actually supplies, with no indication that the search is narrower for add-ons than for products.

**Recommended fix:** Either add `vendor_name`/`category` matching to `list_addons()`'s search (joining `Vendor`/`City` the same way `catalog.py`/`stock.py` already do), or show a segment-specific placeholder/hint when `typeFilter === "addons"` so the UI doesn't over-promise.

### M2. "Set threshold" button is shown to (and enabled for) staff who have `catalog.write` but not `stock.write`, and 403s when clicked

**Files:** `JC/web/admin/js/products.js:950-951` vs. `JC/backend/app/routers/stock.py:473-479` (`update_stock_threshold`, `Depends(require_permission("stock.write"))`)

**Symptom:** In the unified product detail view's stock pane:
```js
${ctx.canWrite?.("stock") || ctx.canWrite?.("catalog")
  ? `<button class="btn btn-threshold" onclick="Stock.editThreshold(${id}, ${stock.low_stock_threshold ?? 5})">Set threshold</button>`
  : ""}
```
The button is shown if the user has *either* `stock.write` *or* `catalog.write`. But `PATCH /stock/products/{id}/threshold` requires `stock.write` specifically — there is no `catalog.write` fallback on the backend. `stock.write` and `catalog.write` are independently assignable permissions (`permissions.py:10,20`), so a staff member who can edit the catalog (SKU, category, price) but was not given stock-editing rights will see and be able to click "Set threshold," only to get a 403 from the server.

**Recommended fix:** Change the gate to `ctx.canWrite?.("stock")` only, matching the backend's actual requirement.

### M3. Add-on Receive/Adjust-stock modals close *before* the save request resolves — a failed save silently discards everything the user typed

**File:** `JC/web/admin/js/addon-products.js:173-205` (`openReceiveStock`), `:207-234` (`openAdjustStock`)

**Symptom:** Both modals' "Save" handlers close the modal immediately, then perform the API call inside a `try`:
```js
document.getElementById("addon-rs-ok").onclick = async () => {
  ...
  App.closeModal();                         // <-- closes first
  try {
    await ctx.api(`/addons/${id}/receive-stock`, { method: "POST", body: ... });
    ...
  } catch (e) {
    ctx.toast(e.message, "error");           // modal is already gone; all inputs lost
  }
};
```
(Identical pattern in `openAdjustStock`.) If the request fails for any reason — most notably, a staff member with `addons.write` but not `finance.write` entering a "Total cost paid" on receive, which the backend explicitly 403s on (`addons.py:206-211`, `has_cost and not (auth.is_admin or auth.has("finance.write"))`) — the user just sees an error toast with no modal to retry from. All previously typed quantity/cost/note (receive) or delta/reason (adjust) are gone; they must reopen the modal and re-enter everything from scratch. Since the finance.write split is a documented, intentional permission boundary (the exact comment in `addons.py:210` calls out this is "the same trust boundary as the standalone expense API"), staff hitting this 403 is an expected, not edge-case, occurrence.

**Recommended fix:** Move `App.closeModal()` to after a successful `await`, inside the `try` block (or on to a `.then()`), so a failed save leaves the modal open with the user's input intact and just surfaces the error inline.

### M4. Catalog edit modal's alternative-product pickers don't exclude products already at their 3-alternative cap, unlike the newer Alternatives board — selecting one 400s with no client-side warning

**Files:** `JC/web/admin/js/catalog.js:757` (`altOptions`), `:814-819` (`ce-alt-0/1/2` selects) vs. `JC/web/admin/js/products.js:1237-1239` (`openAltPicker`/`renderAltPicker`, which explicitly filters `if (Number(s.alt_count || 0) >= 3) continue;`). Backend cap check: `JC/backend/app/routers/catalog.py:166-168` (`_link_alternative`).

**Symptom:** `products.js`'s newer "Manage alternatives" board deliberately excludes any candidate product that's already linked to 3 other products, with a code comment explaining exactly why: *"Linking is bidirectional and the backend caps each side at 3 — a candidate already at its own cap would 400 on select, so don't offer it at all."* The older, still-reachable `Catalog.openEdit()` alternatives section (`Alternatives (max 3)`, three `<select>` dropdowns under "ce-alt-0/1/2") has no such filter — it's populated straight from `/catalog/product-options`, an endpoint that doesn't even return an `alt_count` (`catalog.py:277-286` only returns `id`/`our_product_id`). Picking a product there that happens to already have 3 alternatives elsewhere produces the exact 400 (`"product {a_id} already has 3 alternatives"`) the newer picker was built to avoid, surfaced only as a generic error toast after clicking "Save Changes," with no indication of which of the (up to 3) alternative picks was the problem.

**Recommended fix:** Either have `/catalog/product-options` also return `alt_count` and filter maxed-out entries the same way the Alternatives board does, or simply remove the legacy alternatives editor from `Catalog.openEdit()` in favor of directing users to `Products.openAlternativesManager()`, which already handles this correctly.

---

## LOW

### L1. No client-side duplicate-add-on check in the catalog edit modal (relies entirely on the backend's 400)

**File:** `JC/web/admin/js/catalog.js:849-860` (`addEditAddonRow`), `:869-878` (`saveEdit` addon-link collection)

Nothing stops a staff member from picking the same add-on in two different "Add-on Links" rows before saving — `addEditAddonRow()` just appends a fresh row with no awareness of what's already selected, and `saveEdit()` builds the `addonLinks` array without deduping. The backend's `_sync_addon_links()` does catch this with a clear, actionable 400 ("...is listed more than once for this product — remove the duplicate row" — already verified correct in round 2, finding L3), so this isn't a functional bug, just a missed opportunity to prevent the round-trip. Recommend disabling already-selected add-ons in sibling `<select>`s or graying them out, matching the same spirit as M4's fix.

### L2. Bulk-create wizard threads `alternative_our_product_ids` / `addon_links` all the way to the create API, but no wizard step ever offers UI to populate them — dead plumbing

**File:** `JC/web/admin/js/catalog.js:110-125` (`emptyWizardRow`, initializes both to `[]`), `:716-717` (`createAll`, sends both fields to `POST /catalog/products/bulk`)

`emptyWizardRow()` gives every wizard row an `alternative_our_product_ids` and `addon_links` array, and `createAll()` dutifully forwards them — the backend (`catalog.py`'s `bulk_create`) fully supports both, including alternative-not-found errors and duplicate-add-on 400s. But none of the four wizard steps (`renderWizardStep1` through `renderWizardStep4`) render any control that ever assigns to either array, so they are permanently `[]` for every batch-created product. This isn't a break — staff can (and per the module's design, must) add alternatives/add-ons afterward via `Catalog.openEdit()` or `Products.openAlternativesManager()` — but the two fields, their validation paths, and the corresponding backend error messages are entirely unreachable from the batch-create flow, which could confuse a future maintainer into thinking the wizard supports setting these at creation time. Either wire up the UI (there's clearly room, given the backend already handles it) or drop the dead fields from `emptyWizardRow()`/`createAll()`'s payload.

### L3. "Add-ons" segment tab is shown to users without `addons.read`; they get a misleading "No add-ons yet" empty state instead of a permission notice

**Files:** `JC/web/admin/index.html:421` (`ptype-addons` button, unconditionally rendered), `JC/web/admin/js/products.js:600,608` (`ctx.canRead?.("addons")` gates data *fetching*, not the tab's visibility), `:721-727` (empty-state branch for `typeFilter === "addons"`)

A staff member without `addons.read` can still click the "Add-ons" segmented-control button. `Products.load()` correctly skips fetching `/addons` for them, leaving the local `addons` array empty, so `render()` falls into the "No add-ons yet" empty state (`"Add-ons link to catalog products... Switch to Products if you need a full SKU."`) — which reads as "this business has no add-ons," when the truth is "you don't have permission to see them." Contrast with `updatePrimaryAction()`, which does correctly hide the "+ New Add-on" button for users without `addons.write`. Low severity since nothing errors and no data leaks, but the message is inaccurate for this audience. Recommend hiding the "Add-ons" segment button entirely (mirroring how the nav item `nav-products` is already hidden via `canRead("catalog") || canRead("addons")` in `app.js:51,57`) when `!canRead("addons")`, or showing a permission-specific empty state.

### L4. Verified — round 2's M1 (low-stock badge boundary mismatch between products and add-ons) is still present in the backend and therefore still visible in this round's frontend rendering

**Files:** `JC/backend/app/services/stock_levels.py:15` (`quantity < max(threshold, 1)`) vs. `JC/backend/app/routers/addons.py:38` (`qty <= int(row.low_stock_threshold or 5)`); rendered together via `JC/web/admin/js/products.js:508-516` (`stockStatusMeta`) at `products.js:802` (used for both `isStockProduct` and `showsAddonStock` cards in the same grid).

The audit brief asked to verify round 2's M1 fix is correctly reflected in the rendered badge. It is not fixed — the two comparators still disagree at exactly `quantity == threshold`: `stock_levels.py`'s `admin_stock_status_label` (used for catalog/stock products) calls this "in stock," while `addons.py`'s `_stock_status` (used for add-ons) calls the identical situation "low stock." A one-line docstring was added to `stock_levels.py` since round 2 claiming `admin_stock_status_label` is "matching addons.py's `_stock_status`," but the actual `<` vs `<=` comparator was never changed to make that true. Because `Products.stockStatusMeta()` in `products.js` is the single rendering function used for *both* product-in-stock cards and add-on cards in the same unified Products-hub grid, a product and an add-on sitting at the exact same threshold quantity render different-colored badges ("In stock" green vs. "Low stock" amber) side-by-side on the same screen — the exact symptom round 2 flagged, unchanged. No other badge/status-color inconsistency was found: the `out_of_stock`→gray and `negative_stock`→red mappings are identical between `Products.stockStatusMeta()` (`products.js:508-516`, consumed via the list-view color switch at `:850`) and `AddonProducts.stockBadge()` (`addon-products.js:61-70`) — only the underlying backend threshold boundary differs, not the frontend's color logic.

**Recommended fix:** (repeating round 2's recommendation, since it wasn't applied) make `addons.py`'s `_stock_status` use `qty < max(threshold, 1)` to match `stock_levels.admin_stock_status_label`, or have one call the other.

---

## Summary

| Sev | Finding | File:Line |
|---|---|---|
| Critical | C1 — catalog edit silently zeroes buying_price for non-`costs.read` staff on every save | `catalog.js:797,911` |
| High | H1 — catalog edit's image "replace" deletes all other product photos | `catalog.js:884-893` |
| High | H2 — add-on edit form unsalvageably blocked for non-`costs.read` staff (same root cause as C1) | `addon-products.js:493,520` |
| Medium | M1 — add-on search omits vendor/city/category despite shared placeholder promising it | `addons.py:81-87`, `products.js:267-273` |
| Medium | M2 — "Set threshold" shown/clickable for `catalog.write`-only staff, 403s (needs `stock.write`) | `products.js:950-951`, `stock.py:479` |
| Medium | M3 — add-on receive/adjust-stock modals close before save resolves, losing input on failure | `addon-products.js:193,223` |
| Medium | M4 — catalog edit's legacy alternative pickers don't exclude maxed-out (3-alt) candidates | `catalog.js:757-819`, `catalog.py:166-168` |
| Low | L1 — no client-side duplicate-add-on guard in catalog edit (server 400 already clear) | `catalog.js:849-878` |
| Low | L2 — dead wizard plumbing for `alternative_our_product_ids`/`addon_links` (no UI ever sets them) | `catalog.js:110-125,716-717` |
| Low | L3 — "Add-ons" tab visible without `addons.read`; misleading empty state instead of permission notice | `index.html:421`, `products.js:721-727` |
| Low | L4 — verified: round 2's low-stock badge boundary mismatch is still unfixed and still visibly inconsistent in the unified Products grid | `stock_levels.py:15`, `addons.py:38`, `products.js:802` |

**Single most important finding: C1** — any staff member who can edit the catalog but isn't trusted with cost visibility (an explicitly supported, independently-assignable permission split in this system) will silently zero out a product's real buying price the moment they save *any* edit, with no warning, no confirmation, and a bogus price-history entry left behind as the only trace.
