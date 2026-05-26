"""General ledger — maps to ``Dashboard/gl.py``."""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.gl_import import load_gl

router = APIRouter(tags=["accounting-gl"])


@router.get("/accounts")
def gl_accounts():
    gl = load_gl()
    return gl.list_gl_accounts()


@router.get("/trial-balance")
def gl_trial_balance():
    gl = load_gl()
    return gl.trial_balance()


@router.get("/journals")
def gl_journals(limit: int = Query(200, ge=1, le=2000)):
    gl = load_gl()
    return gl.journal_list(limit)


@router.get("/journals/{journal_id}/lines")
def gl_journal_lines(journal_id: int):
    gl = load_gl()
    return gl.journal_lines(journal_id)


@router.get("/pnl")
def gl_pnl(through: str = Query(..., description="YYYY-MM-DD")):
    gl = load_gl()
    return gl.pnl_to_date(through[:10])
