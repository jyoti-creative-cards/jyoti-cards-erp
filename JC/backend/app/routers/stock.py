from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import AuthContext, get_auth_context
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
    SellingPriceUpdate,
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
)
from app.services.pricing import coerce_selling_price, effective_selling_price
from app.services.stock_levels import stock_status_label
from app.schemas.ledger import StockLedgerDetail
from app.models.debit_note import DebitNote
from app.services.ap_ledger import debit_note_payable_effect, receipt_bill_amount, receipt_debit_note_total
from app.services.activity import log_from_auth
from app.services.order_summary import pending_qty_by_product, placed_qty_by_product, received_qty_by_product
from app.services.stock_receipt import get_open_order
from app.services.doc_gen import generate_vendor_receipt_document
from app.services import response_cache
from app.services.history import list_entity_history
from app.services.receipt_edit import update_vendor_receipt
from app.services.vendor_receive_bill import (
    bill_receipt,
    preview_bill_deviations,
    receive_vendor_goods,
)
from app.services.storage import bill_key, presigned_url, presigned_urls, storage_configured, upload_bytes, vendor_folder_slug

router = APIRouter(prefix="/stock", tags=["stock"])


def _vendor_label(vendor: Vendor, city_name: Optional[str]) -> str:
    city = city_name or ""
    return f"{vendor.business_name} — {city}" if city else vendor.business_name


def _vendor_city(db: Session, vendor: Vendor) -> Optional[str]:
    if not vendor.city_id:
        return None
    city = db.get(City, vendor.city_id)
    return city.name if city else None


def _product_public(
    row: CatalogProduct,
    db: Session,
    balance: int = 0,
    threshold: int = 5,
    *,
    addon_count: Optional[int] = None,
    alt_count: Optional[int] = None,
    vendor_name: Optional[str] = None,
    vendor_city: Optional[str] = None,
    max_images: Optional[int] = None,
) -> dict:
    if vendor_name is None and vendor_city is None:
        vendor = db.get(Vendor, row.vendor_id)
        city_name = _vendor_city(db, vendor) if vendor else None
        vn = vendor.business_name if vendor else None
    else:
        vn, city_name = vendor_name, vendor_city
    label = f"{vn} — {city_name}" if vn and city_name else (vn or "")
    keys = list(row.image_keys or [])
    if max_images is not None:
        keys = keys[: max(0, max_images)]
    if addon_count is None:
        addon_count = db.query(CatalogAddonLink).filter(CatalogAddonLink.catalog_product_id == row.id).count()
    if alt_count is None:
        alt_count = db.query(CatalogAlternative).filter(CatalogAlternative.product_id == row.id).count()
    return {
        "catalog_product_id": row.id,
        "our_product_id": row.our_product_id,
        "vendor_product_id": row.vendor_product_id,
        "vendor_id": row.vendor_id,
        "vendor_name": vn,
        "vendor_city": city_name,
        "vendor_label": label,
        "category": row.category,
        "series": row.series,
        "year_group": row.year_group,
        "quantity_on_hand": balance,
        "low_stock_threshold": threshold,
        "stock_status": stock_status_label(balance, threshold),
        "selling_price": (
            format(eff, "f")
            if (eff := effective_selling_price(row.buying_price, row.selling_price)) is not None
            else None
        ),
        "buying_price": format(row.buying_price, "f") if row.buying_price is not None else None,
        "unit": row.unit,
        "image_urls": presigned_urls(keys),
        "addon_count": int(addon_count or 0),
        "alt_count": int(alt_count or 0),
    }


def _vendor_map(db: Session, vendor_ids: list[int]) -> dict[int, tuple[Optional[str], Optional[str]]]:
    ids = sorted({int(v) for v in vendor_ids if v})
    if not ids:
        return {}
    vendors = db.query(Vendor).filter(Vendor.id.in_(ids)).all()
    city_ids = sorted({v.city_id for v in vendors if v.city_id})
    cities = {
        c.id: c.name
        for c in (db.query(City).filter(City.id.in_(city_ids)).all() if city_ids else [])
    }
    return {
        v.id: (v.business_name, cities.get(v.city_id) if v.city_id else None)
        for v in vendors
    }


