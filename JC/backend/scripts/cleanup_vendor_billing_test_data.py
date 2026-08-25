from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, OrderedDict
from decimal import Decimal
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import psycopg2
from psycopg2.extras import RealDictCursor

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings

JUNK_VENDOR_RECEIPT_COUNTS = {
    "test vendor": 2,
    "delete ven": 4,
}

REAL_VENDOR_NAME = "DEV PRINT & PACK PRIVATE LIMITED"
REAL_VENDOR_MATCHES = (
    ("bill_number", "direct opening demo"),
    ("order_receipt_number", "OLD YEAR"),
)

JUNK_VENDOR_NAMES = (
    "test vendor",
    "delete ven",
    "agrawal test vendor",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Clean up vendor billing test/demo production data.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually commit deletions after interactive confirmation.",
    )
    return parser.parse_args()


def prepare_database_url(raw_url: str) -> str:
    database_url = raw_url.strip()
    match = re.match(
        r"postgresql(?:\+psycopg2)?://postgres:([^@]+)@db\.([a-z0-9]+)\.supabase\.co:5432/(.+)",
        database_url,
    )
    if match:
        password, project, dbname = match.group(1), match.group(2), match.group(3)
        database_url = (
            f"postgresql://postgres.{project}:{password}"
            f"@aws-1-ap-southeast-1.pooler.supabase.com:6543/{dbname}"
        )

    parts = urlsplit(database_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.setdefault("sslmode", "require")
    query.setdefault("connect_timeout", "15")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def format_value(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, Decimal):
        return str(value.quantize(Decimal("0.01")))
    return str(value)


def print_rows(title: str, rows: Iterable[dict], fields: tuple[str, ...]) -> None:
    rows = list(rows)
    print(f"{title}: {len(rows)} row(s)")
    if not rows:
        return
    for row in rows:
        bits = [f"{field}={format_value(row.get(field))}" for field in fields]
        print(f"  - {', '.join(bits)}")


def fetch_vendor_receipts(cursor: RealDictCursor, vendor_name: str) -> list[dict]:
    cursor.execute(
        """
        SELECT
            r.id,
            v.id AS vendor_id,
            v.business_name,
            r.receipt_type,
            r.order_receipt_number,
            r.bill_number,
            r.total_billed_amount,
            r.actual_ap_amount,
            r.expected_bill_amount,
            r.bill_status,
            r.received_at
        FROM jc_stock_receipts r
        JOIN jc_vendors v ON v.id = r.vendor_id
        WHERE v.business_name = %s
        ORDER BY r.id
        """,
        (vendor_name,),
    )
    return cursor.fetchall()


def fetch_exact_vendor_receipt(
    cursor: RealDictCursor,
    vendor_name: str,
    field_name: str,
    expected_value: str,
) -> dict:
    if field_name not in {"bill_number", "order_receipt_number"}:
        raise ValueError(f"Unsupported field name: {field_name}")
    cursor.execute(
        f"""
        SELECT
            r.id,
            v.id AS vendor_id,
            v.business_name,
            r.receipt_type,
            r.order_receipt_number,
            r.bill_number,
            r.total_billed_amount,
            r.actual_ap_amount,
            r.expected_bill_amount,
            r.bill_status,
            r.received_at
        FROM jc_stock_receipts r
        JOIN jc_vendors v ON v.id = r.vendor_id
        WHERE v.business_name = %s
          AND r.{field_name} = %s
        ORDER BY r.id
        """,
        (vendor_name, expected_value),
    )
    rows = cursor.fetchall()
    if len(rows) != 1:
        details = [
            (
                f"id={row['id']}, receipt_type={row['receipt_type']}, "
                f"order_receipt_number={format_value(row['order_receipt_number'])}, "
                f"bill_number={format_value(row['bill_number'])}"
            )
            for row in rows
        ]
        raise RuntimeError(
            "Safety check failed for "
            f"vendor={vendor_name!r}, {field_name}={expected_value!r}: expected exactly 1 receipt, found {len(rows)}. "
            f"Matches: {details}"
        )
    return rows[0]


def delete_returning(cursor: RealDictCursor, sql: str, params: tuple = ()) -> list[dict]:
    cursor.execute(sql, params)
    return cursor.fetchall()


def vendor_name_placeholders(names: tuple[str, ...]) -> str:
    return ", ".join(["%s"] * len(names))


def main() -> int:
    args = parse_args()
    settings = get_settings()
    database_url = prepare_database_url(settings.database_url)
    mode = "EXECUTE" if args.execute else "DRY-RUN"

    print(f"Mode: {mode}")
    print("Safety: exact-match cleanup for approved vendor billing test data only.")

    connection = psycopg2.connect(database_url, cursor_factory=RealDictCursor)
    connection.autocommit = False
    cursor = connection.cursor()

    summary: OrderedDict[str, int] = OrderedDict(
        [
            ("matched_receipts", 0),
            ("jc_debit_notes", 0),
            ("jc_ap_ledger_entries", 0),
            ("jc_stock_receipt_lines", 0),
            ("jc_stock_receipts", 0),
            ("jc_vendor_order_lines", 0),
            ("jc_vendor_order_placements", 0),
            ("jc_vendor_orders", 0),
            ("jc_vendors_soft_deleted", 0),
        ]
    )

    try:
        print("")
        print("Step 1: Match the 8 expected stock receipts.")
        matched_receipts: list[dict] = []
        seen_receipt_ids: set[int] = set()
        for vendor_name, expected_count in JUNK_VENDOR_RECEIPT_COUNTS.items():
            vendor_receipts = fetch_vendor_receipts(cursor, vendor_name)
            if len(vendor_receipts) != expected_count:
                details = [
                    (
                        f"id={row['id']}, receipt_type={row['receipt_type']}, "
                        f"order_receipt_number={format_value(row['order_receipt_number'])}, "
                        f"bill_number={format_value(row['bill_number'])}"
                    )
                    for row in vendor_receipts
                ]
                raise RuntimeError(
                    "Safety check failed for "
                    f"vendor={vendor_name!r}: expected exactly {expected_count} receipt rows, found {len(vendor_receipts)}. "
                    f"Matches: {details}"
                )
            print(f"  - vendor={vendor_name!r} -> matched {len(vendor_receipts)} row(s)")
            for receipt in vendor_receipts:
                if receipt["id"] in seen_receipt_ids:
                    raise RuntimeError(
                        f"Safety check failed: receipt id {receipt['id']} matched more than one expected target."
                    )
                seen_receipt_ids.add(receipt["id"])
                matched_receipts.append(receipt)

        dev_vendor_receipts: list[dict] = []
        for field_name, expected_value in REAL_VENDOR_MATCHES:
            receipt = fetch_exact_vendor_receipt(
                cursor,
                REAL_VENDOR_NAME,
                field_name,
                expected_value,
            )
            if receipt["id"] in seen_receipt_ids:
                raise RuntimeError(
                    f"Safety check failed: receipt id {receipt['id']} matched more than one expected target."
                )
            seen_receipt_ids.add(receipt["id"])
            dev_vendor_receipts.append(receipt)
            matched_receipts.append(receipt)

        if len(dev_vendor_receipts) != len(REAL_VENDOR_MATCHES):
            raise RuntimeError(
                "Safety check failed for "
                f"vendor={REAL_VENDOR_NAME!r}: expected exactly {len(REAL_VENDOR_MATCHES)} matched rows, "
                f"found {len(dev_vendor_receipts)}."
            )
        for receipt in dev_vendor_receipts:
            is_expected_match = (
                receipt["bill_number"] == "direct opening demo"
                or receipt["order_receipt_number"] == "OLD YEAR"
            )
            if not is_expected_match:
                raise RuntimeError(
                    "Safety check failed for "
                    f"vendor={REAL_VENDOR_NAME!r}: accidentally matched unexpected receipt id={receipt['id']}."
                )
        print(f"  - vendor={REAL_VENDOR_NAME!r} -> matched {len(dev_vendor_receipts)} row(s)")

        if len(matched_receipts) != 8:
            raise RuntimeError(
                f"Safety check failed: expected exactly 8 matched receipts, found {len(matched_receipts)}."
            )

        for receipt in matched_receipts:
            amount = (
                receipt["actual_ap_amount"]
                if receipt["actual_ap_amount"] is not None
                else receipt["total_billed_amount"]
            )
            if amount is None:
                amount = receipt["expected_bill_amount"]
            print(
                "  - "
                f"id={receipt['id']}, vendor={receipt['business_name']!r}, "
                f"receipt_type={receipt['receipt_type']}, "
                f"order_receipt_number={format_value(receipt['order_receipt_number'])}, "
                f"bill_number={format_value(receipt['bill_number'])}, "
                f"amount={format_value(amount)}, bill_status={format_value(receipt['bill_status'])}"
            )

        summary["matched_receipts"] = len(matched_receipts)

        print("")
        print("Step 2: Delete receipt-linked debit notes, AP rows, receipt lines, and receipts.")
        for receipt in matched_receipts:
            receipt_id = receipt["id"]
            print(f"Receipt id={receipt_id}, vendor={receipt['business_name']!r}")
            debit_notes = delete_returning(
                cursor,
                """
                DELETE FROM jc_debit_notes
                WHERE receipt_id = %s
                RETURNING id, vendor_id, receipt_id, note_type, direction, amount, source
                """,
                (receipt_id,),
            )
            print_rows(
                "  jc_debit_notes",
                debit_notes,
                ("id", "vendor_id", "receipt_id", "note_type", "direction", "amount", "source"),
            )
            summary["jc_debit_notes"] += len(debit_notes)

            ap_rows = delete_returning(
                cursor,
                """
                DELETE FROM jc_ap_ledger_entries
                WHERE receipt_id = %s
                RETURNING id, vendor_id, receipt_id, debit_note_id, entry_type, amount, description
                """,
                (receipt_id,),
            )
            print_rows(
                "  jc_ap_ledger_entries",
                ap_rows,
                ("id", "vendor_id", "receipt_id", "debit_note_id", "entry_type", "amount", "description"),
            )
            summary["jc_ap_ledger_entries"] += len(ap_rows)

            receipt_lines = delete_returning(
                cursor,
                """
                DELETE FROM jc_stock_receipt_lines
                WHERE receipt_id = %s
                RETURNING id, receipt_id, catalog_product_id, our_product_id, quantity_received, quantity_billed, billed_amount
                """,
                (receipt_id,),
            )
            print_rows(
                "  jc_stock_receipt_lines",
                receipt_lines,
                (
                    "id",
                    "receipt_id",
                    "catalog_product_id",
                    "our_product_id",
                    "quantity_received",
                    "quantity_billed",
                    "billed_amount",
                ),
            )
            summary["jc_stock_receipt_lines"] += len(receipt_lines)

            receipt_rows = delete_returning(
                cursor,
                """
                DELETE FROM jc_stock_receipts
                WHERE id = %s
                RETURNING id, vendor_id, receipt_type, order_receipt_number, bill_number, total_billed_amount, actual_ap_amount
                """,
                (receipt_id,),
            )
            print_rows(
                "  jc_stock_receipts",
                receipt_rows,
                ("id", "vendor_id", "receipt_type", "order_receipt_number", "bill_number", "total_billed_amount", "actual_ap_amount"),
            )
            summary["jc_stock_receipts"] += len(receipt_rows)

        print("")
        print("Step 2b: Resolve junk vendor ids up front (id-scoped deletes from here on).")
        vendor_name_sql = vendor_name_placeholders(JUNK_VENDOR_NAMES)
        cursor.execute(
            f"SELECT id, business_name FROM jc_vendors WHERE business_name IN ({vendor_name_sql})",
            JUNK_VENDOR_NAMES,
        )
        junk_vendor_rows = cursor.fetchall()
        junk_vendor_name_counts = Counter(row["business_name"] for row in junk_vendor_rows)
        if junk_vendor_name_counts != Counter(JUNK_VENDOR_NAMES):
            raise RuntimeError(
                "Safety check failed for junk vendors: expected exactly one vendor row for each of "
                f"{JUNK_VENDOR_NAMES}, found {dict(junk_vendor_name_counts)}."
            )
        junk_vendor_ids = tuple(row["id"] for row in junk_vendor_rows)
        print_rows("  jc_vendors (resolved)", junk_vendor_rows, ("id", "business_name"))
        vendor_id_sql = vendor_name_placeholders(junk_vendor_ids)

        print("")
        print("Step 3: Delete remaining AP ledger rows for junk vendor ids.")
        remaining_ap_rows = delete_returning(
            cursor,
            f"""
            DELETE FROM jc_ap_ledger_entries e
            USING jc_vendors v
            WHERE e.vendor_id = v.id
              AND v.id IN ({vendor_id_sql})
            RETURNING e.id, v.business_name, e.vendor_id, e.entry_type, e.amount, e.receipt_id, e.debit_note_id, e.description
            """,
            junk_vendor_ids,
        )
        print_rows(
            "jc_ap_ledger_entries",
            remaining_ap_rows,
            ("id", "business_name", "vendor_id", "entry_type", "amount", "receipt_id", "debit_note_id", "description"),
        )
        summary["jc_ap_ledger_entries"] += len(remaining_ap_rows)

        print("")
        print("Step 4: Delete vendor orders, placements, and lines for junk vendor ids.")
        order_lines = delete_returning(
            cursor,
            f"""
            DELETE FROM jc_vendor_order_lines l
            USING jc_vendor_order_placements p, jc_vendor_orders o, jc_vendors v
            WHERE l.placement_id = p.id
              AND p.vendor_order_id = o.id
              AND o.vendor_id = v.id
              AND v.id IN ({vendor_id_sql})
            RETURNING l.id, v.business_name, l.placement_id, l.catalog_product_id, l.our_product_id, l.quantity, l.quantity_remaining
            """,
            junk_vendor_ids,
        )
        print_rows(
            "jc_vendor_order_lines",
            order_lines,
            ("id", "business_name", "placement_id", "catalog_product_id", "our_product_id", "quantity", "quantity_remaining"),
        )
        summary["jc_vendor_order_lines"] += len(order_lines)

        placements = delete_returning(
            cursor,
            f"""
            DELETE FROM jc_vendor_order_placements p
            USING jc_vendor_orders o, jc_vendors v
            WHERE p.vendor_order_id = o.id
              AND o.vendor_id = v.id
              AND v.id IN ({vendor_id_sql})
            RETURNING p.id, v.business_name, p.vendor_order_id, p.status, p.placed_by_name, p.placed_at
            """,
            junk_vendor_ids,
        )
        print_rows(
            "jc_vendor_order_placements",
            placements,
            ("id", "business_name", "vendor_order_id", "status", "placed_by_name", "placed_at"),
        )
        summary["jc_vendor_order_placements"] += len(placements)

        orders = delete_returning(
            cursor,
            f"""
            DELETE FROM jc_vendor_orders o
            USING jc_vendors v
            WHERE o.vendor_id = v.id
              AND v.id IN ({vendor_id_sql})
            RETURNING o.id, v.business_name, o.vendor_id, o.bucket, o.status, o.is_open
            """,
            junk_vendor_ids,
        )
        print_rows(
            "jc_vendor_orders",
            orders,
            ("id", "business_name", "vendor_id", "bucket", "status", "is_open"),
        )
        summary["jc_vendor_orders"] += len(orders)

        print("")
        print("Step 5: Soft-delete the 3 junk vendors.")
        vendors = delete_returning(
            cursor,
            f"""
            UPDATE jc_vendors
            SET is_active = FALSE,
                deleted_at = NOW()
            WHERE id IN ({vendor_id_sql})
            RETURNING id, business_name, is_active, deleted_at
            """,
            junk_vendor_ids,
        )
        print_rows(
            "jc_vendors",
            vendors,
            ("id", "business_name", "is_active", "deleted_at"),
        )
        vendor_name_counts = Counter(row["business_name"] for row in vendors)
        if vendor_name_counts != Counter(JUNK_VENDOR_NAMES):
            raise RuntimeError(
                "Safety check failed for junk vendors: expected exactly one vendor row for each of "
                f"{JUNK_VENDOR_NAMES}, found {dict(vendor_name_counts)}."
            )
        summary["jc_vendors_soft_deleted"] = len(vendors)

        print("")
        print("Step 6: Final summary.")
        for table_name, count in summary.items():
            print(f"  {table_name}: {count}")

        if args.execute:
            if not sys.stdin.isatty():
                connection.rollback()
                print("")
                print("Abort: --execute requires an interactive terminal (stdin is not a TTY). Transaction rolled back.")
                return 1
            print("")
            confirmation = input("Type 'yes' to commit these deletions: ").strip()
            if confirmation != "yes":
                connection.rollback()
                print("Abort: confirmation mismatch. Transaction rolled back.")
                return 1
            connection.commit()
            print("Commit complete.")
            return 0

        connection.rollback()
        print("")
        print("Dry-run complete. Transaction rolled back. No changes committed.")
        return 0
    except Exception as exc:
        connection.rollback()
        print("")
        print(f"Abort: {exc}")
        return 1
    finally:
        cursor.close()
        connection.close()


if __name__ == "__main__":
    sys.exit(main())
