from __future__ import annotations
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.deps import AuthContext, get_auth_context, require_admin, require_permission
from app.models.addon_product import AddonProduct
from app.models.catalog_addon_link import CatalogAddonLink
from app.models.catalog_alternative import CatalogAlternative
from app.models.catalog_product import CatalogProduct
from app.models.city import City
from app.models.customer import Customer
from app.models.customer_bill import CustomerBill
from app.models.customer_order import CustomerOrderPlacement
from app.models.customer_return import CustomerReturn
from app.models.debit_note import DebitNote
from app.models.route import Route
from app.models.staff import Staff
from app.models.stock import StockReceipt
from app.models.vendor import Vendor
from app.services.activity import log_from_auth
from app.routers.customers import _to_public as customer_public
from app.routers.routes import _city_public, _route_public
from app.routers.catalog import _to_public as catalog_public
from app.routers.addons import _to_public as addon_public
from app.routers.vendors import _to_public as vendor_public
from app.schemas.customer import (
    CityDetail,
    CustomerPublic,
    RecycleBinItem,
    RecycleBinList,
    RouteDetail,
)
from app.schemas.catalog import CatalogProductPublic
from app.schemas.addon import AddonPublic
from app.schemas.vendor import VendorPublic
from app.services.storage import delete_keys
from app.services.void_service import (
    purge_customer_bill,
    purge_customer_placement,
    purge_customer_return,
    purge_debit_note,
    purge_receipt,
    restore_customer_bill,
    restore_customer_placement,
    restore_customer_return,
    restore_debit_note,
    restore_receipt,
)

from app.routers.recycle_bin.router import router

@router.delete("/routes/{route_id}", dependencies=[Depends(require_admin)])
def purge_route(route_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)) -> dict:
    row = db.get(Route, route_id)
    if not row or row.is_active:
        raise HTTPException(404, "deleted route not found")
    log_from_auth(db, auth, action="purge", entity_type="route", entity_id=row.id, entity_label=row.name)
    db.delete(row)
    db.commit()
    return {"ok": True, "message": "route permanently deleted"}

@router.delete("/cities/{city_id}", dependencies=[Depends(require_admin)])
def purge_city(city_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)) -> dict:
    row = db.get(City, city_id)
    if not row or row.is_active:
        raise HTTPException(404, "deleted city not found")
    vend_n = db.query(Vendor).filter(Vendor.city_id == city_id).count()
    cust_n = db.query(Customer).filter(Customer.city_id == city_id).count()
    if vend_n or cust_n:
        raise HTTPException(400, f"city still linked to {vend_n} vendor(s) and {cust_n} customer(s) — purge those first")
    log_from_auth(db, auth, action="purge", entity_type="city", entity_id=row.id, entity_label=row.name)
    db.delete(row)
    db.commit()
    return {"ok": True, "message": "city permanently deleted"}

@router.delete("/customers/{customer_id}", dependencies=[Depends(require_admin)])
def purge_customer(customer_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)) -> dict:
    row = db.get(Customer, customer_id)
    if not row or row.is_active:
        raise HTTPException(404, "deleted customer not found")
    original_phone = row.phone
    customer_name = row.business_name
    try:
        log_from_auth(db, auth, action="purge", entity_type="customer", entity_id=row.id, entity_label=customer_name)
        db.delete(row)
        db.commit()
        return {"ok": True, "message": "customer permanently deleted"}
    except IntegrityError:
        db.rollback()
        # Orders / AR still reference this customer — free the phone so it can be reused.
        row = db.get(Customer, customer_id)
        if not row or row.is_active:
            raise HTTPException(404, "deleted customer not found")
        freed = f"x{customer_id}_{original_phone}"[-32:]
        row.phone = freed
        row.is_active = False
        if not row.deleted_at:
            row.deleted_at = datetime.now(timezone.utc)
        db.add(row)
        try:
            log_from_auth(
                db,
                auth,
                action="purge",
                entity_type="customer",
                entity_id=row.id,
                entity_label=customer_name,
                detail="phone freed for reuse",
            )
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(
                400,
                "cannot permanently delete — linked orders/bills remain and phone could not be freed",
            ) from None
        return {
            "ok": True,
            "message": "customer removed from recycle; phone freed for reuse (history kept)",
            "phone_freed": original_phone,
        }

