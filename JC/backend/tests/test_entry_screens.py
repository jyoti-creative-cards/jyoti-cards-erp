"""Order and bill entry load their lists in one call."""
from datetime import datetime, timezone

from app.main import app
from app.services.report_pdfs import _pdf_day


def test_entry_lists_are_on_the_api():
    spec = app.openapi()
    assert "/api/v1/customers/entry-parties" in spec["paths"]
    assert "/api/v1/stock/entry-items" in spec["paths"]
    freight = spec["paths"]["/api/v1/freight-agents"]["get"]
    names = [p["name"] for p in freight.get("parameters") or []]
    assert "names_only" in names


def test_statement_date_accepts_a_timestamp():
    assert _pdf_day(datetime(2026, 10, 20, 5, 30, tzinfo=timezone.utc)) == "2026-10-20"
    assert _pdf_day(None) == ""
    assert _pdf_day("2026-10-20T00:00:00") == "2026-10-20"
