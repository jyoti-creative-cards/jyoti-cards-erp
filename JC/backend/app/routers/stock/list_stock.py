from __future__ import annotations
"""Split from app/routers/stock.py."""

from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import and_, case, func, or_, text
from sqlalchemy.orm import Session, aliased

from app.db.session import get_db
from app.deps import AuthContext, get_auth_context, require_admin, require_any_permission, require_permission
from app.models.addon_product import AddonProduct
from app.models.catalog_alternative import CatalogAlternative
from app.models.catalog_addon_link import CatalogAddonLink
from app.models.catalog_product import CatalogProduct
from app.models.city import City
from app.models.stock import StockBalance, StockLedger, StockReceipt, StockReceiptLine
from app.models.vendor import Vendor
from app.schemas.stock import (
    BillPreviewIn,
    BillPreviewOut,
    BulkSellingPriceIn,
    PendingBillReceipt,
    PlacedLineForReceipt,
    ReceiptForBillDetail,
    ReceiptLineForBill,
    ReservedByPartyRow,
    SellingPriceUpdate,
    StockAdjustIn,
    StockThresholdUpdate,
    StockLedgerEntry,
    StockBrowsePage,
    StockProductDetail,
    StockProductSummary,
    VendorBillIn,
    VendorPendingBillList,
    VendorPlacedOrderForReceipt,
    VendorReceiptCreate,
    VendorReceiveCreate,
    OfflineVendorReceiptCreate,
    VoidIn,
)
from app.services.cost_visibility import can_see_cost, hide_cost
from app.services.pricing import coerce_selling_price, effective_selling_price
from app.services.stock_levels import admin_stock_status_label
from app.schemas.ledger import StockLedgerDetail
from app.models.debit_note import DebitNote
from app.services.ap_ledger import debit_note_payable_effect, receipt_bill_amount, receipt_debit_note_total
from app.services.activity import log_from_auth
from app.services.order_summary import pending_qty_by_product, placed_qty_by_product, received_qty_by_product, reserved_by_party
from app.services.stock_receipt import get_open_order
from app.services.doc_gen import generate_vendor_receipt_document
from app.services import response_cache
from app.services.history import list_entity_history
from app.services.document_present import present
from app.services.receipt_edit import update_vendor_receipt
from app.services.vendor_receive_bill import (
    bill_receipt,
    preview_bill_deviations,
    receive_vendor_goods,
)
from app.services.storage import bill_key, presigned_url, presigned_urls, storage_configured, upload_bytes, vendor_folder_slug
from app.services.void_service import void_receipt

from app.routers.stock.router import router


def _attach_priced_addons(db: Session, rows: list) -> None:
    if not rows:
        return
    from app.services.catalog_addons import addon_snapshots_map, priced_addons_by_product

    ids = [int(r.catalog_product_id) for r in rows]
    all_addons = addon_snapshots_map(db, ids)
    priced = priced_addons_by_product(db, ids)
    for row in rows:
        pid = int(row.catalog_product_id)
        row.addons = all_addons.get(pid, [])
        row.priced_addons = priced.get(pid, [])