@router.delete("/vendors/{vendor_id}", dependencies=[Depends(require_admin)])
def purge_vendor(vendor_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)) -> dict:
    row = db.get(Vendor, vendor_id)
    if not row or row.is_active:
        raise HTTPException(404, "deleted vendor not found")
    cat_n = db.query(CatalogProduct).filter(CatalogProduct.vendor_id == vendor_id).count()
    addon_n = db.query(AddonProduct).filter(AddonProduct.vendor_id == vendor_id).count()
    if cat_n or addon_n:
        raise HTTPException(400, f"vendor still has {cat_n} catalog and {addon_n} addon product(s) — purge those first")
    log_from_auth(db, auth, action="purge", entity_type="vendor", entity_id=row.id, entity_label=row.business_name)
    db.delete(row)
    db.commit()
    return {"ok": True, "message": "vendor permanently deleted"}

@router.delete("/catalog-products/{product_id}", dependencies=[Depends(require_admin)])
def purge_catalog_product(product_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)) -> dict:
    row = db.get(CatalogProduct, product_id)
    if not row or row.is_active:
        raise HTTPException(404, "deleted product not found")
    db.query(CatalogAlternative).filter(
        (CatalogAlternative.product_id == product_id) | (CatalogAlternative.alternative_product_id == product_id)
    ).delete(synchronize_session=False)
    db.query(CatalogAddonLink).filter(CatalogAddonLink.catalog_product_id == product_id).delete(synchronize_session=False)
    label = row.our_product_id
    try:
        if row.image_keys:
            delete_keys(row.image_keys)
        log_from_auth(db, auth, action="purge", entity_type="catalog", entity_id=row.id, entity_label=label)
        db.delete(row)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            400,
            "cannot permanently delete — this product has stock/order/bill history. "
            "It stays safely in the recycle bin (soft-deleted); history is kept.",
        ) from None
    from app.services import response_cache
    response_cache.invalidate("catalog:")
    response_cache.invalidate("stock:")
    return {"ok": True, "message": "product permanently deleted"}

@router.delete("/addons/{addon_id}", dependencies=[Depends(require_admin)])
def purge_addon(addon_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)) -> dict:
    row = db.get(AddonProduct, addon_id)
    if not row or row.is_active:
        raise HTTPException(404, "deleted addon not found")
    db.query(CatalogAddonLink).filter(CatalogAddonLink.addon_product_id == addon_id).delete(synchronize_session=False)
    label = row.our_product_id
    try:
        if row.image_keys:
            delete_keys(row.image_keys)
        log_from_auth(db, auth, action="purge", entity_type="addon", entity_id=row.id, entity_label=label)
        db.delete(row)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            400,
            "cannot permanently delete — this add-on has stock movement history. "
            "It stays safely in the recycle bin (soft-deleted); history is kept.",
        ) from None
    return {"ok": True, "message": "addon permanently deleted"}

@router.delete("/staff/{staff_id}", dependencies=[Depends(require_admin)])
def purge_staff(staff_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)) -> dict:
    row = db.get(Staff, staff_id)
    if not row or row.is_active:
        raise HTTPException(404, "deleted staff not found")
    log_from_auth(db, auth, action="purge", entity_type="staff", entity_id=row.id, entity_label=row.name)
    db.delete(row)
    db.commit()
    return {"ok": True, "message": "staff permanently deleted"}

@router.delete("/receipts/{receipt_id}", dependencies=[Depends(require_admin)])
def purge_receipt_endpoint(receipt_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)) -> dict:
    from app.services import response_cache

    result = purge_receipt(db, auth, receipt_id)
    response_cache.invalidate("stock:")
    return result

@router.delete("/debit-notes/{note_id}", dependencies=[Depends(require_admin)])
def purge_debit_note_endpoint(note_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)) -> dict:
    from app.services import response_cache

    result = purge_debit_note(db, auth, note_id)
    response_cache.invalidate("stock:")
    return result

@router.delete("/customer-bills/{bill_id}", dependencies=[Depends(require_admin)])
def purge_customer_bill_endpoint(bill_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)) -> dict:
    from app.services import response_cache

    result = purge_customer_bill(db, auth, bill_id)
    response_cache.invalidate("stock:")
    response_cache.invalidate("shop:")
    return result

@router.delete("/customer-placements/{placement_id}", dependencies=[Depends(require_admin)])
def purge_customer_placement_endpoint(placement_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)) -> dict:
    from app.services import response_cache

    result = purge_customer_placement(db, auth, placement_id)
    response_cache.invalidate("stock:")
    response_cache.invalidate("shop:")
    return result

@router.delete("/customer-returns/{return_id}", dependencies=[Depends(require_admin)])
def purge_customer_return_endpoint(return_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)) -> dict:
    from app.services import response_cache

    result = purge_customer_return(db, auth, return_id)
    response_cache.invalidate("stock:")
    response_cache.invalidate("shop:")
    return result
