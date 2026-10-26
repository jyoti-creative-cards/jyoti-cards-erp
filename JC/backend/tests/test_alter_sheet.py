"""The alter sheet replaces listed products and keeps both directions."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.catalog_alternative import CatalogAlternative
from app.models.catalog_product import CatalogProduct
from app.models.vendor import Vendor
from app.services.alter_sheet import apply_alter_rows, resolve_code


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    vendor = Vendor(business_name="Mill", phone="9000000101")
    db.add(vendor)
    db.flush()
    rows = []
    for name in ("1067 CARD", "1068 CARD", "1069 CARD", "5658 PATRIKA", "5658 PATRIKA -B"):
        row = CatalogProduct(
            our_product_id=name, vendor_id=vendor.id, vendor_product_id=name,
            year_group="2026-27", image_keys=[],
        )
        db.add(row)
        rows.append(row)
    old = CatalogProduct(
        our_product_id="5658 PATRIKA OLD YEAR", vendor_id=vendor.id, vendor_product_id="OLD",
        year_group="2015-25", image_keys=[],
    )
    db.add(old)
    db.flush()
    by_name = {p.our_product_id: p for p in rows}
    db.add(CatalogAlternative(product_id=by_name["1067 CARD"].id, alternative_product_id=by_name["1069 CARD"].id))
    db.add(CatalogAlternative(product_id=by_name["1069 CARD"].id, alternative_product_id=by_name["1067 CARD"].id))
    db.commit()
    return db, by_name


def test_plain_name_wins_when_two_current_products_share_the_number():
    db, _rows = _db()
    products = db.query(CatalogProduct).all()
    chosen = resolve_code(products, "5658")
    assert chosen.our_product_id == "5658 PATRIKA"


def test_sheet_replaces_listed_links_and_mirrors_them():
    db, rows = _db()
    apply_alter_rows(db, [("1067", ["1068"]), ("1069", ["1067"])])
    db.commit()
    pairs = {
        (a.product_id, a.alternative_product_id)
        for a in db.query(CatalogAlternative).all()
    }
    a, b, c = rows["1067 CARD"].id, rows["1068 CARD"].id, rows["1069 CARD"].id
    assert pairs == {(a, b), (b, a), (c, a), (a, c)}