@router.get("/products", response_model=List[StockProductSummary])
def list_stock(
    db: Session = Depends(get_db),
    search: Optional[str] = Query(None),
    year_group: Optional[str] = Query(None),
    lite: bool = Query(False, description="Skip images for faster pickers"),
    limit: Optional[int] = Query(None, ge=1, le=100),
    auth: AuthContext = Depends(require_permission("stock.read")),
):
    yg = (year_group or "").replace("\x00", "").strip()
    cache_key = (
        f"stock:products:v6:{(search or '').replace(chr(0), '')}:{yg}:{int(lite)}:"
        f"lim={limit or 0}:cost={int(can_see_cost(auth))}"
    )
    cached = response_cache.get(cache_key)
    if cached is not None:
        return cached

    search_clean_early = (search or "").replace("\x00", "").strip()
    if db.get_bind().dialect.name == "sqlite":
        out = _list_stock_sqlite(db, search_clean_early, yg, lite, limit, auth)
        if lite:
            _attach_priced_addons(db, out)
        response_cache.set(cache_key, out, 25.0)
        return out

    params: dict = {}
    search_sql = ""
    year_sql = ""
    # Postgres rejects NUL bytes in text params (client search paste / bad URL)
    search_clean = (search or "").replace("\x00", "").strip()
    if search_clean:
        search_sql = """
          AND (
            lower(p.our_product_id) LIKE :search
            OR lower(COALESCE(p.vendor_product_id, '')) LIKE :search
            OR lower(COALESCE(p.category, '')) LIKE :search
            OR lower(COALESCE(p.second_category, '')) LIKE :search
            OR lower(COALESCE(p.category_3, '')) LIKE :search
            OR lower(COALESCE(p.series, '')) LIKE :search
            OR lower(COALESCE(p.year_group, '')) LIKE :search
            OR lower(COALESCE(v.business_name, '')) LIKE :search
            OR lower(COALESCE(c.name, '')) LIKE :search
          )
        """
        params["search"] = f"%{search_clean.lower()}%"
    if yg:
        year_sql = " AND p.year_group = :year_group "
        params["year_group"] = yg
    limit_sql = ""
    if limit is not None:
        params["lim"] = int(limit)
        limit_sql = " LIMIT :lim "
    if lite:
        image_select = "NULL AS image_key"
        addon_select = "0 AS addon_count"
        addon_join = ""
        alt_select = "0 AS alt_count"
        alt_join = ""
    else:
        image_select = "p.image_keys->>0 AS image_key"
        addon_select = "COALESCE(ac.cnt, 0) AS addon_count"
        addon_join = """
            LEFT JOIN (
              SELECT catalog_product_id, COUNT(*)::int AS cnt
              FROM jc_catalog_addon_links
              GROUP BY catalog_product_id
            ) ac ON ac.catalog_product_id = p.id
        """
        alt_select = "COALESCE(alt.cnt, 0) AS alt_count"
        alt_join = """
            LEFT JOIN (
              SELECT product_id, COUNT(*)::int AS cnt
              FROM jc_catalog_alternatives
              GROUP BY product_id
            ) alt ON alt.product_id = p.id
        """

    rows = db.execute(
        text(
            f"""
            SELECT
              p.id AS catalog_product_id,
              p.our_product_id,
              p.vendor_product_id,
              p.vendor_id,
              p.category,
              p.second_category,
              p.category_3,
              p.series,
              p.year_group,
              p.marking,
              p.selling_price,
              p.buying_price,
              p.unit,
              {image_select},
              COALESCE(sb.quantity_on_hand, 0) AS quantity_on_hand,
              COALESCE(sb.low_stock_threshold, 5) AS low_stock_threshold,
              v.business_name AS vendor_name,
              c.name AS vendor_city,
              {addon_select},
              {alt_select}
            FROM jc_catalog_products p
            LEFT JOIN jc_stock_balances sb ON sb.catalog_product_id = p.id
            LEFT JOIN jc_vendors v ON v.id = p.vendor_id
            LEFT JOIN jc_cities c ON c.id = v.city_id
            {addon_join}
            {alt_join}
            WHERE p.is_active IS TRUE
              AND p.deleted_at IS NULL
              {search_sql}
              {year_sql}
            ORDER BY p.our_product_id ASC, COALESCE(p.year_group, '') ASC, p.id ASC
            {limit_sql}
            """
        ),
        params,
    ).mappings().all()

    out: list[StockProductSummary] = []
    for r in rows:
        qty = int(r["quantity_on_hand"] or 0)
        th = int(r["low_stock_threshold"] or 5)
        vn = r["vendor_name"]
        city_name = r["vendor_city"]
        label = f"{vn} — {city_name}" if vn and city_name else (vn or "")
        image_urls = []
        out.append(
            StockProductSummary(
                catalog_product_id=int(r["catalog_product_id"]),
                our_product_id=r["our_product_id"],
                vendor_product_id=r["vendor_product_id"],
                vendor_id=int(r["vendor_id"]),
                vendor_name=vn,
                vendor_city=city_name,
                vendor_label=label,
                category=r["category"],
                second_category=r["second_category"],
                category_3=r["category_3"],
                series=r["series"],
                year_group=r["year_group"],
                marking=r["marking"],
                quantity_on_hand=qty,
                low_stock_threshold=th,
                stock_status=admin_stock_status_label(qty, th),
                selling_price=(
                    format(eff, "f")
                    if (eff := effective_selling_price(r["buying_price"], r["selling_price"])) is not None
                    else None
                ),
                buying_price=hide_cost(format(r["buying_price"], "f") if r["buying_price"] is not None else None, auth),
                unit=r["unit"],
                image_urls=image_urls,
                addon_count=int(r["addon_count"] or 0),
                alt_count=int(r["alt_count"] or 0),
            )
        )
    if lite:
        _attach_priced_addons(db, out)
    response_cache.set(cache_key, out, 25.0)
    return out


