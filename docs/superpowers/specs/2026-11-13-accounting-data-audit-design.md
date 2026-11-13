# Live accounting data audit

A one-time, read-only check of the live JC books. The result is a findings report in the chat. No application code is added, and no row is inserted, updated, or deleted.

## Goal

Say whether the books are clean. A clean verdict means every check ran to completion and there are zero breaks. Review items stay listed and do not, by themselves, make the books unclean.

The audit covers all history, plus everything that is still open.

## Books

The database is the live Postgres database configured in `JC/backend/.env`. The audit uses the existing application session so headline dues can be read through `dues_snapshot` and `assert_dues_consistent`.

The session is `READ ONLY`. If that cannot be set, the audit stops and reports nothing as clean. The transaction is rolled back at the end.

Soft-deleted rows stay out of every live sum. Commission ledger rows and freight ledger rows have no `deleted_at`. A cancelled customer bill on a commission agent is stored as a bill row of ₹0.00. A cancelled freight charge is deleted.

Amounts are compared after quantizing to paise. A gap under ₹0.01 is ignored.

A rule that cannot be confirmed from the posting code is a review. It is never a break.

## What a finding contains

- Level: break or review
- Area: customer sales, vendor purchases, freight, expenses, or open items
- Party name, or the id when the name is missing
- Document number and row id
- Expected amount, actual amount, and the difference
- One sentence naming the rule that failed

Each finding is read a second time before it is written.

## Verdict and report order

1. Verdict, with the count of breaks, reviews, and checks that did not run.
2. Headline money.
3. Every break, largest difference first.
4. Every review.
5. Open lists.

The report also states how many bills, receipts, payments, returns, expenses, and ledger rows each check saw.

The findings stay in the chat. No audit script is committed.

## Headline money

These figures are labels, not a profit calculation. Cash collected is not sales. Vendor payments are not purchase cost. The app's monthly cash "profit" is not used.

- Billed sales: `grand_total` of customer bills with `cancelled_at` and `deleted_at` both null.
- Credit notes: the absolute value of live credit-note rows on customer receivables and commission agents.
- Cash collected: the absolute value of the net of live `payment` and `payment_reversal` rows, shown separately for customer receivables and for commission agents.
- Vendor bills: `receipt_bill_amount` for live receipts whose `bill_status` is `billed`. That helper uses `actual_ap_amount` when it is set, otherwise `total_billed_amount`, otherwise the legacy line total plus additional charges. `actual_ap_amount` already includes extra cash.
- Vendor payments: the absolute value of the net of live payable `payment` and `payment_reversal` rows.
- Cash expenses: expenses where `is_cash` is true or null.
- Non-cash expenses: expenses where `is_cash` is false.
- Manual losses: the sum of `jc_manual_losses`.
- Open customers, open vendors, and open freight: the positive dues from `dues_snapshot`.
- Open commission agents: the sum of positive `agent_outstanding` values.
- Credit balances: the absolute value of negative party balances, shown on their own lines for customers, commission agents, vendors, and freight. A negative balance is an open credit. It is not a break.

Customer, vendor, and freight dues are computed twice: a live SQL sum of positive party balances, and `dues_snapshot`. The two figures must match. Commission dues are computed through `agent_outstanding` and are not added to customer receivables. The home-screen dues total leaves agent books out, and the audit keeps them apart.

## Customer sales

A live bill (`deleted_at` null, `cancelled_at` null) with `grand_total` greater than zero sits on one ledger:

- `commission_agent_id` set: one commission bill row for that agent, amount equal to `grand_total`, and no live customer-receivable bill row.
- `commission_agent_id` null: one live customer-receivable bill row, amount equal to `grand_total`, and no commission bill row.

A live bill on both ledgers is a break. A live bill with `grand_total` greater than zero on neither ledger is a break. A live bill whose ledger amount differs from `grand_total` is a break. A live bill with `grand_total` of ₹0.00 and no ledger row passes.

A cancelled bill may keep a bill row of ₹0.00. Any other live bill amount on that cancelled bill is a break. A missing row passes, because the amount due is zero.

A voided bill (`deleted_at` set) must not have a live customer-receivable bill row. A commission bill row for that voided bill must be ₹0.00 or absent. Commission rows cannot be soft-deleted.

Stored `grand_total` is the document amount. The audit does not rebuild GST.

### Returns

A live return with `credit_amount` of zero posts nothing and passes.

