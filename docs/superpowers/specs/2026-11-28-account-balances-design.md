# Account balances on expenses

Paid from, customer payment, and vendor payment use one account list. That list is the payment accounts already used when money comes in or a vendor is paid. The expense screen does not keep a second list.

Cash Register, ICICI, and NC Saving Account were names on that second list. They are not separate pots. An old expense saved under one of those names counts on the matching payment account.

## Who and where

Staff who can already record an expense see the balances on Add expense and on Multiple expenses. Staff who can already record a customer payment see the account balance there. Staff who can already record a vendor payment see it there.

Heads and subcategories stay as they are. A new account is added with the payment accounts, not on the expense screen.

## One balance per account

The red balance beside an account is only that account.

It adds the customer payment amount received into that account. It subtracts the vendor payment amount paid from that account. It subtracts expenses paid from that account. The balance uses those amounts. It does not add up the raw signed ledger rows.

A reversed payment is left out. A deleted payment is left out. Freight is left out. An expense that is not cash, such as a sample, does not change the account balance.

There is no opening figure from Tally. The number is only what is already saved in this app, so it will not match an old Tally cash total.

The amount still being typed is not included. Saving is allowed when the amount is larger than the balance.

If the balance cannot be loaded, the screen says so. It does not show ₹0 in place of a failed load. A real zero is shown as ₹0. Review and confirm still work. The check shows that error in place of the missing number.

## What matches an old expense

A new expense stores the payment account that was picked.

An old expense counts on a payment account when the names are the same, ignoring case and extra spaces. These old names also match:

- Cash Register counts on the payment account named Cash.
- NC Saving Account counts on the payment account named NC.
- ICICI counts on the payment account named ICICI.

If nothing matches, that old name stays visible as its own balance so the amount is not dropped.

## Each expense line

Under the subcategory, the red balance is the total already saved for that subcategory. Tea shows Tea. It does not repeat the cash balance. A sample saved under that subcategory counts here, because this number is the subcategory total, not the cash total.

A row with no account yet shows no account balance. A row with no subcategory yet shows no subcategory balance. Two rows on Cash both show the same cash balance.

The single Add expense form shows the same two red balances. Customer payment and vendor payment show only the account balance, under the account that was picked.

The check page, before confirm, shows the same red account balance and the same red subcategory balance that were on the form. Confirm still saves when the amount is larger than the balance.

The rupee text uses the same format as the other amounts on Money, in red.

## After save

The next time a form opens, the balances include the expense that was just saved. A customer payment changes only the account it was received in. A vendor payment changes only the account it was paid from.

The expense report’s paid-from filter lists these payment accounts. An old expense that matched an account is filtered under that account.

## Tests

- A customer payment increases only the account it was received in.
- An expense decreases only the account it was paid from.
- A vendor payment decreases only the account it was paid from.
- Another account’s balance does not change.
- A reversed payment is not counted. A deleted payment is not counted. Freight is not counted. A sample expense does not change the account balance.
- Cash Register counts on Cash, NC Saving Account counts on NC, and ICICI counts on ICICI.
- The subcategory balance is only the expenses saved under that subcategory.
- The amount on the form is not included until save. A larger amount than the balance still saves.
- A failed balance load shows an error and does not show ₹0.

## Out of scope

An opening balance, freight in this balance, matching the old Tally cash total, and blocking a save that is larger than the balance.
