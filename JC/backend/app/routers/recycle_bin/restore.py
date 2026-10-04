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

@router.post("/routes/{route_id}/restore", dependencies=[Depends(require_permission("recycle.write"))])
def restore_route(route_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permission("recycle.write"))) -> dict:
    row = db.get(Route, route_id)
    if not row or row.is_active:
        raise HTTPException(404, "deleted route not found")
    if db.query(Route).filter(Route.name == row.name, Route.is_active.is_(True), Route.id != route_id).first():
        raise HTTPException(409, "an active route with this name already exists")
    row.is_active = True
    row.deleted_at = None
    log_from_auth(db, auth, action="restore", entity_type="route", entity_id=row.id, entity_label=row.name)
    db.commit()
    return {"ok": True, "message": "route restored"}

@router.post("/cities/{city_id}/restore", dependencies=[Depends(require_permission("recycle.write"))])
def restore_city(city_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permission("recycle.write"))) -> dict:
    row = db.get(City, city_id)
    if not row or row.is_active:
        raise HTTPException(404, "deleted city not found")
    if db.query(City).filter(City.name == row.name, City.is_active.is_(True), City.id != city_id).first():
        raise HTTPException(409, "an active city with this name already exists")
    if row.route_id:
        route = db.get(Route, row.route_id)
        if not route or not route.is_active:
            raise HTTPException(400, "linked route is deleted — reassign route before restoring")
    row.is_active = True
    row.deleted_at = None
    log_from_auth(db, auth, action="restore", entity_type="city", entity_id=row.id, entity_label=row.name)
    db.commit()
    return {"ok": True, "message": "city restored"}

@router.post("/customers/{customer_id}/restore", dependencies=[Depends(require_permission("recycle.write"))])
def restore_customer(customer_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permission("recycle.write"))) -> dict:
    row = db.get(Customer, customer_id)
    if not row or row.is_active:
        raise HTTPException(404, "deleted customer not found")
    if db.query(Customer).filter(Customer.phone == row.phone, Customer.is_active.is_(True), Customer.id != customer_id).first():
        raise HTTPException(409, "an active customer with this phone already exists")
    if row.city_id:
        city = db.get(City, row.city_id)
        if not city or not city.is_active:
            raise HTTPException(400, "linked city is deleted — reassign city before restoring")
    row.is_active = True
    row.deleted_at = None
    log_from_auth(db, auth, action="restore", entity_type="customer", entity_id=row.id, entity_label=row.business_name)
    db.commit()
    return {"ok": True, "message": "customer restored"}

@router.post("/vendors/{vendor_id}/restore", dependencies=[Depends(require_permission("recycle.write"))])
def restore_vendor(vendor_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permission("recycle.write"))) -> dict:
    row = db.get(Vendor, vendor_id)
    if not row or row.is_active:
        raise HTTPException(404, "deleted vendor not found")
    if db.query(Vendor).filter(Vendor.phone == row.phone, Vendor.is_active.is_(True), Vendor.id != vendor_id).first():
        raise HTTPException(409, "an active vendor with this phone already exists")
    city = db.get(City, row.city_id)
    if not city or not city.is_active:
        raise HTTPException(400, "linked city is deleted — reassign city before restoring")
    row.is_active = True
    row.deleted_at = None
    log_from_auth(db, auth, action="restore", entity_type="vendor", entity_id=row.id, entity_label=row.business_name)
    db.commit()
    return {"ok": True, "message": "vendor restored"}

