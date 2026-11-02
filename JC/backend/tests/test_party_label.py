from app.services.party_label import format_party_label


def test_party_label_includes_markings():
    assert format_party_label("Sharma", "Dewas", "Cash", "Genuine") == "Sharma — Dewas · Cash Genuine"


def test_party_label_without_city_or_marks():
    assert format_party_label("Sharma") == "Sharma"