@router.get("/entry-items")
def entry_items(
    q: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_any_permission("customer_orders.read", "customer_orders.write", "stock.read")),
) -> list[dict]:
    """Item numbers for the order form. A query returns a short match list."""
    needle = (q or "").replace("\x00", "").strip()
    if needle:
        like = f"%{needle.lower()}%"
        prefix = f"{needle.lower()}%"
        rows = (
            db.query(CatalogProduct, StockBalance.quantity_on_hand)
            .outerjoin(StockBalance, StockBalance.catalog_product_id == CatalogProduct.id)
            .filter(
                CatalogProduct.is_active.is_(True),
                CatalogProduct.deleted_at.is_(None),
                func.lower(CatalogProduct.our_product_id).like(like),
            )
            .order_by(
                case((func.lower(CatalogProduct.our_product_id).like(prefix), 0), else_=1),
                CatalogProduct.our_product_id.asc(),
                CatalogProduct.id.asc(),
            )
            .limit(12)
            .all()
        )
        out = []
        for product, qty in rows:
            price = effective_selling_price(product.buying_price, product.selling_price)
            out.append({
                "catalog_product_id": product.id,
                "our_product_id": product.our_product_id,
                "year_group": product.year_group,
                "selling_price": format(price, "f") if price is not None else None,
                "quantity_on_hand": int(qty or 0),
                "addons": [],
                "priced_addons": [],
            })
        return out
    cached = response_cache.get("stock:entry-items:v1")
    if cached is not None:
        return cached
    from app.services.catalog_addons import addon_snapshots_map

    rows = (
        db.query(CatalogProduct, StockBalance.quantity_on_hand)
        .outerjoin(StockBalance, StockBalance.catalog_product_id == CatalogProduct.id)
        .filter(CatalogProduct.is_active.is_(True), CatalogProduct.deleted_at.is_(None))
        .order_by(CatalogProduct.our_product_id.asc(), CatalogProduct.id.asc())
        .all()
    )
    ids = [product.id for product, _qty in rows]
    addons = addon_snapshots_map(db, ids, with_images=False)
    out = []
    for product, qty in rows:
        price = effective_selling_price(product.buying_price, product.selling_price)
        extra = addons.get(product.id) or []
        out.append({
            "catalog_product_id": product.id,
            "our_product_id": product.our_product_id,
            "year_group": product.year_group,
            "selling_price": format(price, "f") if price is not None else None,
            "quantity_on_hand": int(qty or 0),
            "addons": extra,
            "priced_addons": [a for a in extra if float(a.get("selling_price") or 0) > 0],
        })
    response_cache.set("stock:entry-items:v1", out, 60.0)
    return out


