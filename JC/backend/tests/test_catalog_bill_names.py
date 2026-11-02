from app.services.our_catalogs.core import catalog_name_for_bill_sku


def test_spacing_variants_land_on_the_category_catalog():
    assert catalog_name_for_bill_sku("2027 ALBUM NO. 01") == "2027 ALBUM NO. 01"
    assert catalog_name_for_bill_sku("2027 ALBUM NO.01") == "2027 ALBUM NO. 01"
    assert catalog_name_for_bill_sku("2027 ALBUM NO.05") == "2027 ALBUM NO. 05"
    assert catalog_name_for_bill_sku("2027 album no.123") == "2027 ALBUM NO. 123"
    assert catalog_name_for_bill_sku("2027 BOX NO.09") == "2027 BOX NO. 09"
    assert catalog_name_for_bill_sku("BP ALBUM 2027") == "BP ALBUM 2027"
    assert catalog_name_for_bill_sku("BP+SC ALBUM 2027") == "BP+SC ALBUM 2027"


def test_loose_samples_are_not_catalogs():
    assert catalog_name_for_bill_sku("2027 box no 08 mix") is None
    assert catalog_name_for_bill_sku("2027 PP (ASHOKA)") is None
    assert catalog_name_for_bill_sku("2026 BOX LOOSE SAMPLES") is None
    assert catalog_name_for_bill_sku("2027 FANCY ENVELOPE NO.06") is None
