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

@router.get("/products/{catalog_product_id}", response_model=StockProductDetail)
def get_stock_detail(
    catalog_product_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("stock.read")),
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
                "buying_price": hide_cost(format(alt.buying_price, "f"), auth),
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
    from app.services.stock_receipt import annotate_stock_ledger

    ledger = [StockLedgerEntry(**row) for row in annotate_stock_ledger(db, ledger_rows)]

    from app.models.addon_product import AddonProduct
    from app.models.catalog_addon_link import CatalogAddonLink

    addon_links_pub: list[dict] = []
    for lk in db.query(CatalogAddonLink).filter(CatalogAddonLink.catalog_product_id == catalog_product_id).all():
        addon = db.get(AddonProduct, lk.addon_product_id)
        if not addon or not addon.is_active or addon.deleted_at:
            continue
        addon_links_pub.append({
            "id": lk.id,
            "catalog_product_id": lk.catalog_product_id,
            "addon_product_id": lk.addon_product_id,
            "addon_our_product_id": addon.our_product_id,
            "addon_name": addon.name or addon.our_product_id,
            "quantity": lk.quantity,
            "image_urls": list(presigned_urls(addon.image_keys or []) or []),
        })

    reserved_rows = [ReservedByPartyRow(**r) for r in reserved_by_party(db, catalog_product_id)]

    base = _product_public(row, db, qty, threshold, auth=auth)
    return StockProductDetail(
        **base,
        alternatives=alt_pub,
        addon_links=addon_links_pub,
        quantity_pending=int(pending),
        quantity_sold=0,
        ledger=ledger,
        reserved_by_party=reserved_rows,
    )

def _product_public(
    row: CatalogProduct,
    db: Session,
    balance: int = 0,
    threshold: int = 5,
    *,
    auth: AuthContext,
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
        "marking": row.marking,
        "quantity_on_hand": balance,
        "low_stock_threshold": threshold,
        "stock_status": admin_stock_status_label(balance, threshold),
        "selling_price": (
            format(eff, "f")
            if (eff := effective_selling_price(row.buying_price, row.selling_price)) is not None
            else None
        ),
        "buying_price": hide_cost(format(row.buying_price, "f") if row.buying_price is not None else None, auth),
        "unit": row.unit,
        "image_urls": presigned_urls(keys),
        "addon_count": int(addon_count or 0),
        "alt_count": int(alt_count or 0),
    }

@router.get("/vendor-order/{vendor_id}/received", response_model=VendorPendingBillList)
def get_pending_bill_receipts(
    vendor_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.read")),
) -> VendorPendingBillList:
    vendor = db.get(Vendor, vendor_id)
    if not vendor or vendor.deleted_at:
        raise HTTPException(404, "vendor not found")
    label = _vendor_label(vendor, _vendor_city(db, vendor))
    from sqlalchemy import func

    rows = (
        db.query(StockReceipt)
        .filter(
            StockReceipt.vendor_id == vendor_id,
            StockReceipt.bill_status == "pending_bill",
            StockReceipt.deleted_at.is_(None),
        )
        .order_by(StockReceipt.received_at.asc())
        .all()
    )
    receipt_ids = [r.id for r in rows]
    line_stats: dict[int, tuple[int, int]] = {}
    if receipt_ids:
        agg = (
            db.query(
                StockReceiptLine.receipt_id,
                func.count(StockReceiptLine.id),
                func.coalesce(func.sum(StockReceiptLine.quantity_received), 0),
            )
            .filter(StockReceiptLine.receipt_id.in_(receipt_ids))
            .group_by(StockReceiptLine.receipt_id)
            .all()
        )
        line_stats = {int(rid): (int(cnt), int(qty)) for rid, cnt, qty in agg}
    receipts = []
    for r in rows:
        line_count, total_qty = line_stats.get(r.id, (0, 0))
        view = present(db, "vendor_receipt", r)
        receipts.append(PendingBillReceipt(
            receipt_id=r.id,
            order_receipt_number=r.order_receipt_number,
            received_at=r.received_at,
            display_date=view.get("display_date") or r.received_at,
            display_name=view.get("display_name"),
            status=view.get("status"),
            expected_bill_amount=format(r.expected_bill_amount, "f") if r.expected_bill_amount is not None else None,
            expected_extra_cash=format(r.expected_extra_cash, "f") if r.expected_extra_cash is not None else None,
            line_count=line_count, total_quantity=total_qty,
        ))
    return VendorPendingBillList(vendor_id=vendor_id, vendor_label=label, vendor_alias=vendor.alias, receipts=receipts)

