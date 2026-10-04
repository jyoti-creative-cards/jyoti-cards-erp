"""Void / restore / purge for vendor receipts (incl. bills) and debit notes.

Append-only accounting, but "I entered this by mistake" needs an undo path:
  - void:    soft-delete (deleted_at) + reverse the stock effect with a real ledger entry.
             AP entries tied to the receipt/debit-note are excluded from all "active" queries
             the instant deleted_at is set (see ap_ledger.py / ledger.py / stock.py filters).
  - restore: clear deleted_at on the receipt/note and on the AP entries voided in the *same*
             action (matched by timestamp), and re-apply the stock effect.
  - purge:   permanent — hard-delete the row(s) and their AP entries. Requires void first.

Stock reversal always allowed to go negative (received qty may already be shipped out) —
this only corrects the running total, it never blocks.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional
from fastapi import HTTPException
from sqlalchemy.orm import Session
from app.deps import AuthContext
from app.models.accounts_payable import ApLedgerEntry
from app.models.debit_note import DebitNote
from app.models.stock import StockReceipt, StockReceiptLine
from app.models.vendor import Vendor
from app.services.activity import log_from_auth
from app.services.open_lines import add_to_open, reduce_from_open
from app.services.stock_receipt import add_stock

def _vendor_label(db: Session, vendor_id: int) -> str:
    from app.models.city import City

    vendor = db.get(Vendor, vendor_id)
    if not vendor:
        return f"Vendor #{vendor_id}"
    city_name = None
    if vendor.city_id:
        city = db.get(City, vendor.city_id)
        city_name = city.name if city else None
    return f"{vendor.business_name} — {city_name}" if city_name else vendor.business_name

def _customer_label(db: Session, customer_id: int) -> str:
    from app.models.city import City
    from app.models.customer import Customer

    customer = db.get(Customer, customer_id)
    if not customer:
        return f"Customer #{customer_id}"
    city_name = None
    if customer.city_id:
        city = db.get(City, customer.city_id)
        city_name = city.name if city else None
    return f"{customer.business_name} — {city_name}" if city_name else customer.business_name

def _reverse_item_dn_stock(db: Session, dn: DebitNote, label: str, note: str) -> None:
    """Undo create_debit_note's stock effect for an item-type note (it applied -quantity)."""
    if dn.note_type == "item" and dn.catalog_product_id and dn.quantity:
        add_stock(
            db,
            catalog_product_id=int(dn.catalog_product_id),
            our_product_id=dn.our_product_id or "",
            quantity=int(dn.quantity),  # undo the -quantity applied at creation
            entry_type="void_debit_note",
            reference_type="debit_note",
            reference_id=dn.id,
            party=label,
            notes=note,
        )

def _reapply_item_dn_stock(db: Session, dn: DebitNote, label: str, note: str) -> None:
    """Re-apply create_debit_note's stock effect for an item-type note on restore."""
    if dn.note_type == "item" and dn.catalog_product_id and dn.quantity:
        add_stock(
            db,
            catalog_product_id=int(dn.catalog_product_id),
            our_product_id=dn.our_product_id or "",
            quantity=-int(dn.quantity),
            entry_type="restore_debit_note",
            reference_type="debit_note",
            reference_id=dn.id,
            party=label,
            notes=note,
        )
