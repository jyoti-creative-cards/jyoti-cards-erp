"""Expense CRUD — indirect expenses (rent, salary, electricity, misc)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import require_admin
from app.models.expense import Expense

router = APIRouter(prefix="/expenses", tags=["expenses"])

CATEGORIES = {"rent", "salary", "electricity", "transport", "misc", "other"}
PAYMENT_MODES = {"cash", "bank", "upi", "cheque"}


class ExpenseIn(BaseModel):
    expense_date: date
    category: str
    description: Optional[str] = None
    amount: Decimal
    payment_mode: str = "cash"
    reference: Optional[str] = None


class ExpensePublic(BaseModel):
    id: int
    expense_date: date
    category: str
    description: Optional[str] = None
    amount: str
    payment_mode: str
    reference: Optional[str] = None
    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_row(cls, row: Expense) -> "ExpensePublic":
        return cls(
            id=row.id,
            expense_date=row.expense_date,
            category=row.category,
            description=row.description,
            amount=format(row.amount, "f"),
            payment_mode=row.payment_mode,
            reference=row.reference,
        )


@router.get("", response_model=List[ExpensePublic], dependencies=[Depends(require_admin)])
def list_expenses(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    category: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(Expense)
    if from_date:
        q = q.filter(Expense.expense_date >= from_date)
    if to_date:
        q = q.filter(Expense.expense_date <= to_date)
    if category:
        q = q.filter(Expense.category == category.lower())
    rows = q.order_by(Expense.expense_date.desc()).limit(500).all()
    return [ExpensePublic.from_orm_row(r) for r in rows]


@router.post("", response_model=ExpensePublic, status_code=201, dependencies=[Depends(require_admin)])
def create_expense(body: ExpenseIn, db: Session = Depends(get_db)):
    cat = body.category.lower().strip()
    mode = body.payment_mode.lower().strip()
    row = Expense(
        expense_date=body.expense_date,
        category=cat,
        description=(body.description or "").strip() or None,
        amount=body.amount,
        payment_mode=mode,
        reference=(body.reference or "").strip() or None,
    )
    db.add(row); db.commit(); db.refresh(row)
    return ExpensePublic.from_orm_row(row)


@router.patch("/{expense_id}", response_model=ExpensePublic, dependencies=[Depends(require_admin)])
def update_expense(expense_id: int, body: ExpenseIn, db: Session = Depends(get_db)):
    row = db.get(Expense, expense_id)
    if not row:
        raise HTTPException(404, "expense not found")
    row.expense_date = body.expense_date
    row.category = body.category.lower().strip()
    row.description = (body.description or "").strip() or None
    row.amount = body.amount
    row.payment_mode = body.payment_mode.lower().strip()
    row.reference = (body.reference or "").strip() or None
    db.commit(); db.refresh(row)
    return ExpensePublic.from_orm_row(row)


@router.delete("/{expense_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_expense(expense_id: int, db: Session = Depends(get_db)):
    row = db.get(Expense, expense_id)
    if row:
        db.delete(row); db.commit()
