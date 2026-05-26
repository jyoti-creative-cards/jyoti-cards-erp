"""Freight vendor management API."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import require_admin
from app.models.freight_vendor import FreightVendor
from app.models.freight_ledger_entry import FreightLedgerEntry

router = APIRouter(prefix="/freight-vendors", tags=["freight-vendors"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class FreightVendorIn(BaseModel):
    name: str
    phone: Optional[str] = None
    notes: Optional[str] = None


class FreightVendorPublic(BaseModel):
    id: int
    name: str
    phone: Optional[str]
    notes: Optional[str]
    balance_due: str


class FreightLedgerIn(BaseModel):
    freight_vendor_id: int
    entry_date: date
    entry_type: str  # "charge" | "payment"
    amount: Decimal
    reference: Optional[str] = None
    notes: Optional[str] = None


class FreightLedgerPublic(BaseModel):
    id: int
    freight_vendor_id: int
    entry_date: date
    entry_type: str
    amount: str
    reference: Optional[str]
    notes: Optional[str]


def _fv_public(r: FreightVendor) -> FreightVendorPublic:
    return FreightVendorPublic(
        id=r.id,
        name=r.name,
        phone=r.phone,
        notes=r.notes,
        balance_due=format(r.balance_due or Decimal("0"), "f"),
    )


def _fl_public(r: FreightLedgerEntry) -> FreightLedgerPublic:
    return FreightLedgerPublic(
        id=r.id,
        freight_vendor_id=r.freight_vendor_id,
        entry_date=r.entry_date,
        entry_type=r.entry_type,
        amount=format(r.amount, "f"),
        reference=r.reference,
        notes=r.notes,
    )


# ── Freight vendor CRUD ───────────────────────────────────────────────────────

@router.get("", response_model=List[FreightVendorPublic], dependencies=[Depends(require_admin)])
def list_freight_vendors(db: Session = Depends(get_db)):
    return [_fv_public(r) for r in db.query(FreightVendor).order_by(FreightVendor.name).all()]


@router.post("", response_model=FreightVendorPublic, status_code=201, dependencies=[Depends(require_admin)])
def create_freight_vendor(body: FreightVendorIn, db: Session = Depends(get_db)):
    row = FreightVendor(name=body.name.strip(), phone=body.phone, notes=body.notes)
    db.add(row); db.commit(); db.refresh(row)
    return _fv_public(row)


@router.patch("/{vendor_id}", response_model=FreightVendorPublic, dependencies=[Depends(require_admin)])
def update_freight_vendor(vendor_id: int, body: FreightVendorIn, db: Session = Depends(get_db)):
    row = db.get(FreightVendor, vendor_id)
    if not row:
        raise HTTPException(404, "not found")
    row.name = body.name.strip()
    if body.phone is not None:
        row.phone = body.phone
    if body.notes is not None:
        row.notes = body.notes
    db.add(row); db.commit(); db.refresh(row)
    return _fv_public(row)


@router.delete("/{vendor_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_freight_vendor(vendor_id: int, db: Session = Depends(get_db)):
    row = db.get(FreightVendor, vendor_id)
    if row:
        db.delete(row); db.commit()


# ── Ledger entries ────────────────────────────────────────────────────────────

@router.get("/{vendor_id}/ledger", response_model=List[FreightLedgerPublic], dependencies=[Depends(require_admin)])
def get_ledger(vendor_id: int, db: Session = Depends(get_db)):
    rows = (
        db.query(FreightLedgerEntry)
        .filter(FreightLedgerEntry.freight_vendor_id == vendor_id)
        .order_by(FreightLedgerEntry.entry_date.desc(), FreightLedgerEntry.id.desc())
        .all()
    )
    return [_fl_public(r) for r in rows]


@router.post("/ledger", response_model=FreightLedgerPublic, status_code=201, dependencies=[Depends(require_admin)])
def add_ledger_entry(body: FreightLedgerIn, db: Session = Depends(get_db)):
    vendor = db.get(FreightVendor, body.freight_vendor_id)
    if not vendor:
        raise HTTPException(404, "freight vendor not found")

    if body.entry_type not in ("charge", "payment"):
        raise HTTPException(400, "entry_type must be 'charge' or 'payment'")

    row = FreightLedgerEntry(
        freight_vendor_id=body.freight_vendor_id,
        entry_date=body.entry_date,
        entry_type=body.entry_type,
        amount=body.amount,
        reference=body.reference,
        notes=body.notes,
    )
    db.add(row)

    # Update running balance on vendor
    if body.entry_type == "charge":
        vendor.balance_due = (vendor.balance_due or Decimal("0")) + body.amount
    else:
        vendor.balance_due = (vendor.balance_due or Decimal("0")) - body.amount
    db.add(vendor)
    db.commit(); db.refresh(row)
    return _fl_public(row)


@router.delete("/ledger/{entry_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_ledger_entry(entry_id: int, db: Session = Depends(get_db)):
    row = db.get(FreightLedgerEntry, entry_id)
    if not row:
        return
    vendor = db.get(FreightVendor, row.freight_vendor_id)
    if vendor:
        if row.entry_type == "charge":
            vendor.balance_due = (vendor.balance_due or Decimal("0")) - row.amount
        else:
            vendor.balance_due = (vendor.balance_due or Decimal("0")) + row.amount
        db.add(vendor)
    db.delete(row)
    db.commit()