def _list_stock_sqlite(
    db: Session,
    search_clean: str,
    year_group: str,
    lite: bool,
    limit: Optional[int],
    auth: AuthContext,
) -> list[StockProductSummary]:
    """Postgres list SQL uses ::int and jsonb. Local sqlite uses this ORM path."""
    q = (
        db.query(CatalogProduct, StockBalance, Vendor, City)
        .outerjoin(StockBalance, StockBalance.catalog_product_id == CatalogProduct.id)
        .outerjoin(Vendor, Vendor.id == CatalogProduct.vendor_id)
        .outerjoin(City, City.id == Vendor.city_id)
        .filter(CatalogProduct.is_active.is_(True), CatalogProduct.deleted_at.is_(None))
    )
    if year_group:
        q = q.filter(CatalogProduct.year_group == year_group)
    if search_clean:
        like = f"%{search_clean.lower().replace('%', '').replace('_', '')}%"
        q = q.filter(
            or_(
                func.lower(CatalogProduct.our_product_id).like(like),
                func.lower(func.coalesce(CatalogProduct.vendor_product_id, "")).like(like),
                func.lower(func.coalesce(CatalogProduct.category, "")).like(like),
                func.lower(func.coalesce(CatalogProduct.second_category, "")).like(like),
                func.lower(func.coalesce(CatalogProduct.category_3, "")).like(like),
                func.lower(func.coalesce(CatalogProduct.series, "")).like(like),
                func.lower(func.coalesce(CatalogProduct.year_group, "")).like(like),
                func.lower(func.coalesce(Vendor.business_name, "")).like(like),
                func.lower(func.coalesce(City.name, "")).like(like),
            )
        )
    q = q.order_by(CatalogProduct.our_product_id.asc(), CatalogProduct.id.asc())
    if limit:
        q = q.limit(int(limit))
    out: list[StockProductSummary] = []
    for product, balance, vendor, city in q.all():
        qty = int(balance.quantity_on_hand) if balance else 0
        th = int(balance.low_stock_threshold) if balance else 5
        vn = vendor.business_name if vendor else ""
        city_name = city.name if city else None
        label = f"{vn} — {city_name}" if vn and city_name else (vn or "")
        image_urls = []
        out.append(
            StockProductSummary(
                catalog_product_id=product.id,
                our_product_id=product.our_product_id,
                vendor_product_id=product.vendor_product_id,
                vendor_id=product.vendor_id,
                vendor_name=vn,
                vendor_city=city_name,
                vendor_label=label,
                category=product.category,
                second_category=product.second_category,
                category_3=product.category_3,
                series=product.series,
                year_group=product.year_group,
                marking=product.marking,
                quantity_on_hand=qty,
                low_stock_threshold=th,
                stock_status=admin_stock_status_label(qty, th),
                selling_price=(
                    format(eff, "f")
                    if (eff := effective_selling_price(product.buying_price, product.selling_price)) is not None
                    else None
                ),
                buying_price=hide_cost(
                    format(product.buying_price, "f") if product.buying_price is not None else None,
                    auth,
                ),
                unit=product.unit,
                image_urls=image_urls,
                addon_count=0,
                alt_count=0,
            )
        )
    return out


def _active_addon_counts(db: Session):
    return (
        db.query(
            CatalogAddonLink.catalog_product_id.label("pid"),
            func.count(CatalogAddonLink.id).label("cnt"),
        )
        .join(AddonProduct, AddonProduct.id == CatalogAddonLink.addon_product_id)
        .filter(AddonProduct.is_active.is_(True), AddonProduct.deleted_at.is_(None))
        .group_by(CatalogAddonLink.catalog_product_id)
        .subquery()
    )


def _stock_scope(db: Session, search: str, year_group: str):
    addon_counts = _active_addon_counts(db)
    qty = func.coalesce(StockBalance.quantity_on_hand, 0)
    addon_count = func.coalesce(addon_counts.c.cnt, 0)
    q = (
        db.query(CatalogProduct, StockBalance, Vendor, City, addon_count)
        .outerjoin(StockBalance, StockBalance.catalog_product_id == CatalogProduct.id)
        .outerjoin(Vendor, Vendor.id == CatalogProduct.vendor_id)
        .outerjoin(City, City.id == Vendor.city_id)
        .outerjoin(addon_counts, addon_counts.c.pid == CatalogProduct.id)
        .filter(CatalogProduct.is_active.is_(True), CatalogProduct.deleted_at.is_(None))
    )
    if year_group:
        q = q.filter(CatalogProduct.year_group == year_group)
    if search:
        like = f"%{search.lower()}%"
        q = q.filter(or_(
            func.lower(CatalogProduct.our_product_id).like(like),
            func.lower(func.coalesce(CatalogProduct.vendor_product_id, "")).like(like),
            func.lower(func.coalesce(CatalogProduct.category, "")).like(like),
            func.lower(func.coalesce(CatalogProduct.second_category, "")).like(like),
            func.lower(func.coalesce(CatalogProduct.category_3, "")).like(like),
            func.lower(func.coalesce(CatalogProduct.series, "")).like(like),
            func.lower(func.coalesce(CatalogProduct.year_group, "")).like(like),
            func.lower(func.coalesce(Vendor.business_name, "")).like(like),
            func.lower(func.coalesce(City.name, "")).like(like),
            CatalogProduct.id.in_(_alternative_match_ids(db, like)),
        ))
    return q, qty, addon_count