A live return with a positive `credit_amount` must have live credit-note rows whose signed amounts sum to the negative of `credit_amount`. A return of one party's own bills has one customer-receivable credit note. A return of one agent's bills has one commission credit note. A return that spans a party and one or more agents has one row per ledger, split by the posting code. Any other count or total is a break.

A voided return must not have a live customer-receivable credit note. A commission credit for that voided return must be ₹0.00 or absent.

### Openings, signs, and duplicates

More than one live opening balance for the same customer or vendor is a break. Deleted opening rows are ignored. Commission and freight ledger rows have no `deleted_at`, so every opening row on those ledgers counts. The audit does not use the opening getters that skip the `deleted_at` filter.

On live customer, vendor, and commission rows:

- A `bill` amount is positive. A ₹0.00 bill row passes when that bill is cancelled or its `grand_total` is ₹0.00.
- A `payment` amount is negative.
- A `payment_reversal` amount is positive.
- A `credit_note` amount is negative.
- An `adjustment` may be either sign.
- A payable `debit_note` amount equals `debit_note_payable_effect`: item notes reduce the payable, every other note type increases it.

An unknown `entry_type` is a break.

A repeated customer `bill_number` among bills with `deleted_at` null is a break, including a number shared with a cancelled bill. A repeated vendor `bill_number` on live billed receipts for the same vendor is a break. The same vendor bill number on two different vendors passes.

A possible duplicate payment is the same party, the same absolute amount, and the same day. The day is `value_date`, or the IST date of `created_at` when `value_date` is null. Reversed rows are left out. A shared non-empty `payment_ref` makes it a break. A blank reference stays a review.

An orphan is a break: a live bill, credit-note, or debit-note ledger row with a non-zero amount whose document is missing or voided. A ₹0.00 commission row left on a voided bill passes.

## Vendor purchases

For a live receipt with `bill_status` `billed`, the sum of live payable rows of type `bill` and `adjustment` equals `receipt_bill_amount`. Extra-cash bill rows and later adjustments are inside that sum. Debit notes and payments are outside it.

A live receipt with `bill_status` `pending_bill` and a non-zero live bill-and-adjustment net is a break. That receipt is listed under breaks and left off the open list.

A voided receipt must not have a live payable bill, adjustment, or debit-note row.

A live debit note has one live payable `debit_note` row for `debit_note_payable_effect`. A voided debit note must not have a live payable row.

A receipt with `closed_at` set, a status other than `billed`, and no live bill net is a review.

## Freight

`balance_due` on each freight agent equals the sum of that agent's freight ledger.

A picked bus bill (`freight_picked_at` set, mode `bus`, agent set, `freight_charges` greater than zero) has one freight charge for that amount. A missing or different charge is a break.

A freight charge that exists must point at a live, non-cancelled bill in mode `bus` or `transport`, for the same agent, with the same amount. A charge left on a cancelled or voided bill is a break, because cancel deletes the charge.

An unpicked bill with no charge passes, and it is not an open payable. An unpicked bill with one matching charge passes, because saving freight posts the charge before pickup. A picked transport bill with no charge passes, because pickup posts a charge only for bus. Self-pickup, a missing agent, or a zero freight amount has no charge.

A freight settlement or advance whose `expense_id` points at a missing expense is a break. An expense does not need a freight row.

## Expenses and losses

A negative expense amount is a break. Cash and non-cash expenses stay in separate headline totals. Manual losses are listed and are not mixed into payables. A manual loss of zero or less is a review.

## Open lists

These lists are complete. They are not breaks.

- Every customer, commission agent, vendor, and freight agent whose live balance is not zero.
- Every customer order line with status `active`, on a placement that is not deleted and not cancelled, where `quantity` is greater than `quantity_billed`.
- Every vendor receipt with `bill_status` `pending_bill`, `deleted_at` null, and `closed_at` null.
- Every vendor order line with `quantity_remaining` greater than zero on an order that is still open.

Payments are not matched back onto single bills. The books do not store that link.

## Left out

Stock counts, sticker jobs, and rebuilding a bill's tax from its lines. Cash collected is not treated as profit.

## How the audit checks itself

A check that throws is marked not run, and the verdict stays unclean. The rest of the checks still run.

Headline customer, vendor, and freight dues must agree between the SQL sum and `dues_snapshot`. A mismatch is a break.

The second read of a finding must still show the same party, document, and amounts. A finding that changed is dropped. The other findings from that check stay. The check is marked not fully run, so the verdict stays unclean.