@router.post("/catalog-products/{product_id}/restore", dependencies=[Depends(require_permission("recycle.write"))])
def restore_catalog_product(product_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permission("recycle.write"))) -> dict:
    row = db.get(CatalogProduct, product_id)
    if not row or row.is_active:
        raise HTTPException(404, "deleted product not found")
    from app.services.catalog_identity import find_active_sku_year, year_key
    if find_active_sku_year(db, row.our_product_id, row.year_group, exclude_id=product_id):
        yg = year_key(row.year_group) or "—"
        raise HTTPException(409, f"active product with same our_product_id exists for year group {yg}")
    vendor = db.get(Vendor, row.vendor_id)
    if not vendor or not vendor.is_active or vendor.deleted_at:
        raise HTTPException(400, "linked vendor is deleted — restore vendor first")
    row.is_active = True
    row.deleted_at = None
    log_from_auth(db, auth, action="restore", entity_type="catalog", entity_id=row.id, entity_label=row.our_product_id)
    db.commit()
    from app.services import response_cache
    response_cache.invalidate("catalog:")
    response_cache.invalidate("stock:")
    return {"ok": True, "message": "product restored"}

@router.post("/addons/{addon_id}/restore", dependencies=[Depends(require_permission("recycle.write"))])
def restore_addon(addon_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permission("recycle.write"))) -> dict:
    row = db.get(AddonProduct, addon_id)
    if not row or row.is_active:
        raise HTTPException(404, "deleted addon not found")
    if db.query(AddonProduct).filter(AddonProduct.our_product_id == row.our_product_id, AddonProduct.is_active.is_(True), AddonProduct.id != addon_id).first():
        raise HTTPException(409, "active addon with same our_product_id exists")
    row.is_active = True
    row.deleted_at = None
    log_from_auth(db, auth, action="restore", entity_type="addon", entity_id=row.id, entity_label=row.our_product_id)
    db.commit()
    return {"ok": True, "message": "addon restored"}

@router.post("/staff/{staff_id}/restore", dependencies=[Depends(require_admin)])
def restore_staff(staff_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)) -> dict:
    row = db.get(Staff, staff_id)
    if not row or row.is_active:
        raise HTTPException(404, "deleted staff not found")
    if db.query(Staff).filter(Staff.phone == row.phone, Staff.is_active.is_(True), Staff.id != staff_id).first():
        raise HTTPException(409, "an active staff with this phone already exists")
    row.is_active = True
    row.deleted_at = None
    log_from_auth(db, auth, action="restore", entity_type="staff", entity_id=row.id, entity_label=row.name)
    db.commit()
    return {"ok": True, "message": "staff restored"}

@router.post("/receipts/{receipt_id}/restore", dependencies=[Depends(require_admin)])
def restore_receipt_endpoint(receipt_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)) -> dict:
    from app.services import response_cache

    result = restore_receipt(db, auth, receipt_id)
    response_cache.invalidate("stock:")
    response_cache.invalidate("shop:")
    return result

@router.post("/debit-notes/{note_id}/restore", dependencies=[Depends(require_admin)])
def restore_debit_note_endpoint(note_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)) -> dict:
    from app.services import response_cache

    result = restore_debit_note(db, auth, note_id)
    response_cache.invalidate("stock:")
    return result

@router.post("/customer-bills/{bill_id}/restore", dependencies=[Depends(require_admin)])
def restore_customer_bill_endpoint(bill_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)) -> dict:
    from app.services import response_cache

    result = restore_customer_bill(db, auth, bill_id)
    response_cache.invalidate("stock:")
    response_cache.invalidate("shop:")
    return result

@router.post("/customer-placements/{placement_id}/restore", dependencies=[Depends(require_admin)])
def restore_customer_placement_endpoint(placement_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)) -> dict:
    from app.services import response_cache

    result = restore_customer_placement(db, auth, placement_id)
    response_cache.invalidate("stock:")
    response_cache.invalidate("shop:")
    return result

@router.post("/customer-returns/{return_id}/restore", dependencies=[Depends(require_admin)])
def restore_customer_return_endpoint(return_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)) -> dict:
    from app.services import response_cache

    result = restore_customer_return(db, auth, return_id)
    response_cache.invalidate("stock:")
    response_cache.invalidate("shop:")
    return result
