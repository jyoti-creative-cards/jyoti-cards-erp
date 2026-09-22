# Document consistency

Date: 2026-09-22
Status: design approved in chat; awaiting review of this file
Scope: JC ERP only (`JC/backend/`, `JC/web/admin/`, customer portal routes in `JC/backend/app/routers/shop.py`). One system-wide rule. Not a shortcut on each screen.

This spec is the single implementation-plan input.

## Problem

The same fact is read from different places.

A backdated order stores the date the user typed on `placed_at`. The party ledger shows that date. The New / Today / Past screens show `updated_at` or `created_at`, which is the moment someone clicked save, so the order looks like today.

A product rename updates `CatalogProduct`. Stock and the catalog show the new name. Orders, bills, debit notes, and ledgers show `our_product_id` copied onto the line when it was created. Photos, add-ons, and alternatives are worse: several PDFs and the portal order history call the live catalog (`prod.image_keys`, `addon_snapshots_for_product`) even after the document was issued.

Cancelling a bill sets `cancelled_at`. The order screen shows cancelled. The party ledger ignores that flag and still lists the bill as open. A void (`deleted_at`) is hidden. Cancel is not.

The same split exists for customers, vendors, bill series, freight agents, cities, routes, payment modes, and category / series / unit lookups. Master screens are live. Issued documents sometimes join the live row and sometimes use a stale copy.

## Goal

One document has one date, one saved card, and one status, on every screen that shows that document.

- Open work follows the live masters.
- An issued document does not change when a master changes.
- Cancel, void, close, payment, and an explicit edit of that document show up everywhere that document appears.
- Search, reports, PDFs, share, the recycle bin, and the customer portal use the same facts as the admin screen.
- Nothing bypasses this. A new screen that joins the live catalog for an issued document is a bug.

## Non-goals

- Rewriting stock on hand, outstanding balances, credit limit, freight balance due, or the shop catalog. Those are live on purpose.
- Changing activity-log time or price-history time. Those record when an edit happened.
- Recovering a photo, add-on, or party detail that was never stored and was already overwritten before this ships. Existing documents are frozen as well as the stored row and entity history allow. After that they do not move.
- A second history product. `EntityHistory` stays the log of master edits. The document card is what that document said.

## Open versus exercised

**Open.** Still only inside the system. Nothing has been handed over and it is not money yet.

- Customer order in New or Confirmed, not billed.
- Vendor order placed, goods not received.
- A bill or receipt form that has not been saved.
- The part of a partial bill that is still unbilled.

Open work reads live masters. A rename, a new photo, a new add-on, a new alternative, a category rename, a party edit, or a price change shows here.

**Exercised.** It has left the building or become money.

- Customer bill saved (PDF can be printed).
- Customer order or bill closed.
- Vendor goods received, or a vendor bill posted.
- A debit note posted.
- A customer return posted.
- A payment posted.
- An expense saved.
- A freight charge posted.
- Anything sitting as payment due.

The quantity just billed on a partial bill is exercised. The quantity still open stays open.

At the transition, the system copies the live masters onto that document once. Later master edits do not touch it. The next open order uses the new masters.

Cancel, void, and payment do not rewrite the card. They change the status of that same row. Every screen reads that status.

An explicit Save on an existing bill or receipt does rewrite that document's card, and only that card. See Edit below.

## The card

One JSON snapshot on the exercised document. `present()` is the only reader. Admin JS renders `present()` fields. It does not format `created_at`, `updated_at`, or a copied item code on its own.

The card holds:

- Product: our code, vendor code, year group, category, series, unit, marking, buying price, selling price, photo keys, add-ons, alternatives.
- Party: business name, person name, phone, address, city name, route name, GST, party number or vendor number, markers, payment type. Vendor billing terms that were applied (`billing_pct`, GST rate, discount, extra-charge label) when the document is a vendor bill.
- Bill series label and prefix, beside the issued number. The issued number itself never changes.
- Freight agent name.
- Payment mode name, when the document is a payment.
- Business date of the document.
- Status of the document.

Addon products are their own master (name, photo, price, vendor). If a document names an add-on, the card copies that add-on too.

Staff names stay the `created_by_name` string already stored on the row. Do not re-join `Staff`.

## Dates

The date on a document is the business date the user typed.

| Document | Field |
|---|---|
| Customer order | `placed_at` |
| Customer bill | `bill_date` |
| Vendor order | `placed_at` |
| Vendor receipt | `received_at` |
| Vendor bill | the bill date already stored (`billed_at`) |
| Debit note created with a bill | that bill's business date |
| Return | its business date (add one if the row has only `created_at`) |
| Payment | `value_date` |
| Expense | `expense_date` |
| Freight charge tied to a bill | that bill's business date |
| Freight settlement or advance with no bill | its own business date (add one if the row has only `created_at`) |
| Manual loss | `loss_date` (date only; there is no master card) |

Today means that business date is today in Asia/Kolkata. Past means it is earlier. A backdated order entered today sits in Past, with the backdate, on the order screen and in the party ledger.

`created_at` and `updated_at` stay as audit clocks. They are not the date on the document and they do not pick the Today tab.

