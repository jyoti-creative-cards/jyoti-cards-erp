"""PDF billing — generation lives in ``Dashboard/bill_pdf.py`` (Streamlit today)."""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/integrations/pdf", tags=["integrations-pdf"])


@router.get("/info")
def pdf_info():
    return {
        "billing_pdfs": "Built via bill_pdf.build_billing_pdfs_* from Streamlit; "
        "expose upload/download endpoints here when needed.",
        "storage": "Supabase S3-compatible bucket (same as Dashboard.storage_s3).",
    }