def _apply_stock_filters(
    q,
    *,
    vendor_id: Optional[int],
    category: Optional[str],
    price_min: Optional[Decimal],
    price_max: Optional[Decimal],
    stock_status: Optional[str],
    no_sell_price: bool,
    no_addons: bool,
    no_alternatives: bool,
    addon_count,
    qty,
    db: Session,
):
    if vendor_id:
        q = q.filter(CatalogProduct.vendor_id == vendor_id)
    if category:
        q = q.filter(or_(
            CatalogProduct.category == category,
            CatalogProduct.second_category == category,
            CatalogProduct.category_3 == category,
        ))
    price = func.coalesce(CatalogProduct.selling_price, CatalogProduct.buying_price)
    if price_min is not None:
        q = q.filter(price >= price_min)
    if price_max is not None:
        q = q.filter(price <= price_max)
    th = func.coalesce(StockBalance.low_stock_threshold, 5)
    floor = case((th < 1, 1), else_=th)
    if stock_status == "negative_stock":
        q = q.filter(qty < 0)
    elif stock_status == "out_of_stock":
        q = q.filter(qty == 0)
    elif stock_status == "low_stock":
        q = q.filter(and_(qty > 0, qty < floor))
    elif stock_status == "in_stock":
        q = q.filter(qty >= floor)
    if no_sell_price:
        q = q.filter(or_(
            CatalogProduct.selling_price.is_(None),
            CatalogProduct.selling_price == CatalogProduct.buying_price,
        ))
    if no_addons:
        q = q.filter(addon_count == 0)
    if no_alternatives:
        q = q.filter(~CatalogProduct.id.in_(_products_with_alternatives(db)))
    return q


def _products_with_alternatives(db: Session):
    alt_target = aliased(CatalogProduct)
    return (
        db.query(CatalogAlternative.product_id)
        .join(alt_target, alt_target.id == CatalogAlternative.alternative_product_id)
        .filter(alt_target.is_active.is_(True), alt_target.deleted_at.is_(None))
        .distinct()
    )


def _alternative_match_ids(db: Session, like: str):
    alt_target = aliased(CatalogProduct)
    return (
        db.query(CatalogAlternative.product_id)
        .join(alt_target, alt_target.id == CatalogAlternative.alternative_product_id)
        .filter(
            alt_target.is_active.is_(True),
            alt_target.deleted_at.is_(None),
            func.lower(alt_target.our_product_id).like(like),
        )
        .distinct()
    )


