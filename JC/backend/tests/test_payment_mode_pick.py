from app.services.payment_mode_pick import resolve_payment_account


def test_a_reference_that_names_an_account_is_that_account():
    account, ref = resolve_payment_account("CASH", "NC", ["CASH", "NC", "ICICI"])
    assert account == "NC"
    assert ref == "NC"


def test_a_utr_stays_in_the_selected_account():
    account, ref = resolve_payment_account("ICICI", "UTR9981", ["CASH", "NC", "ICICI"])
    assert account == "ICICI"
    assert ref == "UTR9981"


def test_blank_reference_uses_the_selected_account():
    account, ref = resolve_payment_account("NC", "", ["CASH", "NC"])
    assert account == "NC"
    assert ref == "NC"
