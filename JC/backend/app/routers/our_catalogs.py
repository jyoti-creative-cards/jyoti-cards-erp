from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import AuthContext, require_permission
from app.schemas.stock_journal import JournalIn, JournalLineIn
from app.services.biz_date import today_ist
from app.services.our_catalogs import (
    assign_parties,
    catalog_detail,
    delete_issue,
    for_customer,
    import_sample_journals,
    list_catalogs,
    record_issue,
    unassign_party,
    update_issue,
)
from app.services.stock_journal import post_journal
from app.models.our_catalog import OurCatalog, OurCatalogLine

router = APIRouter(prefix="/our-catalogs", tags=["our-catalogs"])


class CatalogLineIn(BaseModel):
    catalog_product_id: int
    quantity: int = Field(..., gt=0)


class CatalogCreate(BaseModel):
    name: str
    copies: int = Field(..., gt=0)
    lines: List[CatalogLineIn]
    journal_date: Optional[date] = None


class AssignIn(BaseModel):
    customer_ids: List[int]


class IssueIn(BaseModel):
    customer_id: int
    copies: int = Field(1, gt=0)
    price: Decimal = Decimal("0")
    issued_on: Optional[date] = None
    note: Optional[str] = None


class IssueUpdate(BaseModel):
    copies: int = Field(..., gt=0)
    issued_on: Optional[date] = None


@router.get("")
def get_catalogs(db: Session = Depends(get_db), auth: AuthContext = Depends(require_permission("catalog.read"))):
    return list_catalogs(db)


@router.get("/for-customer/{customer_id}")
def catalogs_for_customer(customer_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permission("customer_orders.read"))):
    return for_customer(db, customer_id)


@router.post("/import-journals")
def import_journals(db: Session = Depends(get_db), auth: AuthContext = Depends(require_permission("catalog.write"))):
    made = import_sample_journals(db)
    db.commit()
    return {"imported": made}


@router.get("/{catalog_id}")
def get_catalog(catalog_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permission("catalog.read"))):
    return catalog_detail(db, catalog_id)


@router.post("", status_code=201)
def create_catalog(body: CatalogCreate, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permission("catalog.write"))):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Enter the catalog name")
    if not body.lines:
        raise HTTPException(400, "Add the items in this catalog")
    posted = post_journal(
        db,
        JournalIn(
            journal_date=body.journal_date or today_ist(),
            kind="consumption",
            narration=name,
            expense_category="sample catalogues",
            lines=[
                JournalLineIn(catalog_product_id=ln.catalog_product_id, quantity=ln.quantity * body.copies)
                for ln in body.lines
            ],
        ),
        auth,
    )
    catalog = OurCatalog(
        name=name,
        copies_made=body.copies,
        expense_id=posted.expense_id,
        stock_journal_id=posted.id,
    )
    db.add(catalog)
    db.flush()
    for ln in body.lines:
        db.add(OurCatalogLine(catalog_id=catalog.id, catalog_product_id=ln.catalog_product_id, quantity=ln.quantity))
    db.commit()
    return catalog_detail(db, catalog.id)


@router.post("/{catalog_id}/assign")
def assign(catalog_id: int, body: AssignIn, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permission("catalog.write"))):
    added = assign_parties(db, catalog_id, body.customer_ids)
    db.commit()
    return {"added": added}


@router.delete("/{catalog_id}/assign/{customer_id}")
def unassign(catalog_id: int, customer_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permission("catalog.write"))):
    unassign_party(db, catalog_id, customer_id)
    db.commit()
    return catalog_detail(db, catalog_id)


@router.patch("/issues/{issue_id}")
def edit_issue(issue_id: int, body: IssueUpdate, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permission("catalog.write"))):
    issue = update_issue(db, issue_id, copies=body.copies, issued_on=body.issued_on)
    catalog_id = issue.catalog_id
    db.commit()
    return catalog_detail(db, catalog_id)


@router.delete("/issues/{issue_id}")
def remove_issue(issue_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permission("catalog.write"))):
    catalog_id = delete_issue(db, issue_id)
    db.commit()
    return catalog_detail(db, catalog_id)


@router.post("/{catalog_id}/issues", status_code=201)
def add_issue(catalog_id: int, body: IssueIn, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permission("catalog.write"))):
    record_issue(
        db,
        catalog_id=catalog_id,
        customer_id=body.customer_id,
        copies=body.copies,
        price=body.price,
        issued_on=body.issued_on,
        bill_id=None,
        note=body.note,
    )
    db.commit()
    return catalog_detail(db, catalog_id)
