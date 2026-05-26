"""Accounting: GL + AR/AP under ``/api/v1/accounting``."""
from __future__ import annotations

from fastapi import APIRouter

from app.routes.accounting.ar_ap import router as ar_ap_router
from app.routes.accounting.gl import router as gl_router

router = APIRouter(prefix="/accounting", tags=["accounting"])
router.include_router(gl_router, prefix="/gl")
router.include_router(ar_ap_router)
