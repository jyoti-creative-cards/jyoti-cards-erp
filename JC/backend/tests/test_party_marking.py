"""A product marking reaches the customer bill only when show to party is on."""

from app.services.product_markings import narration_for_party


def test_hidden_marking_stays_off_the_bill():
    text = narration_for_party("18 nov 1200 ayga", [("18 nov 1200 ayga", False)])
    assert text == ""


def test_shown_marking_is_on_the_bill():
    text = narration_for_party("", [("18 nov 1200 ayga", True)])
    assert text == "18 nov 1200 ayga"


def test_other_narration_stays_when_marking_is_hidden():
    text = narration_for_party("Handle with care · 18 nov 1200 ayga", [("18 nov 1200 ayga", False)])
    assert text == "Handle with care"