def browse_stock(
    db: Session,
    auth: AuthContext,
    *,
    search: Optional[str] = None,
    year_group: Optional[str] = None,
    vendor_id: Optional[int] = None,
    category: Optional[str] = None,
    price_min: Optional[Decimal] = None,
    price_max: Optional[Decimal] = None,
    stock_status: Optional[str] = None,
    no_sell_price: bool = False,
    no_addons: bool = False,
    no_alternatives: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> StockBrowsePage:
    """One page of the stock hub, plus totals for the whole search."""
    search_clean = (search or "").replace("\x00", "").strip()
    year_clean = (year_group or "").replace("\x00", "").strip()
    scope, qty, addon_count = _stock_scope(db, search_clean, year_clean)
    th = func.coalesce(StockBalance.low_stock_threshold, 5)
    floor = case((th < 1, 1), else_=th)
    no_sell = or_(
        CatalogProduct.selling_price.is_(None),
        CatalogProduct.selling_price == CatalogProduct.buying_price,
    )
    counted = scope.order_by(None).with_entities(
        func.count(CatalogProduct.id),
        func.coalesce(func.sum(qty), 0),
        func.coalesce(func.sum(case((qty < 0, 1), else_=0)), 0),
        func.coalesce(func.sum(case((qty == 0, 1), else_=0)), 0),
        func.coalesce(func.sum(case((and_(qty > 0, qty < floor), 1), else_=0)), 0),
        func.coalesce(func.sum(case((no_sell, 1), else_=0)), 0),
        func.coalesce(func.sum(case((addon_count == 0, 1), else_=0)), 0),
    ).one()
    all_count, units, negative, out_of, low, missing_sell, missing_addons = counted
    missing_alts = (
        scope.filter(~CatalogProduct.id.in_(_products_with_alternatives(db)))
        .order_by(None)
        .with_entities(func.count(CatalogProduct.id))
        .scalar()
    )
    filtered, _qty, filtered_addon = _stock_scope(db, search_clean, year_clean)
    filtered = _apply_stock_filters(
        filtered,
        vendor_id=vendor_id,
        category=category,
        price_min=price_min,
        price_max=price_max,
        stock_status=stock_status,
        no_sell_price=no_sell_price,
        no_addons=no_addons,
        no_alternatives=no_alternatives,
        addon_count=filtered_addon,
        qty=_qty,
        db=db,
    )
    total = filtered.order_by(None).with_entities(func.count(CatalogProduct.id)).scalar() or 0
    rows = (
        filtered.order_by(CatalogProduct.our_product_id.asc(), CatalogProduct.id.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    page_ids = [product.id for product, _balance, _vendor, _city, _addons in rows]
    alt_counts: dict[int, int] = {}
    if page_ids:
        alt_target = aliased(CatalogProduct)
        for pid, cnt in (
            db.query(CatalogAlternative.product_id, func.count(CatalogAlternative.id))
            .join(alt_target, alt_target.id == CatalogAlternative.alternative_product_id)
            .filter(
                CatalogAlternative.product_id.in_(page_ids),
                alt_target.is_active.is_(True),
                alt_target.deleted_at.is_(None),
            )
            .group_by(CatalogAlternative.product_id)
            .all()
        ):
            alt_counts[int(pid)] = int(cnt)
    items: list[StockProductSummary] = []
    for product, balance, vendor, city, addons in rows:
        on_hand = int(balance.quantity_on_hand) if balance else 0
        threshold = int(balance.low_stock_threshold) if balance else 5
        vendor_name = vendor.business_name if vendor else ""
        city_name = city.name if city else None
        label = f"{vendor_name} — {city_name}" if vendor_name and city_name else (vendor_name or "")
        items.append(StockProductSummary(
            catalog_product_id=product.id,
            our_product_id=product.our_product_id,
            vendor_product_id=product.vendor_product_id,
            vendor_id=product.vendor_id,
            vendor_name=vendor_name,
            vendor_city=city_name,
            vendor_label=label,
            category=product.category,
            second_category=product.second_category,
            category_3=product.category_3,
            series=product.series,
            year_group=product.year_group,
            marking=product.marking,
            quantity_on_hand=on_hand,
            low_stock_threshold=threshold,
            stock_status=admin_stock_status_label(on_hand, threshold),
            selling_price=(
                format(eff, "f")
                if (eff := effective_selling_price(product.buying_price, product.selling_price)) is not None
                else None
            ),
            buying_price=hide_cost(
                format(product.buying_price, "f") if product.buying_price is not None else None,
                auth,
            ),
            unit=product.unit,
            image_urls=[],
            addon_count=int(addons or 0),
            alt_count=alt_counts.get(product.id, 0),
        ))
    return StockBrowsePage(
        items=items,
        total=int(total),
        units_on_hand=int(units or 0),
        counts={
            "all": int(all_count or 0),
            "low_stock": int(low or 0),
            "out_of_stock": int(out_of or 0),
            "negative_stock": int(negative or 0),
            "no_sell": int(missing_sell or 0),
            "no_addons": int(missing_addons or 0),
            "no_alternatives": int(missing_alts or 0),
        },
    )


@router.get("/products/page", response_model=StockBrowsePage)
def browse_stock_products(
    db: Session = Depends(get_db),
    search: Optional[str] = Query(None),
    year_group: Optional[str] = Query(None),
    vendor_id: Optional[int] = Query(None),
    category: Optional[str] = Query(None),
    price_min: Optional[Decimal] = Query(None, ge=0),
    price_max: Optional[Decimal] = Query(None, ge=0),
    stock_status: Optional[str] = Query(None),
    no_sell_price: bool = Query(False),
    no_addons: bool = Query(False),
    no_alternatives: bool = Query(False),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(require_permission("stock.read")),
) -> StockBrowsePage:
    cache_key = (
        f"stock:page:v1:{(search or '').replace(chr(0), '')}:{(year_group or '').replace(chr(0), '')}:"
        f"{vendor_id or ''}:{category or ''}:{price_min}:{price_max}:{stock_status or ''}:"
        f"{int(no_sell_price)}:{int(no_addons)}:{int(no_alternatives)}:{limit}:{offset}:cost={int(can_see_cost(auth))}"
    )
    cached = response_cache.get(cache_key)
    if cached is not None:
        return cached
    page = browse_stock(
        db, auth,
        search=search, year_group=year_group, vendor_id=vendor_id, category=category,
        price_min=price_min, price_max=price_max, stock_status=stock_status,
        no_sell_price=no_sell_price, no_addons=no_addons, no_alternatives=no_alternatives,
        limit=limit, offset=offset,
    )
    dumped = page.model_dump()
    response_cache.set(cache_key, dumped, 25.0)
    return page

