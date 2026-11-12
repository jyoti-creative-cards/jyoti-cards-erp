from app.services.our_catalogs.core import catalog_name_for_bill_sku


def test_spacing_variants_land_on_the_category_catalog():
    assert catalog_name_for_bill_sku("2027 ALBUM NO. 01") == "2027 ALBUM NO. 01"
    assert catalog_name_for_bill_sku("2027 ALBUM NO.01") == "2027 ALBUM NO. 01"
    assert catalog_name_for_bill_sku("2027 ALBUM NO.05") == "2027 ALBUM NO. 05"
    assert catalog_name_for_bill_sku("2027 album no.123") == "2027 ALBUM NO. 123"
    assert catalog_name_for_bill_sku("2027 BOX NO.09") == "2027 BOX NO. 09"
    assert catalog_name_for_bill_sku("BP ALBUM 2027") == "BP ALBUM 2027"
    assert catalog_name_for_bill_sku("BP+SC ALBUM 2027") == "BP+SC ALBUM 2027"


def test_album_category_is_the_catalogue():
    from app.services.our_catalogs.core import catalog_name_for_categories
    assert catalog_name_for_categories("ENVELOPE ALBUM", "", "", "5441 PATRIKA") == "2027 ENVELOPE ALBUM"
    assert catalog_name_for_categories("BP ALBUM", "", "", "1001 CARD") == "BP ALBUM 2027"
    assert catalog_name_for_categories("", "BP+SC ALBUM", "", "1002") == "BP+SC ALBUM 2027"
    assert catalog_name_for_categories("LOOSE", "", "", "5441 PATRIKA") is None
    assert catalog_name_for_bill_sku("2027 box no 08 mix") is None
    assert catalog_name_for_bill_sku("2027 PP (ASHOKA)") is None
    assert catalog_name_for_bill_sku("2026 BOX LOOSE SAMPLES") is None
    assert catalog_name_for_bill_sku("2027 FANCY ENVELOPE NO.06") is None
