from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.db_import import load_dashboard_db
from app.serialize import model_to_json

router = APIRouter(prefix="/warehouses", tags=["warehouses"])


@router.get("")
def list_wh():
    db = load_dashboard_db()
    return [model_to_json(w) for w in db.list_warehouses()]


@router.get("/default")
def default_wh():
    db = load_dashboard_db()
    try:
        return model_to_json(db.get_default_warehouse())
    except Exception as e:
        raise HTTPException(404, str(e)) from e
