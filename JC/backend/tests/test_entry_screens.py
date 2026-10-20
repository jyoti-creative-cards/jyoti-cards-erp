"""Order and bill entry load their lists in one call."""
from app.main import app


def test_entry_lists_are_on_the_api():
    spec = app.openapi()
    assert "/api/v1/customers/entry-parties" in spec["paths"]
    assert "/api/v1/stock/entry-items" in spec["paths"]
    freight = spec["paths"]["/api/v1/freight-agents"]["get"]
    names = [p["name"] for p in freight.get("parameters") or []]
    assert "names_only" in names
