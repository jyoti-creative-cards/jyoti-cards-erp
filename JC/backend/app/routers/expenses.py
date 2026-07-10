from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import AuthContext, require_admin
from app.models.expense import Expense

router = APIRouter(prefix="/expenses", tags=["expenses"])


class ExpenseIn(BaseModel):
    expense_date: date
    category: str
    description: Optional[str] = None
    amount: Decimal
    reference: Optional[str] = None


class ExpensePublic(BaseModel):
    id: int
    expense_date: date
    category: str
    description: Optional[str] = None
    amount: str
    reference: Optional[str] = None
    freight_agent_id: Optional[int] = None
    created_by_name: str

    @classmethod
    def from_row(cls, row: Expense) -> "ExpensePublic":
        return cls(
            id=row.id,
            expense_date=row.expense_date,
            category=row.category,
            description=row.description,
            amount=format(row.amount, "f"),
            reference=row.reference,
            freight_agent_id=row.freight_agent_id,
            created_by_name=row.created_by_name,
        )


@router.get("", response_model=List[ExpensePublic])
def list_expenses(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    category: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
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
def create_expense(body: ExpenseIn, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)):
    row = Expense(
        expense_date=body.expense_date,
        category=body.category.lower().strip(),
        description=(body.description or "").strip() or None,
        amount=body.amount,
        reference=(body.reference or "").strip() or None,
        created_by_name=auth.actor_name,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return ExpensePublic.from_row(row)


@router.delete("/{expense_id}", status_code=204)
def delete_expense(expense_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)):
    row = db.get(Expense, expense_id)
    if not row:
        raise HTTPException(404, "expense not found")
    if row.freight_agent_id:
        raise HTTPException(400, "cannot delete freight-linked expense")
    db.delete(row)
    db.commit()
