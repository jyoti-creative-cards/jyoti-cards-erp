# Multiple expenses Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Staff record many expenses on one form, check them, and save them together on the date they picked, then filter and download that list from the expense report.

**Architecture:** One new batch save writes normal `Expense` rows in a single transaction. The day book already reads `expense_date`, so no new ledger table. A new expense-lines report and PDF apply date, subcategory, and paid-from filters with no 500-row cap. The admin form follows the vendor-payment screen: it stays on the Money page, Review does not save, Confirm posts once.

**Tech Stack:** FastAPI, SQLAlchemy, pytest, sqlite memory, reportlab, pypdf, vanilla admin JS in `JC/web/admin/js/finance.js` and `JC/web/admin/js/reports.js`.

## Global Constraints

- Work only in `JC/backend/` and `JC/web/admin/`. Do not edit root `backend/`.
- The name is the expense title and is stored in `Expense.description`. The optional note is stored in `Expense.reference`. A blank note is stored as null.
- The date on the form is `expense_date` on every row. Do not substitute today at save time.
- Paid from is an existing `ExpenseSource` id. Subcategory is an existing `ExpenseSubhead` id. Category text is the existing `head / sub` string from `resolve_expense_category`, lowercased.
- Amount must be greater than zero. Name is required on every kept row. Paid from and subcategory are required.
- One bad row saves nothing. Confirm posts once. Review does not post.
- A new row copies paid from and subcategory from the row above it. Changing an earlier row does not change the other rows. Changing the last row is what the next new row copies.
- The expense report returns every matching row. Do not apply a 500-row limit.
- Add expense, vendor payment, and customer payment stay as they are.
- Do not read or copy `JC/backend/.env`. Do not connect to a hosted database. Run tests with `DATABASE_URL=sqlite:///:memory:`.
- Edit `JC/web/admin/js/finance.js` and `JC/web/admin/js/reports.js`. Those are the files `index.html` loads. If the same button markup also exists under `JC/web/admin/js/finance/`, change it there too. Do not run `tools/stitch_screen.py --write`.
- Bump only the cache query you change: `js/finance.js?v=ui138` becomes `ui139`, `js/reports.js?v=ui131` becomes `ui132`.

---

### Task 1: Batch save

**Files:**
- Create: `JC/backend/tests/test_expense_batch.py`
- Modify: `JC/backend/app/routers/expenses.py`

**Interfaces:**
- Consumes: `resolve_expense_category`, `_expense_source`, `Expense`, `ExpenseHead`, `ExpenseSubhead`, `ExpenseSource`
- Produces: `ExpenseBatchIn`, `create_expenses_batch(db, body, actor_name) -> list[Expense]`, `POST /api/v1/expenses/batch` returning `list[ExpensePublic]`

- [ ] **Step 1: Write the failing test**

```python
"""Many expenses save together on the chosen date, or not at all."""
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.expense import Expense, ExpenseHead, ExpenseSource, ExpenseSubhead
from app.routers.expenses import ExpenseBatchIn, ExpenseBatchLine, create_expenses_batch
from app.services.reports.daybook import daybook


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _seed(db):
    source = ExpenseSource(name="Cash Register")
    head = ExpenseHead(name="Kitchen")
    db.add_all([source, head])
    db.flush()
    sub = ExpenseSubhead(head_id=head.id, name="Tea")
    db.add(sub)
    db.flush()
    return source, sub


def test_batch_stores_the_chosen_date_and_the_day_book_uses_it():
    db = _db()
    source, sub = _seed(db)
    rows = create_expenses_batch(db, ExpenseBatchIn(
        expense_date=date(2026, 1, 15),
        lines=[
            ExpenseBatchLine(source_id=source.id, subhead_id=sub.id, description="Milk", amount=Decimal("40"), reference="morning"),
            ExpenseBatchLine(source_id=source.id, subhead_id=sub.id, description="Sugar", amount=Decimal("10")),
        ],
    ), "Anita")
    db.commit()
    assert [r.expense_date for r in rows] == [date(2026, 1, 15), date(2026, 1, 15)]
    assert rows[0].description == "Milk"
    assert rows[0].reference == "morning"
    assert rows[0].category == "kitchen / tea"
    assert rows[0].source_id == source.id
    assert rows[1].reference is None
    book = daybook(db, from_date=date(2026, 1, 15), to_date=date(2026, 1, 15))
    labels = [r["label"] for r in book["entries"] if r["kind"] == "expense"]
    assert set(labels) == {"Milk", "Sugar"}
    assert all(r["at"] == "2026-01-15" for r in book["entries"] if r["kind"] == "expense")
    db.close()


def test_one_bad_row_saves_nothing():
    db = _db()
    source, sub = _seed(db)
    with pytest.raises(HTTPException):
        create_expenses_batch(db, ExpenseBatchIn(
            expense_date=date(2026, 1, 15),
            lines=[
                ExpenseBatchLine(source_id=source.id, subhead_id=sub.id, description="Milk", amount=Decimal("40")),
                ExpenseBatchLine(source_id=source.id, subhead_id=sub.id, description="Sugar", amount=Decimal("0")),
            ],
        ), "Anita")
    db.rollback()
    assert db.query(Expense).count() == 0
    db.close()
```

