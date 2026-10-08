from decimal import Decimal

from app.services.catalog_addons import is_initial_plate, is_name_plate, merge_priced_addon_charges


def test_name_plate_match_ignores_case_and_dashes():
    assert is_name_plate("NAME-PLATE", None)
    assert is_name_plate("box", "Name Plate")
    assert not is_name_plate("envelope", "Cover")


def test_name_plate_charge_is_two_per_piece_and_other_addons_are_free():
    charges = merge_priced_addon_charges(
        [{"name": "Packing", "amount": "10"}],
        {
            1: [
                {"addon_product_id": 9, "our_product_id": "NAME PLATE", "name": "Name Plate", "quantity": 1, "selling_price": "2.00"},
                {"addon_product_id": 10, "our_product_id": "ENVELOPE", "name": "Envelope", "quantity": 1, "selling_price": "0.00"},
            ],
            2: [
                {"addon_product_id": 9, "our_product_id": "NAME PLATE", "name": "Name Plate", "quantity": 1, "selling_price": "2.00"},
            ],
        },
        [
            {"catalog_product_id": 1, "quantity": 4},
            {"catalog_product_id": 2, "quantity": 1},
        ],
    )
    by_name = {c["name"]: Decimal(c["amount"]) for c in charges}
    assert by_name["Packing"] == Decimal("10")
    assert by_name["Name Plate"] == Decimal("10.00")


def test_initial_plate_is_three_and_separate_from_name_plate():
    assert is_initial_plate("INITIAL PLATE", None)
    assert not is_initial_plate("NAME PLATE LEDGER", None)
    charges = merge_priced_addon_charges(
        [],
        {
            1: [
                {"addon_product_id": 9, "our_product_id": "NAME PLATE LEDGER", "name": "NAME PLATE LEDGER", "quantity": 1, "selling_price": "2.00"},
                {"addon_product_id": 10, "our_product_id": "INITIAL PLATE", "name": "INITIAL PLATE", "quantity": 1, "selling_price": "0"},
            ],
        },
        [{"catalog_product_id": 1, "quantity": 4}],
    )
    by_name = {c["name"]: Decimal(c["amount"]) for c in charges}
    assert by_name["Name Plate"] == Decimal("8.00")
    assert by_name["Initial Plate"] == Decimal("12.00")


def test_removed_name_plate_adds_no_charge():
    charges = merge_priced_addon_charges(
        [],
        {1: [{"addon_product_id": 10, "our_product_id": "ENVELOPE", "name": "Envelope", "quantity": 1, "selling_price": "0"}]},
        [{"catalog_product_id": 1, "quantity": 3}],
    )
    assert charges == []
