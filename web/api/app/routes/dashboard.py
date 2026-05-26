from __future__ import annotations

from fastapi import APIRouter

from app.db_import import load_dashboard_db

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard/stats")
def dashboard_stats():
    db = load_dashboard_db()
    return db.get_dashboard_stats()


@router.get("/documents/stats")
def document_stats():
    db = load_dashboard_db()
    return db.get_document_dashboard_stats()
