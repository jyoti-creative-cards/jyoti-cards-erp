# Final fix report

Fixed: hub search hidden for expense-cat (screen no longer filters by search, matches PDF); slice files reverted to 0590323; #finance-needs stays visible while multiExp or vendorPay is set; note maxlength=255 and "Note is too long" 400 before any row is written.

## Command
```
cd JC/backend && DATABASE_URL='sqlite:///:memory:' python3 (wrap create_engine) -m pytest -q tests/test_expense_batch.py tests/test_expense_lines_report.py
```

## Output
```
....                                                                     [100%]
4 passed in 0.61s
```