@router.get("/vendor-order/{vendor_id}/placed", response_model=VendorPlacedOrderForReceipt)
def get_placed_order_for_receipt(
    vendor_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.read")),
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
                buying_price=hide_cost(
                    format(prod.buying_price, "f") if prod.buying_price is not None else None,
                    auth,
                ),
                unit=prod.unit,
                image_urls=presigned_urls(prod.image_keys or []),
            )
        )
    lines.sort(key=lambda x: x.our_product_id.lower())
    return VendorPlacedOrderForReceipt(
        vendor_id=vendor_id, vendor_label=label, order_id=placed.id, lines=lines
    )

@router.get("/receipts/{receipt_id}/for-bill", response_model=ReceiptForBillDetail)
def get_receipt_for_bill(
    receipt_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.read")),
) -> ReceiptForBillDetail:
    receipt = db.get(StockReceipt, receipt_id)
    if not receipt or receipt.deleted_at or receipt.bill_status != "pending_bill":
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
            our_product_id=prod.our_product_id if prod else ln.our_product_id,
            vendor_product_id=prod.vendor_product_id if prod else None,
            year_group=prod.year_group if prod else None,
            quantity_received=ln.quantity_received,
            buying_price=hide_cost(format(ln.buying_price, "f"), auth),
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
        receipt_id=receipt.id, vendor_id=vendor.id, vendor_label=label, vendor_alias=vendor.alias,
        order_receipt_number=receipt.order_receipt_number,
        expected_bill_amount=format(receipt.expected_bill_amount, "f") if receipt.expected_bill_amount is not None else None,
        expected_extra_cash=format(receipt.expected_extra_cash, "f") if receipt.expected_extra_cash is not None else None,
        billing_terms=billing_terms, lines=lines,
    )

@router.post("/products/{catalog_product_id}/adjust", response_model=StockProductSummary, dependencies=[Depends(require_admin)])
def adjust_stock(
    catalog_product_id: int,
    body: StockAdjustIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    """Manual stock correction — no order/receipt involved. Admin-only; full ledger trail kept."""
    row = db.get(CatalogProduct, catalog_product_id)
    if not row or not row.is_active:
        raise HTTPException(404, "product not found")
    from app.services.stock_receipt import add_stock

    balance = add_stock(
        db,
        catalog_product_id=catalog_product_id,
        our_product_id=row.our_product_id,
        quantity=body.quantity_delta,
        entry_type="manual_adjustment",
        reference_type="manual_adjustment",
        reference_id=catalog_product_id,
        party=auth.actor_name,
        notes=body.reason.strip(),
    )
    log_from_auth(
        db,
        auth,
        action="adjust",
        entity_type="catalog",
        entity_id=row.id,
        entity_label=row.our_product_id,
        detail=f"stock {'+' if body.quantity_delta > 0 else ''}{body.quantity_delta} — {body.reason.strip()[:120]}",
    )
    db.commit()
    response_cache.invalidate("stock:")
    response_cache.invalidate("shop:")
    db.refresh(balance)
    d = _product_public(row, db, balance.quantity_on_hand, balance.low_stock_threshold, auth=auth)
    return StockProductSummary(**d)

@router.patch("/products/{catalog_product_id}/threshold", response_model=StockProductSummary)
def update_stock_threshold(
    catalog_product_id: int,
    body: StockThresholdUpdate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("stock.write")),
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
    d = _product_public(row, db, balance_row.quantity_on_hand, balance_row.low_stock_threshold, auth=auth)
    return StockProductSummary(**d)

@router.patch("/products/{catalog_product_id}/selling-price", response_model=StockProductSummary, dependencies=[Depends(require_admin)])
def update_selling_price(
    catalog_product_id: int,
    body: SellingPriceUpdate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
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
    d = _product_public(row, db, qty, th, auth=auth)
    return StockProductSummary(**d)

def _vendor_city(db: Session, vendor: Vendor) -> Optional[str]:
    if not vendor.city_id:
        return None
    city = db.get(City, vendor.city_id)
    return city.name if city else None

def _vendor_label(vendor: Vendor, city_name: Optional[str]) -> str:
    city = city_name or ""
    return f"{vendor.business_name} — {city}" if city else vendor.business_name

