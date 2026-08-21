"""
Update vendor details from VENDORS UPDT.XLSX.
- Updates existing vendors (name, alias, phone, address, GST, city)
- Inserts new vendors found in Excel but not in DB
- Never deletes or touches LEGACY STOCK / test vendors
"""
import re
import psycopg2
import psycopg2.extras
import openpyxl

EXCEL_PATH = "/Users/sourabh/Desktop/personal/anshul/JC/VENDORS UPDT.XLSX"
DB_URL = "postgresql://postgres:Bk0gNohhSeELKCB7@db.jovuafnpuhogmngjmpzd.supabase.co:5432/postgres"

def clean_str(s):
    if not s:
        return None
    return re.sub(r'\s+', ' ', str(s).strip().rstrip('.,'))

def clean_address(s):
    if not s:
        return None
    # collapse double commas, trailing commas/dots
    s = re.sub(r',\s*,', ',', str(s))
    s = re.sub(r'\s+', ' ', s).strip().rstrip('.,')
    return s or None

def clean_phone(s):
    if not s:
        return None
    digits = re.sub(r'\D', '', str(s))
    return digits[-10:] if len(digits) >= 10 else digits

def clean_gst(s):
    if not s:
        return None
    return str(s).strip().upper()

# ── Parse Excel ────────────────────────────────────────────────────────────
wb = openpyxl.load_workbook(EXCEL_PATH, data_only=True)
ws = wb.active

excel_vendors = []
for i, row in enumerate(ws.iter_rows(values_only=True)):
    if i < 3:
        continue
    name = clean_str(row[0])
    if not name:
        continue
    excel_vendors.append({
        "name":    name,
        "alias":   clean_str(row[1]),
        "city_raw": clean_str(row[2]),
        "address": clean_address(row[3]),
        "phone":   clean_phone(row[4]),
        "gst":     clean_gst(row[5]),
    })

print(f"Excel vendors: {len(excel_vendors)}")

# ── DB connection ──────────────────────────────────────────────────────────
conn = psycopg2.connect(DB_URL)
conn.autocommit = False
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

# Current DB vendors
cur.execute("SELECT id, business_name, phone, alias, address, gst_number, city_id FROM jc_vendors WHERE deleted_at IS NULL")
db_vendors = list(cur.fetchall())

# City map — Excel city name → DB city_id
CITY_MAP = {
    "AHEMDABAD": 3, "AHMEDABAD": 3,
    "DELHI": 2,
    "INDORE": 1,
    "GHAZIABAD": 4,
    "NAGPUR": 141,
}

# Create BALLARPUR city if missing
cur.execute("SELECT id FROM jc_cities WHERE LOWER(name)='ballarpur'")
row = cur.fetchone()
if row:
    CITY_MAP["BALLARPUR"] = row["id"]
else:
    cur.execute("INSERT INTO jc_cities (name, is_active) VALUES ('Ballarpur', TRUE) RETURNING id")
    new_id = cur.fetchone()["id"]
    CITY_MAP["BALLARPUR"] = new_id
    print(f"Created city Ballarpur id={new_id}")

# ── Match Excel → DB ───────────────────────────────────────────────────────
# Explicit phone + GST + name-based matches
# phone → db_id
phone_index = {v["phone"]: v["id"] for v in db_vendors if v["phone"]}
gst_index   = {v["gst_number"]: v["id"] for v in db_vendors if v["gst_number"]}
name_index  = {v["business_name"].strip().lower(): v["id"] for v in db_vendors}

# Hard-coded overrides for cases where phone/name differ but they're the same vendor
HARD_MATCH = {
    # excel_name_lower → db_id
    "bahubali cards":                      7,   # DB phone wrong, same name
    "k.b. wedding cards":                  25,  # KB CORPORATION — same address
    "myraa enterprises":                   3,
    "neha creations":                      26,
    "sona cards & paper":                  24,
    "utsav cards":                         14,
    "vee pee creations":                   5,   # V.P. Bharat — same address
    "kiran cards":                         16,  # SHREE GANESH CARDS — same phone
    "shri balaji packers  (rjndr)":        11,  # RAJENDRA CARDS — same phone
    "gagan card products":                 13,  # GAGAN CARDS — same phone
    "nice cards":                          4,   # NICE WEDDING CARDS — same phone
    "raj trading":                         18,  # RAJ TRADING - NAGPUR
    "rakshit cards creation (shweta)":     None, # new
    "batra cards-n-arts":                  None, # new
    "dev enterprises (navin bhai)":        None, # new
    "kirti offset & paper mart":           None, # new
    "monarch paper enterprises":           None, # new
    "prince card & arts products":         None, # new
}

updated = 0
inserted = 0

for ev in excel_vendors:
    name_key = ev["name"].lower().strip()
    city_key = (ev["city_raw"] or "").upper().strip()
    city_id  = CITY_MAP.get(city_key)

    # Find matching DB vendor
    db_id = None
    if name_key in HARD_MATCH:
        db_id = HARD_MATCH[name_key]
    elif ev["gst"] and ev["gst"] in gst_index:
        db_id = gst_index[ev["gst"]]
    elif ev["phone"] and ev["phone"] in phone_index:
        db_id = phone_index[ev["phone"]]
    elif name_key in name_index:
        db_id = name_index[name_key]

    if db_id is None:
        # Insert new vendor
        cur.execute("""
            INSERT INTO jc_vendors (business_name, alias, phone, address, gst_number, city_id, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, TRUE)
        """, (ev["name"], ev["alias"], ev["phone"], ev["address"], ev["gst"], city_id))
        print(f"  INSERT: {ev['name']}")
        inserted += 1
    else:
        cur.execute("""
            UPDATE jc_vendors
            SET business_name = %s,
                alias         = %s,
                phone         = %s,
                address       = %s,
                gst_number    = %s,
                city_id       = COALESCE(%s, city_id)
            WHERE id = %s
        """, (ev["name"], ev["alias"], ev["phone"], ev["address"], ev["gst"], city_id, db_id))
        print(f"  UPDATE id={db_id}: {ev['name']}")
        updated += 1

conn.commit()
cur.close()
conn.close()
print(f"\nDone — updated {updated}, inserted {inserted}")
