# Multiple expenses

Alt+Q opens Quick entry. Add expense stays the one-expense box. Multiple expenses is a new button beside it. It closes the popup and opens one form on the Money screen, then a check, then one save. Vendor payment and customer payment stay as they are.

## Who and where

Staff who can already record an expense. The same permission as Add expense. The button is on the Alt+Q popup and on the Quick entry page. Both close the popup and show the form on the Money screen.

## Form

The form sits on the screen. It does not use a browser prompt for the fields.

The date is at the top. It starts as today in India time. The date that is selected is the date stored on every row. Confirm does not replace it with the day the list is saved.

The first row has five fields:

1. Paid from. Required. The accounts already created for expenses.
2. Subcategory. Required. A sub-head under a head, with the same labels as Add expense. A head with no sub-head is not offered.
3. Name. Required. This is the expense title. It is stored as the expense description.
4. Amount. Required. A number greater than zero.
5. Note. Optional. Stored in the existing reference field. A blank note is stored as empty.

Enter in the amount or the note of the last row adds the next row. Enter on an earlier row moves to the next row already on the form. A new row copies paid from and subcategory from the row above it. Name, amount, and note start empty.

Change on a row opens paid from and subcategory for that row only. Other rows stay as they were. A new row copies the row above it, so a change on the last row is what the next row picks up. A change on an earlier row does not change the next new row.

Remove drops that row. A removed row is not saved.

The last row counts when Review is pressed, even if Enter was not pressed. A row with no name and no amount is left out. A row that has some required fields and not others stays on the form, and the screen says what is missing. Nothing is posted.

Review is the only way forward. It does not save.

If the paid-from list or the subcategory list fails to load, the screen shows the error and does not open the check.

## Check

The check shows the date once, then each kept row: paid from, subcategory, name, amount, and note. An empty note is a dash. The total is at the bottom.

Back returns to the form with the same rows, including any paid from or subcategory that was changed.

Confirm sends the list once, to a new batch save. The body is the date plus one line per kept row: paid-from id, sub-head id, name, amount, and the note when it is not blank.

Each line is stored as a normal expense. The category is the existing head and sub-head text. The name is the description. The note is the reference. The paid-from account is the source. The date is the date from the form. The staff member who confirmed is recorded as the creator.

The lines are written together. If one line is rejected, none of them are written. The error is shown and the check stays on screen.

Add expense, and the single-expense save, stay as they are.

## After save

A short saved screen shows how many expenses were written, the total, and the date. Done closes it and returns to Money. That screen does not save again.

## Books

No new ledger. The day book and the expense book already list each expense on its expense date. These rows show on the date that was selected, not on the day they were typed.

## Expense report

Expense by category keeps the date bar: Today, 7 days, This month, All, and Custom. Two dropdowns are added. Subcategory is All or one sub-head. Paid from is All or one account. Fetch uses the dates and those two choices.

The table is one line per expense: date, subcategory, paid from, name, note, and amount. An empty note is a dash. The total is at the bottom. Every matching expense is returned. The old limit of 500 rows does not apply to this report.

Print, Excel, and PDF use the rows on screen. The PDF is saved the same way as the sales report PDF. The date on each line is the expense date.

The page that creates heads and paid-from accounts stays as it is.

## Tests

- A backdated date is the date stored on every row, and the day book lists those rows on that date.
- One bad row saves nothing.
- A new row copies paid from and subcategory from the row above it. Changing an earlier row leaves the other rows alone. Changing the last row is what the next new row copies.
- Review does not save. Back returns the same rows. Confirm sends the list once.
- The report returns every row that matches the dates, the subcategory, and the paid-from account. The PDF is that same list.

## Out of scope

Add expense, vendor payment, customer payment, and editing an expense after it is saved.
