from __future__ import annotations
"""Split from app/routers/stock.py."""

from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import func, or_, text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import AuthContext, get_auth_context, require_admin, require_permission
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
        f"stock:products:v4:{(search or '').replace(chr(0), '')}:{yg}:{int(lite)}:"
        f"lim={limit or 0}:cost={int(can_see_cost(auth))}"
    )
    cached = response_cache.get(cache_key)
    if cached is not None:
        return cached

    search_clean_early = (search or "").replace("\x00", "").strip()
    if db.get_bind().dialect.name == "sqlite":
        out = _list_stock_sqlite(db, search_clean_early, yg, lite, limit, auth)
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
        image_key = r["image_key"]
        image_urls = [url] if image_key and (url := presigned_url(image_key)) else []
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
    response_cache.set(cache_key, out, 25.0)
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
        keys = [] if lite else ((product.image_keys or [])[:1])
        image_urls = presigned_urls(keys) if keys else []
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

