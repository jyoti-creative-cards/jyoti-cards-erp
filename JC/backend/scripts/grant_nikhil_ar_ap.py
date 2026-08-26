"""One-time: give Nikhil full AR/AP access (outstanding figures, ledger,
payment collection/payment with real context) — beyond the blind
"finance.write" quick-entry that Fiza/Raj keep.

Adds: ar.read, ar.write, ap.read, ap.write
Keeps: everything else Nikhil already has (no change to costs.read — buying
price stays hidden — and no change to delete-capable permissions).

Usage:
    python3 scripts/grant_nikhil_ar_ap.py            # dry run
    python3 scripts/grant_nikhil_ar_ap.py --execute  # write
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from app.db.session import SessionLocal
from app.models.staff import Staff
from app.services.permissions import dump_permissions, parse_permissions

PHONE = "9000000101"  # Nikhil
ADD_PERMS = ["ar.read", "ar.write", "ap.read", "ap.write"]


def main() -> None:
    execute = "--execute" in sys.argv
    db = SessionLocal()
    try:
        row = db.query(Staff).filter(Staff.phone == PHONE).first()
        if not row:
            print(f"No staff found with phone {PHONE}")
            return
        current = parse_permissions(row.permissions_json)
        updated = sorted(current | set(ADD_PERMS))
        print(f"{row.name} (#{row.id}) current: {sorted(current)}")
        print(f"{row.name} (#{row.id}) new:     {updated}")
        if execute:
            row.permissions_json = dump_permissions(updated)
            db.commit()
            print("Saved.")
        else:
            print("[dry run] Re-run with --execute to write.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
