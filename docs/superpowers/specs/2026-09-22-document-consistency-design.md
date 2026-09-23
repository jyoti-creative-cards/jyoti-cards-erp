# Document consistency

Date: 2026-09-22
Status: approved by user 2026-09-22
Scope: JC ERP only (`JC/backend/`, `JC/web/admin/`, customer portal routes in `JC/backend/app/routers/shop.py`). One system-wide rule. Not a shortcut on each screen.

This spec is the single implementation-plan input.

## Problem

The same fact is read from different places.

A backdated order stores the date the user typed on `placed_at`. The party ledger shows that date. The New / Today / Past screens show `updated_at` or `created_at`, which is the moment someone clicked save, so the order looks like today.

A product rename updates `CatalogProduct`. Stock and the catalog show the new name. Orders, bills, debit notes, and ledgers show `our_product_id` copied onto the line when it was created. Photos, add-ons, and alternatives are worse: several PDFs and the portal order history call the live catalog (`prod.image_keys`, `addon_snapshots_for_product`) even after the document was issued.

Cancelling a bill sets `cancelled_at`. The order screen shows cancelled. The party ledger ignores that flag and still lists the bill as open. A void (`deleted_at`) is hidden. Cancel is not.

The same split exists for customers, vendors, bill series, freight agents, cities, routes, payment modes, and category / series / unit lookups. Master screens are live. Issued documents sometimes join the live row and sometimes use a stale copy.

## Goal

One document has one date and one status on every screen. Names and prices follow the live master, except on a locked document, which keeps the card copied when it was locked.

- Open orders, goods receipts, debit notes, expenses, freight, payments, and returns follow the live masters. A correction of that row shows everywhere.
- A saved customer bill, a saved vendor bill, and a closed order do not change when a master changes.
- Cancel, void, and an edit of a row show up everywhere that row appears. Editing a receipt does not rewrite a vendor bill already locked.
- Search, reports, PDFs, share, the recycle bin, and the customer portal use the same facts as the admin screen.
- Nothing bypasses `present()`.

## Non-goals

- Rewriting stock on hand, outstanding balances, credit limit, freight balance due, or the shop catalog. Those are live on purpose.
- Changing activity-log time or price-history time. Those record when an edit happened.
- Recovering a photo, add-on, or party detail that was never stored and was already overwritten before this ships. Locked documents already saved are frozen as well as the stored row and entity history allow. After that they do not move. Unlocked documents keep reading the live master.
- A second history product. `EntityHistory` stays the log of master edits. The document card is what that document said.

## Locked versus everything else

**Locked.** Later changes to masters do not flow into these. The card copied at lock time is what every screen shows for that document.

- A saved customer bill, including one that is not closed yet.
- A saved vendor bill.
- A closed customer order.
- A closed customer bill.
- A closed vendor order.

The quantity on a saved bill is locked with that bill. Quantity still open on the order stays live.

At lock, the system copies the live masters onto that document once. A later rename, price, photo, add-on, alternative, category, or party edit does not touch it.

**Not locked.** These stay consistent with the current masters, and a correction typed on the row shows on every screen that shows that row.

- Open customer orders and open vendor orders.
- Vendor goods received (the receipt), including after a vendor bill exists.
- Debit notes.
- Expenses.
- Freight charges and freight settlements.
- Customer and vendor payments.
- Customer returns.
- Names, prices, photos, add-ons, and alternatives on anything in this list.

`present()` reads the card for a locked document and the live masters for everything else. Dates and status still come from the document row in both cases, so Today / Past and cancelled / voided do not drift.

Editing a receipt does not rewrite a vendor bill already locked from it. The receipt screens show the corrected item. The vendor bill keeps the card it had when it was saved. Same for a debit note or a payment: editing that row updates every view of that row, and does not rewrite a locked bill.

## The card

One JSON snapshot on each locked document. `present()` is the only reader. Admin JS renders `present()` fields. It does not format `created_at`, `updated_at`, or a copied item code on its own. Unlocked documents do not use this snapshot for display.

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

Category, series, and unit live in `CatalogLookup`. A product stores the text. Renaming a lookup updates live products and every unlocked document. Locked bills and closed orders keep the old word.

`EntityHistory` already tracks customer, vendor, catalog product, and add-on product. Extend it to freight agent, bill series, city, route, payment mode, and catalog lookup, so master edits stay auditable. The document card is still what an issued document displays. Do not display an issued document by looking up "whatever history says now".

## What uses the card

`present()` covers every screen. PDFs and share use it too.

The card, not the live master:

- Saved customer bill, bill PDF, copies
- Saved vendor bill and its PDF
- Closed customer order and its PDF
- Closed vendor order and its PDF
- Portal history and PDF for those locked documents
- Report and daybook lines that cite a locked bill or closed order

Live masters, and a correction shows everywhere:

- Open orders
- Vendor goods receipts and the receipt PDF
- Debit notes
- Returns
- Payments, on both ledgers and statements
- Expenses
- Freight charges, settlements, and their PDFs
- Report lines that cite those rows

Portal product search and the shop catalog stay live.

## Reports and search

Amounts come from the document (`grand_total`, `line_total`, ledger `amount`), not from today's catalog price.

A locked line shows the label on that document's card. Any other line shows the current master name.

Totals group by stable id: `catalog_product_id`, `customer_id`, `vendor_id`, `freight_agent_id`. A rename must not split one product or one party into two report rows. Lines under a locked bill keep the saved label. Lines for receipts, debit notes, expenses, freight, and payments use the current name.

Search uses the same rule. An open order, a receipt, a debit note, an expense, or a payment matches the current name. A locked bill or closed order matches the name on its card, and still matches the current name of the same id so staff can find it after a rename.

## Correcting a row

Staff can fix a wrong goods receipt, debit note, return, expense, payment, or freight entry. Where the app has no edit action today (expense, payment), add one.

The save rewrites that same row. It does not insert a second expense or a second payment beside the wrong one. Every screen, ledger, report, and PDF of that row shows the correction. A receipt edit updates stock and every receipt screen. It does not change a vendor bill that is already locked.

A wrong payment is an edit of that payment's amount, date, mode, and reference. Outstanding follows the corrected amount. Reverse and void stay for "this should not exist", not for a typo.

A locked customer bill, vendor bill, or closed order is not rewritten by those corrections or by later master edits. Correcting a locked bill itself, when staff edit that bill, rewrites only that bill's card and every view of that bill.

## Cache

A master edit invalidates open-document caches immediately: catalog, stock, shop products, open customer orders, open vendor orders.

An exercised document's cache changes only when that document is saved, cancelled, voided, or restored.

The admin frontend cache must drop those prefixes on the same mutations. A five-minute stale open order is a bug.

## Backfill

For locked documents already saved:

1. Build the card from columns already on the row (item code, prices, quantities, bill number, charges, party id, applied billing percent, payment mode string, `created_by_name`).
2. Where `EntityHistory` has a snapshot valid at the document's business date, use it for customer, vendor, product, and add-on fields that the row does not already store.
3. Where nothing was stored (a photo, an add-on list, an agent display name), copy the current live value once into the card.

Step 3 stops future drift. It does not restore a value that was overwritten before history existed. Do not leave those fields as live joins.

## Enforcement

- Routers, PDFs, portal, reports, and search call `present()`. They do not assemble display names, photos, or dates themselves.
- Admin JS does not format a document date from `created_at` or `updated_at`. It prints the date `present()` returns.
- A test fails if a locked bill still shows the live catalog name after the catalog name changes.
- A test fails if a goods receipt, debit note, expense, freight charge, or payment still shows the old name after the master name changes.
- New locked document types get a card column and a `present()` branch in the same change that adds them.

## Testing

- Backdated customer order: order list, Past tab, and party ledger show the typed date. It is not under Today.
- Backdated customer bill and vendor bill: same, including a debit note created with the bill.
- Rename product, change photo, add-on, and alternative: open orders, receipts, debit notes, expenses, and freight show the new values. A saved customer bill, a saved vendor bill, and a closed order keep the old card.
- Rename customer, vendor, freight agent, bill series, city, route, payment mode: payments, expenses, and freight show the new value. A locked bill keeps the old card.
- Rename a category lookup: live products and unlocked documents update. A locked bill keeps the old category.
- Cancel a bill: order screen and party ledger both say cancelled. Void hides it everywhere except the recycle bin.
- Edit a receipt item number: stock and every receipt screen show the new item. A vendor bill already saved from that receipt does not change.
- Edit a debit note, expense, payment, or freight entry: every screen shows the corrected row, not a second copy. A payment edit changes that payment's outstanding effect.
- Sales-by-item after a rename: one group for that `catalog_product_id`. Locked bill lines keep the saved label. Other lines show the current name.
- Search: open order and receipt found by the new name. A locked bill found by the old name and by the current product.
- Portal history of a locked bill uses the card, including the photo. An open portal order and the shop catalog stay live.
- Master edit does not leave a stale open order in the cached list.

## Out of scope for the guarantee

Backup zips are raw tables, not a screen. The calculator does not display documents. Login does not display documents.
