from app.services.reports.pdfs import statement_pdf_filename


def test_statement_pdf_name_uses_party_and_dates():
    name = statement_pdf_filename(
        "Meet Printing Press",
        [
            {"value_date": "2026-10-28"},
            {"created_at": "2026-10-30T10:00:00+00:00"},
        ],
    )
    assert name.startswith("meet_printing_press_28_10_2026_to_")
    assert name.endswith(".pdf")
    assert "to_" in name