- [ ] **Step 2: Run the test and see it fail**

Run from `JC/backend`: `DATABASE_URL=sqlite:///:memory: python3 -m pytest tests/test_expense_batch.py -q`

Expected: FAIL because `ExpenseBatchIn` is not defined.

- [ ] **Step 3: Implement the batch save**

Add these models and the function in `JC/backend/app/routers/expenses.py`. The function does not commit. The route commits once.

```python
class ExpenseBatchLine(BaseModel):
    source_id: int
    subhead_id: int
    description: str
    amount: Decimal
    reference: Optional[str] = None


class ExpenseBatchIn(BaseModel):
    expense_date: date
    lines: List[ExpenseBatchLine]


def create_expenses_batch(db: Session, body: ExpenseBatchIn, actor_name: str) -> list[Expense]:
    if not body.lines:
        raise HTTPException(400, "Add an expense")
    rows: list[Expense] = []
    for line in body.lines:
        name = " ".join((line.description or "").split())
        if not name:
            raise HTTPException(400, "Enter a name")
        if line.amount is None or line.amount <= 0:
            raise HTTPException(400, "Enter a valid amount")
        category = resolve_expense_category(db, ExpenseIn(
            expense_date=body.expense_date,
            amount=line.amount,
            subhead_id=line.subhead_id,
            description=name,
            source_id=line.source_id,
        ))
        source = _expense_source(db, line.source_id, required=True)
        row = Expense(
            expense_date=body.expense_date,
            category=category,
            description=name,
            amount=line.amount,
            reference=(" ".join((line.reference or "").split()) or None),
            source_id=source.id,
            created_by_name=actor_name,
        )
        db.add(row)
        rows.append(row)
    db.flush()
    return rows
```

Add the route next to `create_expense`. It uses `require_permission("finance.write")`. It calls `create_expenses_batch`, logs one activity per row with `log_from_auth` after the flush, commits once, and returns `[ExpensePublic.from_row(r) for r in rows]`. Do not commit inside the helper. Do not change `POST /expenses`.

- [ ] **Step 4: Run the test and see it pass**

Run: `DATABASE_URL=sqlite:///:memory: python3 -m pytest tests/test_expense_batch.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add JC/backend/tests/test_expense_batch.py JC/backend/app/routers/expenses.py
git commit -m "$(cat <<'EOF'
Save a list of expenses together on the date the cashier picked.

EOF
)"
```

### Task 2: Expense lines report and PDF

**Files:**
- Create: `JC/backend/tests/test_expense_lines_report.py`
- Modify: `JC/backend/app/services/reports/gst_purchase_register.py`
- Modify: `JC/backend/app/services/reports/extended.py`
- Modify: `JC/backend/app/routers/reports.py`
- Modify: `JC/backend/app/services/reports/pdfs.py`
- Modify: `JC/backend/app/routers/share.py`

**Interfaces:**
- Consumes: `Expense`, `ExpenseSource`, `_fmt` already used in `gst_purchase_register.py`
- Produces: `expense_lines(db, from_date, to_date, category, source_id) -> dict` with keys `items` and `total`. Each item has `date`, `category`, `source_name`, `description`, `reference`, `amount`. `render_expense_lines_pdf(...) -> bytes`. `GET /api/v1/reports/expense-lines`. `GET /api/v1/share/expense-lines/pdf`.

- [ ] **Step 1: Write the failing test**

