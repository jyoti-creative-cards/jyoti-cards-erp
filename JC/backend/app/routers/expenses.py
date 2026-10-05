from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import func

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session, object_session

from app.db.session import get_db
from app.deps import AuthContext, require_admin, require_permission
from app.models.expense import Expense, ExpenseHead, ExpenseSubhead
from app.services.activity import log_from_auth
from app.services import response_cache
from app.services.document_present import present

router = APIRouter(prefix="/expenses", tags=["expenses"])


class ExpenseIn(BaseModel):
    expense_date: date
    category: str = ""
    description: Optional[str] = None
    amount: Decimal
    reference: Optional[str] = None
    head_id: Optional[int] = None
    subhead_id: Optional[int] = None


class HeadIn(BaseModel):
    name: str


def _clean_head_name(name: str) -> str:
    text = " ".join((name or "").split())
    if not text:
        raise HTTPException(400, "Enter a name")
    if "/" in text or "%" in text or "_" in text:
        raise HTTPException(400, "Name cannot contain / _ or %")
    if len(text) > 80:
        raise HTTPException(400, "Name is too long")
    return text


def resolve_expense_category(db: Session, body: ExpenseIn) -> str:
    if body.head_id or body.subhead_id:
        if not body.head_id or not body.subhead_id:
            raise HTTPException(400, "Pick a head and a sub-head")
        head = db.get(ExpenseHead, body.head_id)
        sub = db.get(ExpenseSubhead, body.subhead_id)
        if not head or not sub or sub.head_id != head.id:
            raise HTTPException(400, "Pick a head and a sub-head")
        return f"{head.name} / {sub.name}".lower()
    text = (body.category or "").strip().lower()
    if not text:
        raise HTTPException(400, "Pick a head and a sub-head")
    return text


def expense_head_tree(db: Session) -> list[dict]:
    heads = db.query(ExpenseHead).order_by(ExpenseHead.name.asc(), ExpenseHead.id.asc()).all()
    subs = db.query(ExpenseSubhead).order_by(ExpenseSubhead.name.asc(), ExpenseSubhead.id.asc()).all()
    grouped = (
        db.query(Expense.category, func.count(Expense.id), func.coalesce(func.sum(Expense.amount), 0))
        .group_by(Expense.category)
        .all()
    )
    by_cat = {(c or "").lower(): (int(n), Decimal(str(total))) for c, n, total in grouped}
    out = []
    for head in heads:
        own_n, own_amt = by_cat.get(head.name.lower(), (0, Decimal("0")))
        count = own_n
        total = own_amt
        sub_rows = []
        for sub in subs:
            if sub.head_id != head.id:
                continue
            key = f"{head.name} / {sub.name}".lower()
            n, amt = by_cat.get(key, (0, Decimal("0")))
            count += n
            total += amt
            sub_rows.append({
                "id": sub.id,
                "name": sub.name,
                "category": key,
                "count": n,
                "total": format(amt, "f"),
            })
        out.append({
            "id": head.id,
            "name": head.name,
            "count": count,
            "total": format(total, "f"),
            "subheads": sub_rows,
        })
    return out


class ExpensePublic(BaseModel):
    id: int
    expense_date: date
    category: str
    description: Optional[str] = None
    amount: str
    reference: Optional[str] = None
    freight_agent_id: Optional[int] = None
    addon_product_id: Optional[int] = None
    is_cash: bool = True
    created_by_name: str
    display_date: Optional[date] = None
    display_name: Optional[str] = None
    status: Optional[str] = None

    @classmethod
    def from_row(cls, row: Expense) -> "ExpensePublic":
        db = object_session(row)
        view = present(db, "expense", row) if db is not None else {}
        return cls(
            id=row.id,
            expense_date=row.expense_date,
            category=row.category,
            description=row.description,
            amount=format(row.amount, "f"),
            reference=row.reference,
            freight_agent_id=row.freight_agent_id,
            addon_product_id=row.addon_product_id,
            is_cash=True if row.is_cash is None else bool(row.is_cash),
            created_by_name=row.created_by_name,
            display_date=view.get("display_date") or row.expense_date,
            display_name=view.get("display_name") or row.category,
            status=view.get("status") or "open",
        )


@router.get("/heads")
def list_expense_heads(
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("finance.write")),
):
    return expense_head_tree(db)


@router.post("/heads", status_code=201)
def create_expense_head(
    body: HeadIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    name = _clean_head_name(body.name)
    taken = db.query(ExpenseHead).filter(func.lower(ExpenseHead.name) == name.lower()).first()
    if taken:
        raise HTTPException(400, "That head already exists")
    row = ExpenseHead(name=name)
    db.add(row)
    db.flush()
    log_from_auth(db, auth, action="create", entity_type="expense_head", entity_id=row.id, entity_label=name)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "name": row.name}


