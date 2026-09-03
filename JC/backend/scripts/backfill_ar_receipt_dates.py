"""One-time: set AR payment value_date from Tally Receipt Register xlsx.

Amounts in the sheet are rupees / 100. This script updates DATE ONLY.
It never writes amounts.

Usage (from JC/backend):
    python3 scripts/backfill_ar_receipt_dates.py            # dry run
    python3 scripts/backfill_ar_receipt_dates.py --execute  # write dates
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import openpyxl

sys.path.insert(0, ".")

from app.db.session import SessionLocal
from app.models.accounts_receivable import ArLedgerEntry
from app.models.customer import Customer

XLSX = Path(__file__).resolve().parents[2] / "recipt with date.xlsx"
PAISE = Decimal("0.01")


def norm_name(s: str) -> str:
    t = str(s or "").strip().lower()
    t = t.replace("–", "-").replace("—", "-")
    t = re.sub(r"\([^)]*\)", " ", t)
    t = re.sub(r"\*{1,2}", " ", t)
    t = re.sub(r"\d+/?-?", " ", t)
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\b(cash|credit|new|old|due|strict|strct|limit|day)\b", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def name_tokens(s: str) -> set[str]:
    return {w for w in norm_name(s).split() if len(w) >= 3}


def names_overlap(a: str, b: str) -> bool:
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return False
    return bool(ta & tb)


def sheet_rupees(raw) -> Decimal | None:
    if raw is None or raw == "":
        return None
    return (Decimal(str(raw)) * 100).quantize(PAISE, rounding=ROUND_HALF_UP)


def as_date(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return None


def load_sheet() -> list[dict]:
    wb = openpyxl.load_workbook(XLSX, data_only=True)
    ws = wb.active
    out = []
    for i, row in enumerate(ws.iter_rows(min_row=6, values_only=True), 6):
        dt, name, vtype, vno, debit, credit = (list(row) + [None] * 6)[:6]
        if str(name or "").strip().lower() in {"", "total:"} or str(dt or "").strip().lower() == "total:":
            continue
        if str(vtype or "").strip().lower() not in {"receipt", ""}:
            continue
        d = as_date(dt)
        if not d or not name or vno in (None, ""):
            continue
        amt = sheet_rupees(credit if credit not in (None, "") else debit)
        out.append({
            "row": i,
            "date": d,
            "name": str(name).strip(),
            "vch": str(vno).strip(),
            "sheet_raw": credit if credit not in (None, "") else debit,
            "sheet_rupees": amt,
        })
    return out


def money(v) -> Decimal:
    return Decimal(str(v)).quantize(PAISE, rounding=ROUND_HALF_UP)


def pick_match(sheet: dict, cands: list) -> tuple[object | None, str]:
    """Return (entry, reason). entry is ArLedgerEntry or None."""
    if not cands:
        return None, "no_ref_match"
    if len(cands) == 1:
        return cands[0][0], "unique_ref"
    amt_hits = [c for c in cands if sheet["sheet_rupees"] is not None and money(abs(c[0].amount)) == sheet["sheet_rupees"]]
    if len(amt_hits) == 1:
        return amt_hits[0][0], "ref+amount"
    name_hits = [c for c in (amt_hits or cands) if names_overlap(sheet["name"], c[1].business_name)]
    if len(name_hits) == 1:
        return name_hits[0][0], "ref+name" if not amt_hits else "ref+amount+name"
    return None, f"ambiguous:{len(cands)}"


def main() -> None:
    execute = "--execute" in sys.argv
    if not XLSX.exists():
        print(f"STOP: xlsx missing at {XLSX}")
        sys.exit(1)
    sheet_rows = load_sheet()
    db = SessionLocal()
    try:
        pays = (
            db.query(ArLedgerEntry, Customer)
            .join(Customer, Customer.id == ArLedgerEntry.customer_id)
            .filter(
                ArLedgerEntry.entry_type == "payment",
                ArLedgerEntry.deleted_at.is_(None),
            )
            .all()
        )
        undated = [(e, c) for e, c in pays if e.value_date is None]
        by_ref: dict[str, list] = defaultdict(list)
        for e, c in undated:
            by_ref[str(e.payment_ref or "").strip()].append((e, c))

        used_ids: set[int] = set()
        dated = 0
        amount_ok = 0
        amount_mismatch = []
        unmatched = []
        ambiguous = []

        print(f"xlsx={XLSX.name} sheet_rows={len(sheet_rows)} db_payments={len(pays)} undated={len(undated)}")
        print("amount rule: app_amount should equal excel_amount * 100")

        def apply_match(s, entry, cust, reason):
            nonlocal dated, amount_ok
            used_ids.add(entry.id)
            app_amt = money(abs(entry.amount))
            expect = s["sheet_rupees"]
            amt_match = expect is not None and app_amt == expect
            if amt_match:
                amount_ok += 1
            else:
                amount_mismatch.append((s, entry, cust, app_amt, expect, reason))
            print(
                f"  date {s['date']} entry={entry.id} vch={s['vch']} "
                f"sheet={s['sheet_raw']}→₹{expect} app=₹{app_amt} "
                f"{'AMT_OK' if amt_match else 'AMT_MISMATCH'} "
                f"cust={cust.business_name!r} tally={s['name']!r} via={reason}"
            )
            if execute:
                entry.value_date = s["date"]
            dated += 1

        for s in sheet_rows:
            cands = [(e, c) for e, c in by_ref.get(s["vch"], []) if e.id not in used_ids]
            entry, reason = pick_match(s, cands)
            if entry is None:
                (ambiguous if reason.startswith("ambiguous") else unmatched).append((s, reason, cands))
                continue
            cust = next(c for e, c in cands if e.id == entry.id)
            apply_match(s, entry, cust, reason)

        still_unmatched = []
        leftover = [(e, c) for e, c in undated if e.id not in used_ids]
        for s, reason, _cands in unmatched:
            hits = [
                (e, c) for e, c in leftover
                if e.id not in used_ids
                and s["sheet_rupees"] is not None
                and money(abs(e.amount)) == s["sheet_rupees"]
                and names_overlap(s["name"], c.business_name)
            ]
            if len(hits) == 1:
                apply_match(s, hits[0][0], hits[0][1], "name+amount")
            else:
                still_unmatched.append((s, reason if not hits else f"name+amount ambiguous:{len(hits)}", hits))
        unmatched = still_unmatched
        leftover = [(e, c) for e, c in undated if e.id not in used_ids]
        print(f"\nMATCHED {dated}  leftover_undated={len(leftover)}  unmatched_sheet={len(unmatched)}  ambiguous={len(ambiguous)}")
        print(f"AMOUNT ok={amount_ok} mismatch={len(amount_mismatch)}")

        if amount_mismatch:
            print("\nAMOUNT MISMATCHES (date still applied; amounts NOT changed):")
            for s, e, c, app_amt, expect, reason in amount_mismatch:
                print(
                    f"  entry={e.id} vch={s['vch']} {c.business_name!r} "
                    f"app=₹{app_amt} expected_excel*100=₹{expect} sheet_raw={s['sheet_raw']}"
                )
        if unmatched:
            print("\nUNMATCHED SHEET ROWS:")
            for s, reason, _ in unmatched:
                print(f"  row={s['row']} vch={s['vch']} {s['name']!r} date={s['date']} sheet_raw={s['sheet_raw']} ({reason})")
        if ambiguous:
            print("\nAMBIGUOUS (no date written):")
            for s, reason, cands in ambiguous:
                print(f"  row={s['row']} vch={s['vch']} {s['name']!r} {reason}")
                for e, c in cands:
                    print(f"    candidate entry={e.id} {c.business_name!r} ₹{money(abs(e.amount))}")
        if leftover:
            print("\nDB PAYMENTS STILL UNDATED:")
            for e, c in leftover:
                print(f"  entry={e.id} ref={e.payment_ref!r} {c.business_name!r} ₹{money(abs(e.amount))}")

        if execute:
            db.commit()
            print(f"\nWrote value_date on {dated} payment(s). Amounts untouched.")
        else:
            print(f"\n[dry run] would date {dated} payment(s). Re-run with --execute to write.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