```python
"""The expense report filters by date, subcategory, and paid from, and the PDF is that list."""
from datetime import date
from decimal import Decimal
from io import BytesIO

from pypdf import PdfReader
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.expense import Expense, ExpenseSource
from app.services.reports.extended import expense_lines
from app.services.reports.pdfs import render_expense_lines_pdf


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_filters_return_every_match_and_the_pdf_is_that_list():
    db = _db()
    cash = ExpenseSource(name="Cash Register")
    bank = ExpenseSource(name="ICICI")
    db.add_all([cash, bank])
    db.flush()
    db.add_all([
        Expense(expense_date=date(2026, 1, 15), category="kitchen / tea", description="Milk", reference="morning", amount=Decimal("40"), source_id=cash.id, created_by_name="Anita"),
        Expense(expense_date=date(2026, 1, 15), category="kitchen / tea", description="Sugar", amount=Decimal("10"), source_id=bank.id, created_by_name="Anita"),
        Expense(expense_date=date(2026, 2, 1), category="kitchen / tea", description="Biscuits", amount=Decimal("20"), source_id=cash.id, created_by_name="Anita"),
    ])
    db.commit()
    data = expense_lines(db, date(2026, 1, 1), date(2026, 1, 31), "kitchen / tea", cash.id)
    assert [row["description"] for row in data["items"]] == ["Milk"]
    assert data["items"][0]["date"] == "2026-01-15"
    assert data["items"][0]["source_name"] == "Cash Register"
    assert data["items"][0]["reference"] == "morning"
    assert data["total"] == "40.00"
    pdf = render_expense_lines_pdf(db, date(2026, 1, 1), date(2026, 1, 31), "kitchen / tea", cash.id)
    text = "\n".join((page.extract_text() or "") for page in PdfReader(BytesIO(pdf)).pages)
    assert "Milk" in text
    assert "Sugar" not in text
    assert "2026-01-15" in text
    db.close()
```

- [ ] **Step 2: Run the test and see it fail**

Run: `DATABASE_URL=sqlite:///:memory: python3 -m pytest tests/test_expense_lines_report.py -q`

Expected: FAIL because `expense_lines` is not exported.

- [ ] **Step 3: Implement the report and the PDF**

Add `expense_lines` in `gst_purchase_register.py` beside `expense_by_category`. Filter `expense_date` when from or to is set. Filter `func.lower(Expense.category) == category.strip().lower()` when category is non-empty. Filter `Expense.source_id` when source_id is set. Order by `expense_date` ascending, then `id` ascending. Do not call `.limit()`. Look up source names with one query. A missing source name is an empty string. `reference` is null when the note is empty. `total` is the sum of the returned amounts, formatted with the existing `_fmt`.

Export `expense_lines` from `JC/backend/app/services/reports/extended.py` the same way `expense_by_category` is exported.

Add `GET /expense-lines` on the reports router, `require_admin`, query params `from_date`, `to_date`, `category` default `""`, `source_id` default `None`. Return `expense_lines(...)`.

Add `render_expense_lines_pdf` in `pdfs.py` using the same `_doc`, `Paragraph`, `Table`, and `TableStyle` pattern as `render_sales_pdf`. Columns: Date, Subcategory, Paid from, Name, Note, Amount. A blank note prints as a dash. The last row is the total. The title includes the dates when they are set.

Add `GET /expense-lines/pdf` on the share router, `require_admin`, the same query params, returning `_pdf_response` with a filename `expenses_<from>_<to>.pdf` when both dates are set, otherwise `expenses.pdf`.

- [ ] **Step 4: Run the test and see it pass**

Run: `DATABASE_URL=sqlite:///:memory: python3 -m pytest tests/test_expense_lines_report.py tests/test_expense_batch.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add JC/backend/tests/test_expense_lines_report.py JC/backend/app/services/reports/gst_purchase_register.py JC/backend/app/services/reports/extended.py JC/backend/app/routers/reports.py JC/backend/app/services/reports/pdfs.py JC/backend/app/routers/share.py
git commit -m "$(cat <<'EOF'
Filter the expense report by date, subcategory, and paid from, and save that list as a PDF.

EOF
)"
```

### Task 3: Multiple expenses form

**Files:**
- Modify: `JC/web/admin/js/finance.js`
- Modify: `JC/web/admin/js/finance/01-init.js` only if it still contains the Quick entry buttons
- Modify: `JC/web/admin/index.html` (`js/finance.js?v=ui138` to `ui139` only)

**Interfaces:**
- Consumes: `POST /expenses/batch` with `{ expense_date, lines: [{ source_id, subhead_id, description, amount, reference? }] }`. `GET /expenses/sources`. `GET /expenses/heads` (each head has `subheads` with `id` and `name`).
- Produces: `Finance.quickMultipleExpenses`, `Finance.reviewMultipleExpenses`, `Finance.backMultipleExpenses`, `Finance.confirmMultipleExpenses`, `Finance.addExpenseRow`, `Finance.changeExpenseRow`, `Finance.removeExpenseRow`. Export them on the Finance object next to `quickAddExpense`.

