# JC ERP Audit — Product / Catalog / Add-ons / Stock Module

Scope: `JC/backend/app/{models,routers,services}` (catalog, addons, stock) and
`JC/web/admin/js/{products,catalog,addon-products,stock}.js`. Read-only investigation,
no code changed. Baseline: `python3 -m pytest tests/ -q` → **117 passed** before this
audit (confirmed by re-running).

---

## Technical Findings

- **[CRITICAL]** `app/services/customer_returns.py:187` (and mirrored in
  `app/services/void_service.py:452` void, `:494` restore) — `create_customer_return`
  credits stock back via `add_stock()` directly instead of going through
  `restore_stock()` in `customer_order_flow.py`. Since `deduct_addons_for_product` is
  wired *inside* `reserve_stock`/`restore_stock` (not at each call site), this path
  completely bypasses add-on stock restoration. **A customer returning a
  product-with-add-ons never gets that add-on stock credited back** — the add-ons stay
  permanently "consumed" from the day the original order was placed, even though the
  physical card (with its stickers/lace) came back into the godown. This is exactly the
  bypass class of bug the add-on rollout needed to guard against, and it's real: `git
  grep add_stock` shows this call site does not route through `restore_stock`.
  `tests/test_addon_stock.py` has no return-flow test, so this shipped untested.

- **[HIGH]** `app/routers/recycle_bin.py:427-441` (`purge_catalog_product`) and
  `app/routers/recycle_bin.py:444-455` (`purge_addon`) — neither checks for rows that
  still reference the product/addon under an `ondelete="RESTRICT"` FK before calling
  `db.delete(row)`: `jc_stock_balances`, `jc_stock_ledger`, `jc_stock_receipt_lines`,
  `jc_customer_order_lines`, `jc_customer_bill_lines`, `jc_customer_return_lines` all
  RESTRICT on `catalog_product_id`; `jc_addon_stock_ledger` RESTRICTs on
  `addon_product_id`. Compare with `purge_vendor` (checks `cat_n`/`addon_n` first) and
  `purge_customer_bill` (checks return-line count first) a few dozen lines away in the
  same file — the catalog/addon purge paths never got the same treatment. **Any
  catalog product or add-on that has ever had stock movement, a sale, or a return will
  throw an unhandled `IntegrityError` (500) when an admin tries to permanently delete
  it from the recycle bin** — i.e. purge only works for products added by mistake and
  never touched, which is the rare case, not the common one.

- **[HIGH]** No live UI path calls `POST /stock/products/{id}/adjust` (manual stock
  correction / write-off for regular catalog products) even though the backend
  endpoint, permission check, and ledger trail are fully implemented and tested. See
  Functional/Wiring section for the full trace — flagged here too because it means
  breakage/loss/miscount on finished-card stock has **no correction mechanism** at all
  in the current UI, unlike add-on stock which does have a working "Adjust Stock" path.

- **[MEDIUM]** `app/routers/addons.py:220,222` — `receive_addon_stock` defaults
  `Expense.expense_date` to `date.today()` instead of `today_ist()` from
  `app/services/biz_date.py`. If the app server runs in UTC (typical for Railway), any
  stock receipt logged between 00:00–05:30 IST gets an Expense dated one calendar day
  *early*. This is precisely the "naive UTC date-boundary" bug class the repo's own
  conventions warn about (`biz_date.py` docstring), and it directly affects a financial
  record (the Expense entry), not just a display filter.

- **[MEDIUM]** `app/services/stock_receipt.py:55-64` (`add_stock`) and
  `app/services/customer_order_flow.py:106-115` (`reserve_stock`) — first-ever stock
  touch on a catalog product does a check-then-insert: `SELECT ... FOR UPDATE` returns
  no row (nothing to lock yet), so on a race two concurrent requests can both fall into
  the `if not balance:` branch and both `INSERT` a `StockBalance` row. `catalog_product_id`
  has a DB `unique=True` constraint, so the loser gets a raw, uncaught `IntegrityError`
  (500) instead of a friendly retry. Elsewhere in the very same file,
  `get_or_create_open_order`/`get_or_create_customer_order` handle this exact race with
  `db.begin_nested()` + `except IntegrityError: retry`; that pattern was not reused here.
  Low probability (only matters on a brand-new product's very first stock event) but a
  real gap.

- **[MEDIUM]** `app/services/dashboard.py:30,47-51` — the home dashboard's "needs
  action" low-stock count uses a hardcoded `COALESCE(quantity_on_hand,0) <= 10`
  threshold against `jc_catalog_products`/`jc_stock_balances` directly, ignoring each
  product's own configurable `low_stock_threshold` (which the Products hub's
  `stock_status_label()` correctly uses). A product with `threshold=20` and `qty=15` is
  "low_stock" in the Products hub but invisible on the dashboard; a product with
  `threshold=2` and `qty=8` is "in_stock" in the hub but counted as low on the
  dashboard. Also, this query only counts `jc_catalog_products` — **add-on products are
  never included**, so an add-on running out of stock (the brand-new feature) never
  surfaces on the home dashboard's attention widget. `dashboard.py:30` also uses
  `date.today()` rather than `today_ist()` for its own "today" pulse — same UTC
  day-boundary risk as above, applied to today's sales/purchase counters.

- **[MEDIUM]** `app/routers/recycle_bin.py:304-321` (`restore_catalog_product`),
  `:323-335` (`restore_addon`), `:427-441`/`:444-455` (the two purges above) — none of
  these four call `response_cache.invalidate(...)`. Contrast with
  `restore_receipt_endpoint`/`purge_receipt_endpoint`/etc. a few dozen lines further
  down in the same file, which all invalidate `stock:`/`shop:` caches. Restoring or
  purging a catalog product or add-on from the recycle bin will not be reflected in
  `/catalog/products`, `/stock/products`, or the customer-facing `/shop` list until the
  cache TTL (25–90s) naturally expires — looks like the action silently no-op'd.

- **[LOW]** `app/routers/catalog.py:197-218` (`_sync_addon_links`) — no de-dup check on
  `addon_our_product_id` within one request's `addon_links` list. Two identical addon
  SKUs in the same payload (e.g. a UI bug or copy-paste) both resolve to the same
  `addon_product_id` and hit the `uq_jc_catalog_addon_link` unique constraint on
  flush/commit, surfacing a raw `IntegrityError` instead of a clean 400.

- **[LOW]** `app/services/doc_gen.py:109` (`generate_customer_bill_document`) —
  re-fetches *live* add-on links via `attach_addons_to_totals` every time a bill PDF is
  (re)generated, while `customer_bill_process.py`'s `_persist_totals_addons` (lines
  314, 829, 1242) bakes an add-on snapshot into `bill.totals_json` only at
  creation/edit time. If a catalog product's add-on links change after a bill is
  issued, re-printing/re-downloading that bill's PDF can show different add-ons than
  what's stored on the bill record. Likely intentional ("what this card actually ships
  with today") but worth a product decision, since it contradicts the snapshot
  approach used everywhere else (order lines' `addons_json`, price history, etc.).

- **[LOW]** `app/routers/addons.py:78` (`list_addons`) filters only
  `AddonProduct.is_active.is_(True)`, unlike `catalog.py`'s consistent
  `is_active.is_(True), deleted_at.is_(None)` double-filter. Functionally identical
  today (both flags are always set together in `delete_addon`), but it's an
  inconsistent defensive pattern that would silently break if a future migration/import
  script ever sets one flag without the other.

- **[LOW]** `app/services/addon_stock.py:80` (`deduct_addons_for_product`) swallows
  `ValueError` from a missing addon with a bare `except ValueError: continue` — correct
  choice to never block the customer order, but there's no logging, so a broken/deleted
  addon link fails silently forever with no operational visibility.

- **Verified clean (no bug found):** the "day-scoping" bug class explicitly called out
  in this audit's brief was checked against this module's queues — `stock_status`
  filtering (`in_stock`/`low_stock`/`out_of_stock`/`negative_stock`) in both
  `app/routers/stock.py` and `app/routers/addons.py`, and the `no_sell_price`/`no_addons`
  catalog filters, are all status-based, not date-based, both server-side and in
  `products.js`'s attention chips. No hidden-by-date queue items found here.

---

## Functional / Wiring Findings

- **[CRITICAL] "Adjust stock" for regular catalog products is dead — the only working
  action for it is unreachable.** `Stock.adjustStock()` in
  `JC/web/admin/js/stock.js:2034-2058` correctly posts to
  `POST /stock/products/{id}/adjust` (admin-only, backend fully works, covered by the
  existing test suite's stock ledger paths). Its **only** call site is a button inside
  `Stock.openDetail()` (`stock.js:117`). But `Stock.openDetail` is itself dead: every
  live entry point into a product's detail view goes through
  `Products.openProductDetail()` in `products.js` (grid/list card clicks, "Open stock +
  ledger" fallback in `catalog.js:215` never fires either, because `Catalog.openDetail`
  at `catalog.js:200-203` returns early via `Products.openProductDetail` before it ever
  reaches the `Stock.openDetail(p.id)` line). `Products.openProductDetail`'s own
  `stockPane` (products.js, ~lines 950-984) renders "Set" (sell price) and "Set
  threshold" buttons but **no "Adjust stock" button anywhere** — confirmed by grepping
  `products.js` for `adjustStock`/"Adjust stock": zero matches. Net effect: **there is
  currently no way for anyone, including admins, to record a manual stock
  correction/write-off for a regular product through the app UI**, despite the backend
  supporting it end-to-end. (By contrast, the equivalent add-on flow —
  `AddonProducts.openAdjustStock` — is correctly wired and reachable from
  `AddonProducts.openDetail`.)

- **[HIGH]** Recycle-bin purge for catalog products/add-ons (see Technical §2) will
  surface as a raw, unfriendly error toast (`ctx.toast(e.message, "error")` in whatever
  generic recycle-bin JS handles this — the 500's JSON body, if any, won't have a
  helpful `detail` message) instead of the clean "still linked to N receipts — purge
  those first" style message used for vendors/cities elsewhere in the same file.

- **[MEDIUM]** Cache-invalidation gap on restore/purge (Technical §6) manifests to
  staff as: restore a deleted catalog product or add-on from the recycle bin → success
  toast → go to Products hub → item is still missing (or a purged item still shows) for
  up to ~90s, because `/catalog/products` and `/stock/products` list responses are
  cached and not invalidated by these two endpoints.

- **Verified working, end-to-end:**
  - Catalog bulk-create wizard → `POST /catalog/products/bulk` → response shape
    (`CatalogProductPublic[]`) matches what step-4 review renders.
  - Catalog edit (single product, alternatives, add-on links) → `PATCH
    /catalog/products/{id}` → correctly re-opens detail view on the right tab
    (`editReturnTo`) after save.
  - Add-on wizard create/edit/delete → `/addons` CRUD — request/response shapes match;
    UI refresh via `refreshAfterMutation()` correctly invalidates `/addons` cache and
    re-runs `Products.refreshHub()`.
  - Add-on "Receive Stock" / "Adjust Stock" → `POST /addons/{id}/receive-stock` /
    `/adjust-stock` — both wired correctly, refresh detail view on success, surface
    backend error messages via `ctx.toast(e.message, ...)`.
  - "Manage alternatives" board (`Products.openAlternativesManager` →
    `/catalog/alternatives-board`, `addAlternative`/`removeAlternative`) — all wired
    correctly, including the bidirectional-link mirroring on both create paths.
  - Bulk "Set sell prices" table (`no_sell_price` attention filter) → `POST
    /stock/products/selling-price/bulk` — payload/response match, reloads afterward.

- **[LOW]** Dead/no-op registrations left over from the "Products hub" refactor:
  `addon-products.js:23` (`TableUtils.register("addons", renderView)` where
  `renderView` is `/* legacy — Products hub owns list */`), `catalog.js:177`
  (`TableUtils.register("catalog", () => {})`), and `stock.js:40`/`stock.js:66`
  (`render()` is a no-op). Harmless today since nothing calls `TableUtils.render(...)`
  for these keys anymore, but it's dead wiring that will confuse the next person who
  goes looking for "where does the catalog table render."

---

## PM/UX Suggestions

- **[CRITICAL]** The add-on "Receive Stock" / "Adjust Stock" flow
  (`addon-products.js:208-244`) is three sequential native `prompt()` dialogs
  (quantity → optional cost → optional note). For a real financial action that can also
  create an Expense record, this is too thin: no visible current-stock number while
  typing, no numeric keypad guarantee on mobile, no way to see/confirm all three fields
  together before submitting, no cancel-and-review step, and one typo in the cost field
  silently posts a wrong Expense with no confirmation screen. Recommend a proper modal
  form (quantity, unit cost, computed total, date, vendor bill reference, note) matching
  the quality bar of the rest of the app's wizards/edit modals. Same critique applies
  to the equivalent regular-product flows (`stock.js` `adjustStock`/`editThreshold`
  /`setSellingPrice`), which use the identical `prompt()` pattern — this is a
  house-wide pattern, not just an add-on gap, and worth fixing once, consistently.

- **[CRITICAL — pairs with Technical/Functional finding]** Staff/admin currently have
  **no way to record stock loss/breakage/miscount for regular products** (see Functional
  §1). For a wedding-card trading business, breakage and miscounts against a physical
  godown are routine — this is a basic, expected inventory operation that's silently
  missing from the live UI even though it was clearly built and tested on the backend.

- **[HIGH]** Double-submission risk on the add-on Receive/Adjust flows: the "Receive
  Stock"/"Adjust Stock" buttons stay enabled during the `await ctx.api(...)` call after
  the prompts close (no `btn.disabled = true` guard, unlike `Catalog.createAll()` and
  `AddonProducts.create()` which do disable their submit buttons). A staff member who
  taps the button twice in quick succession — plausible on a spotty warehouse wifi
  connection — can fire two "receive 50 units" calls, doubling both the stock credit
  and the linked Expense.

- **[MEDIUM]** Add-on stock purchases post as a generic `Expense` (category "addon
  stock") rather than flowing through the vendor receive → bill → AP pipeline that
  regular catalog products use. For a small business trying to reconcile "what do I
  owe each vendor," add-on purchases will never show up in that vendor's AP ledger or
  pending-bill queue — only as a loose Expense line, disconnected from the vendor
  relationship. Worth a deliberate call on whether this is fine (add-ons are cheap,
  informal purchases) or should eventually get the same AP treatment as products.

- **[MEDIUM]** Terminology/mental-model: "Stock" tab = "What you have in godown" and
  "Catalog" tab = "Full catalog · set sell price, add-ons, alternatives" are both
  labelled "Products" at the top and show visually near-identical cards for the same
  underlying SKUs. New staff need to learn that price/add-on/alternative *editing*
  lives in Catalog while day-to-day stock *quantities* live in Stock — and the attention
  chips split the same way (Low/Out/Negative only in Stock; "Needs sell price"/"No
  add-ons" only in Catalog), so a staff member doing a daily "what needs attention"
  sweep has to check two separate tab+chip combinations to see everything. Consider
  either a single unified "needs attention" chip strip that's tab-independent, or
  clearer tab names (e.g. "Warehouse" vs "Master data").

- **[LOW]** Deleting a catalog product or add-on shows only a generic "Move to recycle
  bin?" `confirm()` — it doesn't tell the admin how many alternatives, add-on links, or
  current on-hand stock will be orphaned/hidden by the action. A one-line summary
  ("Also removes 2 add-on links and unlinks 1 alternative") would prevent surprises,
  especially since purge later will hard-fail anyway if there's real stock history (see
  Technical §2) — better to surface that constraint at delete time too.

- **[LOW]** There's a bulk "Set sell prices" table for the "Needs sell price" queue,
  which is a nice touch — but no equivalent bulk tool for updating buying prices when a
  vendor announces a broad rate change; each product still needs an individual Edit.
  Given vendor rate changes are usually announced product-line-wide, a bulk
  buying-price update (mirroring the existing bulk sell-price UI) would save real time.

- **Positive note:** the attention-chip / queue system (Low stock / Out / Negative /
  Needs sell price / No add-ons) is well designed and — importantly — correctly
  status-filtered rather than date-filtered, avoiding the day-scoping bug class this
  audit was specifically watching for. The add-on stock ledger detail view (movements +
  price history + change history in one place) is also a solid, consistent piece of UI.
