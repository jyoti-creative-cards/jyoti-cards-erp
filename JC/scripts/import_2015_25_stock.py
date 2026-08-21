"""
Wipe and reimport all year_group='2015-25' products + stock
from FINAL LAST YEAR STOCK LIST WITH RATES FOR SITE.xlsx
"""
import openpyxl
import psycopg2
import psycopg2.extras
from decimal import Decimal

EXCEL_PATH = "/Users/sourabh/Desktop/personal/anshul/JC/FINAL LAST YEAR STOCK LIST WITH RATES FOR SITE.xlsx"
DB_URL = "postgresql://postgres:Bk0gNohhSeELKCB7@db.jovuafnpuhogmngjmpzd.supabase.co:5432/postgres"
VENDOR_ID = 19       # LEGACY STOCK
YEAR_GROUP = "2015-25"
UNIT = "pcs"

# ── 1. Parse Excel ─────────────────────────────────────────────────────────
wb = openpyxl.load_workbook(EXCEL_PATH, data_only=True)
ws = wb.active

products = []
seen_names = {}  # track lowercase name → index in products list
for i, row in enumerate(ws.iter_rows(values_only=True)):
    if i < 3:
        continue  # skip title + header rows
    item_name = str(row[0] or "").strip()
    if not item_name:
        continue
    alias       = str(row[1] or "").strip()
    no_of_bills = row[2]
    buy_price   = float(row[3]) if row[3] is not None else 0.0
    sell_price  = float(row[4]) if row[4] is not None else 0.0
    qty         = int(row[5]) if row[5] is not None else 0

    key = item_name.lower()
    if key in seen_names:
        # Make name unique by appending alias
        suffix = f" ({alias})" if alias else f" (dup)"
        item_name = item_name + suffix

    series = f"Bills: {int(no_of_bills)}" if no_of_bills is not None else None

    seen_names[item_name.lower()] = True
    products.append({
        "our_product_id":    item_name,
        "vendor_product_id": alias,
        "series":            series,
        "buying_price":      buy_price,
        "selling_price":     sell_price,
        "qty":               qty,
    })

print(f"Parsed {len(products)} products from Excel")

# ── 2. DB operations ───────────────────────────────────────────────────────
conn = psycopg2.connect(DB_URL)
conn.autocommit = False
cur = conn.cursor()

# Get existing product IDs for 2015-25
cur.execute("SELECT id FROM jc_catalog_products WHERE year_group = %s", (YEAR_GROUP,))
old_ids = [r[0] for r in cur.fetchall()]
print(f"Found {len(old_ids)} existing 2015-25 products to delete")

if old_ids:
    # Delete child records in FK-safe order
    tables_to_clear = [
        "jc_catalog_addon_links",
        "jc_catalog_alternatives",      # product_id and alternative_product_id
        "jc_stock_receipt_lines",
        "jc_stock_ledger",
        "jc_stock_balances",
        "jc_vendor_order_lines",
        "jc_vendor_open_lines",
        "jc_customer_order_lines",
        "jc_customer_open_lines",
        "jc_customer_bill_lines",
        "jc_customer_return_lines",
        "jc_debit_notes",
    ]
    for tbl in tables_to_clear:
        # Some tables use catalog_product_id, alternatives uses product_id/alternative_product_id
        if tbl == "jc_catalog_alternatives":
            cur.execute(
                f"DELETE FROM {tbl} WHERE product_id = ANY(%s) OR alternative_product_id = ANY(%s)",
                (old_ids, old_ids)
            )
        else:
            cur.execute(f"DELETE FROM {tbl} WHERE catalog_product_id = ANY(%s)", (old_ids,))
        print(f"  Deleted from {tbl}: {cur.rowcount} rows")

    cur.execute("DELETE FROM jc_catalog_products WHERE year_group = %s", (YEAR_GROUP,))
    print(f"  Deleted {cur.rowcount} catalog products")

# ── 3. Insert new products + stock ─────────────────────────────────────────
inserted = 0
skipped = 0

for p in products:
    # Insert catalog product
    cur.execute("""
        INSERT INTO jc_catalog_products
            (our_product_id, vendor_id, vendor_product_id, category, series,
             unit, year_group, buying_price, selling_price, image_keys, is_active)
        VALUES (%s, %s, %s, NULL, %s, %s, %s, %s, %s, '{}', TRUE)
        RETURNING id
    """, (
        p["our_product_id"],
        VENDOR_ID,
        p["vendor_product_id"],
        p["series"],
        UNIT,
        YEAR_GROUP,
        p["buying_price"],
        p["selling_price"],
    ))
    cp_id = cur.fetchone()[0]

    # Insert opening stock ledger entry
    notes = f"Opening stock from FINAL LAST YEAR STOCK LIST (01-07-2026)"
    if p["series"]:
        notes += f" | {p['series']}"

    cur.execute("""
        INSERT INTO jc_stock_ledger
            (catalog_product_id, entry_type, quantity_delta, balance_after,
             reference_type, notes, created_at)
        VALUES (%s, 'opening_balance', %s, %s, 'import', %s, NOW())
    """, (cp_id, p["qty"], p["qty"], notes))

    # Upsert stock balance
    cur.execute("""
        INSERT INTO jc_stock_balances (catalog_product_id, quantity_on_hand)
        VALUES (%s, %s)
        ON CONFLICT (catalog_product_id)
        DO UPDATE SET quantity_on_hand = EXCLUDED.quantity_on_hand
    """, (cp_id, p["qty"]))

    inserted += 1

print(f"\nInserted {inserted} products, skipped {skipped}")

conn.commit()
cur.close()
conn.close()
print("Done ✓")