- [ ] **Step 1: Add the button**

In both Quick entry places in `finance.js` (the Money-page card around the Add expense button, and `openQuickEntry`), add a button after `+ Add expense`:

`Multiple expenses` calls `App.closeDetail();Finance.quickMultipleExpenses()` on the popup, and `Finance.quickMultipleExpenses()` on the page card.

Leave Record vendor payment, Record customer payment, and `+ Add expense` calling the same functions they call now.

- [ ] **Step 2: Draw the form on the Money screen**

Follow the vendor payment guard. `showHub` must not wipe this form. `renderNeedsAction` must return early while the form or the check is on screen. `quickMultipleExpenses` closes the popup, shows Money, and paints the form into `#finance-needs`.

The form has one date input, defaulting to today in `Asia/Kolkata`. Then one row. Fields: paid from (`select` of `/expenses/sources`), subcategory (`select` of every sub-head, label `sub — head`), name, amount, note. Buttons on the row: Change and Remove. The only footer action is Review.

Load sources and heads before painting. If either request fails, show the error in `#finance-needs` and do not open the check.

Enter in the amount or the note of the last row adds a row after it. Enter on an earlier row focuses the next row's name field. A new row copies the paid-from value and the subcategory value from the row above it. Name, amount, and note start empty.

Change replaces that row's paid-from and subcategory selects with enabled selects if they were locked, or the selects stay editable. Other rows do not change. The next row added afterwards copies the row above it.

Remove deletes that row from the form. If it was the only row, leave one empty row.

- [ ] **Step 3: Review, Back, Confirm**

Review reads the rows from the form. Drop a row whose name and amount are both empty. If a remaining row lacks paid from, subcategory, name, or an amount greater than zero, toast the missing piece and stay on the form. Do not post.

The check replaces the form and shows the date once, then each kept row (paid from name, subcategory label, name, amount, note or a dash), then the total. Back restores the same rows, including changed selects. Confirm posts once to `/expenses/batch`. Omit `reference` when the note is blank. On failure, stay on the check and show the error. Nothing in the form is posted before this.

On success, replace the screen with how many expenses, the total, and the date, plus a Done button. Done clears the form and returns to the Money hub. Done does not post.

- [ ] **Step 4: Check the script loads**

Bump `index.html` `js/finance.js?v=ui138` to `ui139` and no other cache key.

- [ ] **Step 5: Commit**

```bash
git add JC/web/admin/js/finance.js JC/web/admin/index.html
git commit -m "$(cat <<'EOF'
Let the cashier enter many expenses on one form and check them before saving.

EOF
)"
```

If `01-init.js` was changed, add it in the same commit.

### Task 4: Expense report screen

**Files:**
- Modify: `JC/web/admin/js/reports.js`
- Modify: `JC/web/admin/index.html` (`js/reports.js?v=ui131` to `ui132` only)

**Interfaces:**
- Consumes: `GET /reports/expense-lines?from_date&to_date&category&source_id` and `GET /share/expense-lines/pdf` with the same query. `GET /expenses/heads` and `GET /expenses/sources`.
- Produces: Expense by category shows the line list for the current date bar plus the two new dropdowns, and PDF uses `DocShare.openPdf`.

- [ ] **Step 1: Filters**

On the Expense by category screen, keep the existing date bar. Add a subcategory select (first option All, then each sub-head labelled `sub — head`, value the category string such as `kitchen / tea`) and a paid-from select (first option All, then each source, value the source id). Changing either reloads the report.

- [ ] **Step 2: Lines**

Replace the category-total table on this screen with one row per expense from `/reports/expense-lines`, using the date range already in `rangeQs()` plus `category` when not All and `source_id` when not All. Columns: date, subcategory, paid from, name, note, amount. An empty note is a dash. Show the total under the table. Do not stop at 500 rows.

- [ ] **Step 3: PDF**

Add a PDF button next to Print and Excel for this screen only. It calls `DocShare.openPdf` on `/share/expense-lines/pdf` with the same query string, `print: false`, filename `expenses_<from>_<to>.pdf` when both dates exist, otherwise `expenses.pdf`. Print and Excel keep using the rows on screen.

- [ ] **Step 4: Cache**

Bump `index.html` `js/reports.js?v=ui131` to `ui132` only.

- [ ] **Step 5: Commit**

```bash
git add JC/web/admin/js/reports.js JC/web/admin/index.html
git commit -m "$(cat <<'EOF'
Filter the expense report and save the same list as a PDF.

EOF
)"
```