Activity log rows and price-history rows keep their own event time.

## Status

`present()` returns the current status of that row: open, billed, cancelled, closed, or voided.

- `cancelled_at` set: every screen, including the party ledger, the portal, and reports, shows cancelled. The card's names and prices stay. The row stays in history.
- `deleted_at` set (void): hidden everywhere except the recycle bin. The recycle bin shows the saved card and the voided status.
- A payment reduces what is owed. The bill line still shows the saved card. Outstanding totals stay live math.

The party ledger must not list a cancelled bill as a normal open bill.

## Masters that stay live

These screens always show the current record: People (customers, vendors), Products (catalog, stock, add-on stock), Setup (routes, cities, freight agents, lookups, bill series, payment modes, staff), the shop catalog, stock on hand, credit limit, outstanding, freight balance due, ageing of who owes today, and today's route collection list.

Category, series, and unit live in `CatalogLookup`. A product stores the text. Renaming a lookup updates live products that still use the old text. Exercised cards keep the old word.

`EntityHistory` already tracks customer, vendor, catalog product, and add-on product. Extend it to freight agent, bill series, city, route, payment mode, and catalog lookup, so master edits stay auditable. The document card is still what an issued document displays. Do not display an issued document by looking up "whatever history says now".

## Documents that freeze

`present()` covers all of these. PDFs and share use the card, never a live join.

- Customer order, customer order PDF
- Customer bill, bill PDF, copies
- Vendor order, vendor placement PDF
- Vendor receipt and vendor bill, receipt PDF
- Debit note
- Customer return, return PDF
- AR ledger and AR statement PDF
- AP ledger and AP statement PDF
- Freight ledger, freight statement PDF, freight payment PDF
- Expense lines that name a freight agent or an add-on
- Daybook for a past day
- GST, revenue, cost, and P&L lines that cite a document
- Recycle bin
- Customer portal order history, order PDF, and bill PDF

Portal product search and the shop catalog stay live.

## Reports and search

Amounts come from the document (`grand_total`, `line_total`, ledger `amount`), not from today's catalog price.

Each line shows the label on that document's card.

Totals group by stable id: `catalog_product_id`, `customer_id`, `vendor_id`, `freight_agent_id`. A rename must not split one product or one party into two report rows. The group title may show the current master name. The lines under it keep the saved labels.

Search uses the same rule. An open order matches the current name. An issued bill matches the name on its card, and still matches the current name of the same `catalog_product_id` so staff can find it after a rename.

## Edit bill and edit receipt

Save on an existing customer bill or vendor receipt is an edit of that document, not a master change.

The save rewrites that document's card from what the user saved. It does not refill blank fields from today's catalog. Every screen of that bill, and a reprinted PDF, shows the new card. Clear `document_key` so the next PDF is generated from the new card.

A master edit that happens later does not touch this card.

## Cache

A master edit invalidates open-document caches immediately: catalog, stock, shop products, open customer orders, open vendor orders.

An exercised document's cache changes only when that document is saved, cancelled, voided, or restored.

The admin frontend cache must drop those prefixes on the same mutations. A five-minute stale open order is a bug.

## Backfill

For documents already exercised:

1. Build the card from columns already on the row (item code, prices, quantities, bill number, charges, party id, applied billing percent, payment mode string, `created_by_name`).
2. Where `EntityHistory` has a snapshot valid at the document's business date, use it for customer, vendor, product, and add-on fields that the row does not already store.
3. Where nothing was stored (a photo, an add-on list, an agent display name), copy the current live value once into the card.

Step 3 stops future drift. It does not restore a value that was overwritten before history existed. Do not leave those fields as live joins.

## Enforcement

- Routers, PDFs, portal, reports, and search call `present()`. They do not assemble display names, photos, or dates themselves for an exercised document.
- Admin JS does not format a document date from `created_at` or `updated_at`. It prints the date `present()` returns.
- A test fails if a known issued-document endpoint returns the live catalog name after the catalog name changes.
- New document types get a card column and a `present()` branch in the same change that adds them.

## Testing

- Backdated customer order: order list, Past tab, and party ledger show the typed date. It is not under Today.
- Backdated customer bill and vendor bill: same, including a debit note created with the bill.
- Rename product, change photo, add-on, and alternative: open order shows the new values; an issued bill and its PDF keep the old card.
- Rename customer, vendor, freight agent, bill series, city, route, payment mode: master screen shows the new value; an issued bill keeps the old card.
- Rename a category lookup: live products that used it update; an issued bill keeps the old category.
- Cancel a bill: order screen and party ledger both say cancelled. Void hides it everywhere except the recycle bin.
- Edit a saved bill: all screens and a reprinted PDF show the edited card, not today's catalog.
- Sales-by-item after a rename: one group for that `catalog_product_id`. Lines keep old labels.
- Search: open order found by the new name; issued bill found by the old name and by the current product.
- Portal order history uses the card, including the photo. Shop catalog stays live.
- Master edit does not leave a stale open order in the cached list.

## Out of scope for the guarantee

Backup zips are raw tables, not a screen. The calculator does not display documents. Login does not display documents.