@router.get("/products", response_model=List[StockProductSummary])
def list_stock(
    db: Session = Depends(get_db),
    search: Optional[str] = Query(None),
    year_group: Optional[str] = Query(None),
    lite: bool = Query(False, description="Skip images for faster pickers"),
    auth: AuthContext = Depends(get_auth_context),
):
    yg = (year_group or "").replace("\x00", "").strip()
    cache_key = f"stock:products:v2:{(search or '').replace(chr(0), '')}:{yg}:{int(lite)}"
    cached = response_cache.get(cache_key)
    if cached is not None:
        return cached

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

    rows = db.execute(
        text(
            f"""
            SELECT
              p.id AS catalog_product_id,
              p.our_product_id,
              p.vendor_product_id,
              p.vendor_id,
              p.category,
              p.series,
              p.year_group,
              p.selling_price,
              p.buying_price,
              p.unit,
              p.image_keys,
              COALESCE(sb.quantity_on_hand, 0) AS quantity_on_hand,
              COALESCE(sb.low_stock_threshold, 5) AS low_stock_threshold,
              v.business_name AS vendor_name,
              c.name AS vendor_city,
              COALESCE(ac.cnt, 0) AS addon_count,
              COALESCE(alt.cnt, 0) AS alt_count
            FROM jc_catalog_products p
            LEFT JOIN jc_stock_balances sb ON sb.catalog_product_id = p.id
            LEFT JOIN jc_vendors v ON v.id = p.vendor_id
            LEFT JOIN jc_cities c ON c.id = v.city_id
            LEFT JOIN (
              SELECT catalog_product_id, COUNT(*)::int AS cnt
              FROM jc_catalog_addon_links
              GROUP BY catalog_product_id
            ) ac ON ac.catalog_product_id = p.id
            LEFT JOIN (
              SELECT product_id, COUNT(*)::int AS cnt
              FROM jc_catalog_alternatives
              GROUP BY product_id
            ) alt ON alt.product_id = p.id
            WHERE p.is_active IS TRUE
              AND p.deleted_at IS NULL
              {search_sql}
              {year_sql}
            ORDER BY p.our_product_id ASC, COALESCE(p.year_group, '') ASC, p.id ASC
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
        keys = list(r["image_keys"] or [])
        keys = [] if lite else keys[:1]
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
                series=r["series"],
                year_group=r["year_group"],
                quantity_on_hand=qty,
                low_stock_threshold=th,
                stock_status=stock_status_label(qty, th),
                selling_price=(
                    format(eff, "f")
                    if (eff := effective_selling_price(r["buying_price"], r["selling_price"])) is not None
                    else None
                ),
                buying_price=format(r["buying_price"], "f") if r["buying_price"] is not None else None,
                unit=r["unit"],
                image_urls=presigned_urls(keys),
                addon_count=int(r["addon_count"] or 0),
                alt_count=int(r["alt_count"] or 0),
            )
        )
    response_cache.set(cache_key, out, 25.0)
    return out


@router.get("/products/{catalog_product_id}", response_model=StockProductDetail)
def get_stock_detail(
    catalog_product_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    row = db.get(CatalogProduct, catalog_product_id)
    if not row or not row.is_active:
        raise HTTPException(404, "product not found")
    balance_row = db.query(StockBalance).filter(StockBalance.catalog_product_id == catalog_product_id).first()
    qty = balance_row.quantity_on_hand if balance_row else 0
    threshold = balance_row.low_stock_threshold if balance_row else 5

    pending_map = pending_qty_by_product(db, row.vendor_id)
    pending = pending_map.get(catalog_product_id, 0)

    alts = db.query(CatalogAlternative).filter(CatalogAlternative.product_id == catalog_product_id).all()
    alt_pub = []
    for a in alts:
        alt = db.get(CatalogProduct, a.alternative_product_id)
        if alt and alt.is_active:
            vendor = db.get(Vendor, alt.vendor_id)
            city_name = None
            if vendor and vendor.city_id:
                city = db.get(City, vendor.city_id)
                city_name = city.name if city else None
            alt_pub.append({
                "catalog_product_id": alt.id,
                "our_product_id": alt.our_product_id,
                "vendor_name": vendor.business_name if vendor else None,
                "vendor_city": city_name,
                "buying_price": format(alt.buying_price, "f"),
                "selling_price": format(alt.selling_price, "f") if alt.selling_price is not None else None,
                "image_urls": presigned_urls(alt.image_keys or []),
            })

    ledger_rows = (
        db.query(StockLedger)
        .filter(StockLedger.catalog_product_id == catalog_product_id)
        .order_by(StockLedger.created_at.desc())
        .limit(100)
        .all()
    )
    ledger = [
        StockLedgerEntry(
            id=e.id,
            entry_type=e.entry_type,
            quantity_delta=e.quantity_delta,
            balance_after=e.balance_after,
            party=e.party,
            notes=e.notes,
            created_at=e.created_at,
            reference_type=e.reference_type,
            reference_id=e.reference_id,
        )
        for e in ledger_rows
    ]

    base = _product_public(row, db, qty, threshold)
    return StockProductDetail(
        **base,
        alternatives=alt_pub,
        quantity_pending=int(pending),
        quantity_sold=0,
        ledger=ledger,
    )


@router.get("/ledger/{ledger_id}", response_model=StockLedgerDetail)
def get_ledger_entry_detail(
    ledger_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    entry = db.get(StockLedger, ledger_id)
    if not entry:
        raise HTTPException(404, "ledger entry not found")
    receipt_data = None
    if entry.reference_type == "stock_receipt" and entry.reference_id:
        receipt = db.get(StockReceipt, entry.reference_id)
        if receipt:
            rlines = db.query(StockReceiptLine).filter(StockReceiptLine.receipt_id == receipt.id).all()
            receipt_data = {
                "id": receipt.id,
                "vendor_id": receipt.vendor_id,
                "bill_number": receipt.bill_number,
                "additional_charges": format(receipt.additional_charges, "f") if receipt.additional_charges is not None else None,
                "bill_file_url": presigned_url(receipt.bill_file_key) if receipt.bill_file_key else None,
                "received_at": receipt.received_at.isoformat(),
                "lines": [
                    {
                        "our_product_id": ln.our_product_id,
                        "quantity_received": ln.quantity_received,
                        "quantity_billed": ln.quantity_billed,
                        "billed_amount": format(ln.billed_amount, "f"),
                        "buying_price": format(ln.buying_price, "f"),
                    }
                    for ln in rlines
                ],
            }
            if auth.is_admin:
                receipt_data["received_by_name"] = receipt.received_by_name
                receipt_data["received_by_type"] = receipt.received_by_type
    return StockLedgerDetail(
        id=entry.id,
        entry_type=entry.entry_type,
        quantity_delta=entry.quantity_delta,
        balance_after=entry.balance_after,
        party=entry.party,
        notes=entry.notes,
        created_at=entry.created_at,
        reference_type=entry.reference_type,
        reference_id=entry.reference_id,
        receipt=receipt_data,
    )


@router.patch("/products/{catalog_product_id}/selling-price", response_model=StockProductSummary)
def update_selling_price(
    catalog_product_id: int,
    body: SellingPriceUpdate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    row = db.get(CatalogProduct, catalog_product_id)
    if not row or not row.is_active:
        raise HTTPException(404, "product not found")
    row.selling_price = coerce_selling_price(row.buying_price, body.selling_price)
    log_from_auth(
        db,
        auth,
        action="update",
        entity_type="catalog",
        entity_id=row.id,
        entity_label=row.our_product_id,
        detail=f"selling price → {row.selling_price}",
    )
    db.commit()
    response_cache.invalidate("stock:")
    response_cache.invalidate("catalog:")
    response_cache.invalidate("shop:")
    db.refresh(row)
    balance_row = db.query(StockBalance).filter(StockBalance.catalog_product_id == catalog_product_id).first()
    th = balance_row.low_stock_threshold if balance_row else 5
    qty = balance_row.quantity_on_hand if balance_row else 0
    d = _product_public(row, db, qty, th)
    return StockProductSummary(**d)


@router.post("/products/selling-price/bulk")
def bulk_update_selling_price(
    body: BulkSellingPriceIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    updated = 0
    for item in body.items:
        row = db.get(CatalogProduct, item.catalog_product_id)
        if not row or not row.is_active or row.deleted_at:
            raise HTTPException(400, f"product {item.catalog_product_id} not found")
        coerced = coerce_selling_price(row.buying_price, item.selling_price)
        if coerced is None:
            raise HTTPException(400, f"sell price for {row.our_product_id} must differ from buy price")
        row.selling_price = coerced
        updated += 1
    log_from_auth(
        db,
        auth,
        action="update",
        entity_type="catalog",
        entity_id=None,
        entity_label=None,
        detail=f"bulk selling price — {updated} products",
    )
    db.commit()
    response_cache.invalidate("stock:")
    response_cache.invalidate("catalog:")
    response_cache.invalidate("shop:")
    return {"ok": True, "updated": updated}


@router.patch("/products/{catalog_product_id}/threshold", response_model=StockProductSummary)
def update_stock_threshold(
    catalog_product_id: int,
    body: StockThresholdUpdate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    row = db.get(CatalogProduct, catalog_product_id)
    if not row or not row.is_active:
        raise HTTPException(404, "product not found")
    balance_row = db.query(StockBalance).filter(StockBalance.catalog_product_id == catalog_product_id).first()
    if not balance_row:
        from app.services.stock_receipt import add_stock
        balance_row = StockBalance(catalog_product_id=catalog_product_id, quantity_on_hand=0, low_stock_threshold=body.low_stock_threshold)
        db.add(balance_row)
    else:
        balance_row.low_stock_threshold = body.low_stock_threshold
    log_from_auth(
        db,
        auth,
        action="update",
        entity_type="catalog",
        entity_id=row.id,
        entity_label=row.our_product_id,
        detail=f"low stock threshold → {body.low_stock_threshold}",
    )
    db.commit()
    response_cache.invalidate("stock:")
    response_cache.invalidate("shop:")
    db.refresh(balance_row)
    d = _product_public(row, db, balance_row.quantity_on_hand, balance_row.low_stock_threshold)
    return StockProductSummary(**d)


@router.get("/vendor-order/{vendor_id}/placed", response_model=VendorPlacedOrderForReceipt)
def get_placed_order_for_receipt(
    vendor_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    vendor = db.get(Vendor, vendor_id)
    if not vendor or vendor.deleted_at:
        raise HTTPException(404, "vendor not found")
    city_name = _vendor_city(db, vendor)
    label = _vendor_label(vendor, city_name)
    placed = get_open_order(db, vendor_id, "placed")
    placed_map = placed_qty_by_product(db, vendor_id)
    pending_map = pending_qty_by_product(db, vendor_id)
    if not placed:
        return VendorPlacedOrderForReceipt(vendor_id=vendor_id, vendor_label=label, order_id=None, lines=[])

    all_ids = set(placed_map) | set(pending_map)

    lines: list[PlacedLineForReceipt] = []
    for cat_id in all_ids:
        pending = pending_map.get(cat_id, 0)
        if pending <= 0:
            continue
        prod = db.get(CatalogProduct, cat_id)
        if not prod:
            continue
        lines.append(
            PlacedLineForReceipt(
                catalog_product_id=cat_id,
                our_product_id=prod.our_product_id,
                vendor_product_id=prod.vendor_product_id,
                category=prod.category,
                quantity_ordered=int(placed_map.get(cat_id, 0)),
                quantity_remaining=int(pending),
                buying_price=format(prod.buying_price, "f"),
                unit=prod.unit,
                image_urls=presigned_urls(prod.image_keys or []),
            )
        )
    lines.sort(key=lambda x: x.our_product_id.lower())
    return VendorPlacedOrderForReceipt(
        vendor_id=vendor_id, vendor_label=label, order_id=placed.id, lines=lines
    )


@router.get("/vendor-order/{vendor_id}/received", response_model=VendorPendingBillList)
def get_pending_bill_receipts(
    vendor_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
) -> VendorPendingBillList:
    vendor = db.get(Vendor, vendor_id)
    if not vendor or vendor.deleted_at:
        raise HTTPException(404, "vendor not found")
    label = _vendor_label(vendor, _vendor_city(db, vendor))
    rows = (
        db.query(StockReceipt)
        .filter(StockReceipt.vendor_id == vendor_id, StockReceipt.bill_status == "pending_bill")
        .order_by(StockReceipt.received_at.asc())
        .all()
    )
    receipts = []
    for r in rows:
        lines = db.query(StockReceiptLine).filter(StockReceiptLine.receipt_id == r.id).all()
        receipts.append(PendingBillReceipt(
            receipt_id=r.id, order_receipt_number=r.order_receipt_number, received_at=r.received_at,
            expected_bill_amount=format(r.expected_bill_amount, "f") if r.expected_bill_amount is not None else None,
            expected_extra_cash=format(r.expected_extra_cash, "f") if r.expected_extra_cash is not None else None,
            line_count=len(lines), total_quantity=sum(l.quantity_received for l in lines),
        ))
    return VendorPendingBillList(vendor_id=vendor_id, vendor_label=label, receipts=receipts)


@router.get("/receipts/{receipt_id}/for-bill", response_model=ReceiptForBillDetail)
def get_receipt_for_bill(
    receipt_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
) -> ReceiptForBillDetail:
    receipt = db.get(StockReceipt, receipt_id)
    if not receipt or receipt.bill_status != "pending_bill":
        raise HTTPException(404, "receipt not open for billing")
    vendor = db.get(Vendor, receipt.vendor_id)
    if not vendor or vendor.deleted_at:
        raise HTTPException(404, "vendor not found")
    label = _vendor_label(vendor, _vendor_city(db, vendor))

    rlines = db.query(StockReceiptLine).filter(StockReceiptLine.receipt_id == receipt_id).all()
    lines: list[ReceiptLineForBill] = []
    for ln in rlines:
        prod = db.get(CatalogProduct, ln.catalog_product_id)
        lines.append(ReceiptLineForBill(
            catalog_product_id=ln.catalog_product_id,
            our_product_id=ln.our_product_id,
            quantity_received=ln.quantity_received,
            buying_price=format(ln.buying_price, "f"),
            unit=prod.unit if prod else None,
            image_urls=presigned_urls(prod.image_keys or []) if prod else [],
        ))
    lines.sort(key=lambda x: x.our_product_id.lower())

    billing_terms = {
        "billing_pct": format(vendor.billing_pct, "f"),
        "additional_charge": format(vendor.additional_charge, "f"),
        "additional_charge_label": vendor.additional_charge_label,
        "discount_pct": format(vendor.discount_pct, "f"),
        "gst_included": vendor.gst_included,
        "gst_rate_pct": format(vendor.gst_rate_pct, "f"),
        "billing_notes": vendor.billing_notes,
    }
    return ReceiptForBillDetail(
        receipt_id=receipt.id, vendor_id=vendor.id, vendor_label=label,
        order_receipt_number=receipt.order_receipt_number,
        expected_bill_amount=format(receipt.expected_bill_amount, "f") if receipt.expected_bill_amount is not None else None,
        expected_extra_cash=format(receipt.expected_extra_cash, "f") if receipt.expected_extra_cash is not None else None,
        billing_terms=billing_terms, lines=lines,
    )


@router.post("/receipts/{receipt_id}/bill-preview", response_model=BillPreviewOut)
def preview_receipt_bill(
    receipt_id: int,
    body: BillPreviewIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
) -> BillPreviewOut:
    receipt = db.get(StockReceipt, receipt_id)
    if not receipt or receipt.bill_status != "pending_bill":
        raise HTTPException(404, "receipt not open for billing")
    vendor = db.get(Vendor, receipt.vendor_id)
    if not vendor or vendor.deleted_at:
        raise HTTPException(404, "vendor not found")
    rlines = db.query(StockReceiptLine).filter(StockReceiptLine.receipt_id == receipt_id).all()
    billed_qty_by_pid = {
        ln_in.catalog_product_id: int(ln_in.quantity_billed)
        for ln_in in (body.lines or [])
        if ln_in.quantity_billed is not None
    }
    result = preview_bill_deviations(
        db, vendor, rlines, billed_qty_by_pid, body.total_billed_amount.quantize(Decimal("0.01")),
    )
    return BillPreviewOut(**result)


@router.post("/upload-bill")
async def upload_bill(
    vendor_id: int = Form(...),
    bill_number: str = Form(""),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
) -> dict:
    if not storage_configured():
        raise HTTPException(503, "S3 not configured")
    vendor = db.get(Vendor, vendor_id)
    if not vendor:
        raise HTTPException(400, "vendor not found")
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty file")
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(400, "file too large (max 10MB)")
    ext = "pdf"
    if file.filename and "." in file.filename:
        ext = file.filename.rsplit(".", 1)[-1].lower()[:8]
    slug = vendor_folder_slug(vendor.business_name)
    key = bill_key(slug, (bill_number or "").strip() or "receive", ext)
    upload_bytes(key, data, file.content_type or "application/pdf")
    url = presigned_url(key)
    return {"key": key, "url": url}


@router.post("/receipts/vendor-receive", status_code=status.HTTP_201_CREATED)
def create_vendor_receive(
    body: VendorReceiveCreate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    payload = VendorReceiptCreate(
        vendor_id=body.vendor_id,
        lines=body.lines,
        order_receipt_number=body.order_receipt_number,
        bill_file_key=body.bill_file_key,
        notes=body.notes,
        debit_notes=[],
        received_on=body.received_on,
    )
    result = receive_vendor_goods(db, auth, payload)
    response_cache.invalidate("stock:")
    response_cache.invalidate("shop:")
    return result


@router.post("/receipts/{receipt_id}/bill", status_code=status.HTTP_201_CREATED)
def create_receipt_bill(
    receipt_id: int,
    body: VendorBillIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    result = bill_receipt(db, auth, receipt_id, body)
    response_cache.invalidate("stock:")
    response_cache.invalidate("shop:")
    return result


@router.post("/receipts/offline-vendor", status_code=status.HTTP_201_CREATED)
def create_offline_vendor_receipt(
    body: VendorReceiveCreate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    """Offline receive only — stock up + Received bucket. Bill later via vendor-bill."""
    payload = VendorReceiptCreate(
        vendor_id=body.vendor_id,
        lines=body.lines,
        order_receipt_number=body.order_receipt_number,
        bill_file_key=body.bill_file_key,
        notes=body.notes,
        debit_notes=[],
        received_on=body.received_on,
    )
    result = receive_vendor_goods(db, auth, payload, offline=True)
    response_cache.invalidate("stock:")
    response_cache.invalidate("shop:")
    return result


@router.get("/receipts/{receipt_id}")
def get_receipt_detail(
    receipt_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    receipt = db.get(StockReceipt, receipt_id)
    if not receipt:
        raise HTTPException(404, "receipt not found")
    rlines = db.query(StockReceiptLine).filter(StockReceiptLine.receipt_id == receipt.id).all()
    bill_amt = receipt_bill_amount(db, receipt.id)
    dn_total = receipt_debit_note_total(db, receipt.id)
    notes = db.query(DebitNote).filter(DebitNote.receipt_id == receipt.id).order_by(DebitNote.id.asc()).all()
    history = list_entity_history(db, "stock_receipt", receipt.id)
    data = {
        "id": receipt.id,
        "vendor_id": receipt.vendor_id,
        "receipt_type": receipt.receipt_type,
        "bill_status": receipt.bill_status,
        "bill_number": receipt.bill_number,
        "order_receipt_number": receipt.order_receipt_number,
        "notes": receipt.notes,
        "bill_file_key": receipt.bill_file_key,
        "additional_charges": format(receipt.additional_charges, "f") if receipt.additional_charges is not None else None,
        "total_billed_amount": format(receipt.total_billed_amount, "f") if receipt.total_billed_amount is not None else None,
        "bill_amount": format(bill_amt, "f"),
        "debit_note_total": format(dn_total, "f"),
        "net_payable": format(bill_amt + dn_total, "f"),
        "bill_file_url": presigned_url(receipt.bill_file_key) if receipt.bill_file_key else None,
        "receipt_document_url": presigned_url(receipt.receipt_document_key) if receipt.receipt_document_key else None,
        "received_at": receipt.received_at.isoformat(),
        "lines": [
            {
                "catalog_product_id": ln.catalog_product_id,
                "our_product_id": ln.our_product_id,
                "quantity_received": ln.quantity_received,
                "quantity_billed": ln.quantity_billed,
                "billed_amount": format(ln.billed_amount, "f"),
                "buying_price": format(ln.buying_price, "f"),
            }
            for ln in rlines
        ],
        "debit_notes": [
            {
                "id": n.id,
                "note_type": n.note_type,
                "direction": n.direction,
                "catalog_product_id": n.catalog_product_id,
                "our_product_id": n.our_product_id,
                "quantity": n.quantity,
                "amount": format(n.amount, "f"),
                "payable_effect": format(debit_note_payable_effect(n.amount, n.note_type), "f"),
                "notes": n.notes,
            }
            for n in notes
        ],
        "change_history": [
            {
                "change_summary": h.change_summary,
                "valid_from": h.valid_from.isoformat() if h.valid_from else None,
                "snapshot_json": h.snapshot_json,
            }
            for h in history
        ],
    }
    if auth.is_admin:
        data["received_by_name"] = receipt.received_by_name
    return data


@router.patch("/receipts/{receipt_id}")
def patch_receipt(
    receipt_id: int,
    body: VendorReceiptCreate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    result = update_vendor_receipt(db, auth, receipt_id, body)
    response_cache.invalidate("stock:")
    response_cache.invalidate("shop:")
    return result


@router.get("/receipts/{receipt_id}/document")
def get_receipt_document(
    receipt_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    receipt = db.get(StockReceipt, receipt_id)
    if not receipt:
        raise HTTPException(404, "receipt not found")
    if storage_configured():
        try:
            generate_vendor_receipt_document(db, receipt.id)
            db.commit()
            db.refresh(receipt)
        except Exception as exc:
            db.rollback()
            import logging
            logging.getLogger(__name__).exception("receipt PDF generate failed for %s", receipt_id)
            raise HTTPException(500, f"document generation failed: {exc}") from exc
    if not receipt.receipt_document_key:
        raise HTTPException(404, "document not available")
    url = presigned_url(receipt.receipt_document_key)
    if not url:
        raise HTTPException(503, "storage not available")
    return {"document_url": url, "document_key": receipt.receipt_document_key}


@router.get("/receipts/{receipt_id}/lines")
def get_receipt_lines(
    receipt_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    receipt = db.get(StockReceipt, receipt_id)
    if not receipt:
        raise HTTPException(404, "receipt not found")
    lines = db.query(StockReceiptLine).filter(StockReceiptLine.receipt_id == receipt_id).all()
    return [
        {
            "catalog_product_id": ln.catalog_product_id,
            "our_product_id": ln.our_product_id,
            "buying_price": format(ln.buying_price, "f"),
            "quantity_received": ln.quantity_received,
        }
        for ln in lines
    ]