@router.post("/heads/{head_id}/subheads", status_code=201)
def create_expense_subhead(
    head_id: int,
    body: HeadIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    head = db.get(ExpenseHead, head_id)
    if not head:
        raise HTTPException(404, "head not found")
    name = _clean_head_name(body.name)
    taken = (
        db.query(ExpenseSubhead)
        .filter(ExpenseSubhead.head_id == head.id, func.lower(ExpenseSubhead.name) == name.lower())
        .first()
    )
    if taken:
        raise HTTPException(400, "That sub-head already exists")
    row = ExpenseSubhead(head_id=head.id, name=name)
    db.add(row)
    db.flush()
    log_from_auth(
        db, auth, action="create", entity_type="expense_subhead", entity_id=row.id,
        entity_label=f"{head.name} / {name}",
    )
    db.commit()
    db.refresh(row)
    return {"id": row.id, "name": row.name, "category": f"{head.name} / {row.name}".lower()}


@router.get("", response_model=List[ExpensePublic])
def list_expenses(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    category: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    # Was require_admin while create_expense (below) only needs finance.write —
    # a finance.write-only staffer could add an expense but not see the list
    # that immediately renders after (finance.js loadExpenses), a hard 403.
    auth: AuthContext = Depends(require_permission("finance.write")),
):
    q = db.query(Expense)
    if from_date:
        q = q.filter(Expense.expense_date >= from_date)
    if to_date:
        q = q.filter(Expense.expense_date <= to_date)
    if category:
        q = q.filter(Expense.category == category.lower())
    rows = q.order_by(Expense.expense_date.desc(), Expense.id.desc()).limit(500).all()
    return [ExpensePublic.from_row(r) for r in rows]


@router.post("", response_model=ExpensePublic, status_code=201)
def create_expense(
    body: ExpenseIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("finance.write")),
):
    category = resolve_expense_category(db, body)
    row = Expense(
        expense_date=body.expense_date,
        category=category,
        description=(body.description or "").strip() or None,
        amount=body.amount,
        reference=(body.reference or "").strip() or None,
        created_by_name=auth.actor_name,
    )
    db.add(row)
    log_from_auth(
        db,
        auth,
        action="create",
        entity_type="expense",
        entity_id=row.id,
        entity_label=row.category,
        detail=f"₹{row.amount}",
    )
    db.commit()
    db.refresh(row)
    return ExpensePublic.from_row(row)


@router.patch("/{expense_id}", response_model=ExpensePublic)
def patch_expense(
    expense_id: int,
    body: ExpenseIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("finance.write")),
):
    row = db.get(Expense, expense_id)
    if not row:
        raise HTTPException(404, "expense not found")
    if row.is_cash is False:
        raise HTTPException(400, "This cost comes from a stock journal. Void the journal to change it.")
    row.expense_date = body.expense_date
    row.category = resolve_expense_category(db, body)
    row.description = (body.description or "").strip() or None
    row.amount = body.amount
    row.reference = (body.reference or "").strip() or None
    log_from_auth(
        db,
        auth,
        action="edit",
        entity_type="expense",
        entity_id=row.id,
        entity_label=row.category,
        detail=f"₹{row.amount}",
    )
    db.commit()
    db.refresh(row)
    response_cache.invalidate("ledger")
    return ExpensePublic.from_row(row)


@router.delete("/{expense_id}", status_code=204)
def delete_expense(
    expense_id: int,
    db: Session = Depends(get_db),
    # Expense is hard-delete only (no deleted_at / recycle-bin recovery), and the
    # accountant/finance.write-only role is explicitly meant to be entry-only with no
    # delete capability. finance.write alone let that role permanently destroy an
    # expense via a direct API call even though the UI never renders a Delete button
    # for them (they're routed to the button-less showQuickEntry() screen) — matches
    # this app's "void/purge is admin-only regardless of staff permissions" rule.
    auth: AuthContext = Depends(require_admin),
):
    row = db.get(Expense, expense_id)
    if not row:
        raise HTTPException(404, "expense not found")
    if row.is_cash is False:
        raise HTTPException(400, "This cost comes from a stock journal. Void the journal to remove it.")
    if row.freight_agent_id:
        raise HTTPException(400, "cannot delete freight-linked expense")
    if row.addon_product_id:
        raise HTTPException(400, "cannot delete add-on stock expense — adjust the add-on's stock ledger instead")
    log_from_auth(
        db,
        auth,
        action="delete",
        entity_type="expense",
        entity_id=row.id,
        entity_label=row.category,
        detail=f"₹{row.amount}",
    )
    db.delete(row)
    db.commit()
