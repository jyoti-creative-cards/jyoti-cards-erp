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
    purge_debit_note,
    purge_receipt,
    restore_debit_note,
    restore_receipt,
)

router = APIRouter(prefix="/recycle-bin", tags=["recycle-bin"])


@router.get("", response_model=RecycleBinList, dependencies=[Depends(require_permission("recycle.read"))])
def list_recycle_bin(db: Session = Depends(get_db)) -> RecycleBinList:
    route_rows = db.query(Route).filter(Route.is_active.is_(False)).order_by(Route.deleted_at.desc()).all()
    city_rows = db.query(City).filter(City.is_active.is_(False)).order_by(City.deleted_at.desc()).all()
    cust_rows = db.query(Customer).filter(Customer.is_active.is_(False)).order_by(Customer.deleted_at.desc()).all()
    vend_rows = db.query(Vendor).filter(Vendor.is_active.is_(False)).order_by(Vendor.deleted_at.desc()).all()
    cat_rows = db.query(CatalogProduct).filter(CatalogProduct.is_active.is_(False)).order_by(CatalogProduct.deleted_at.desc()).all()
    addon_rows = db.query(AddonProduct).filter(AddonProduct.is_active.is_(False)).order_by(AddonProduct.deleted_at.desc()).all()
    staff_rows = db.query(Staff).filter(Staff.is_active.is_(False)).order_by(Staff.deleted_at.desc()).all()
    receipt_rows = (
        db.query(StockReceipt).filter(StockReceipt.deleted_at.isnot(None)).order_by(StockReceipt.deleted_at.desc()).all()
    )
    dn_rows = (
        db.query(DebitNote).filter(DebitNote.deleted_at.isnot(None)).order_by(DebitNote.deleted_at.desc()).all()
    )

    routes = [RecycleBinItem(type="route", id=r.id, name=r.name, subtitle=r.notes, deleted_at=r.deleted_at) for r in route_rows]
    route_map = {r.id: r.name for r in route_rows}
    active_routes = {r.id: r.name for r in db.query(Route).filter(Route.is_active.is_(True)).all()}
    route_map.update(active_routes)
    cities = []
    for c in city_rows:
        route_name = route_map.get(c.route_id) if c.route_id else None
        cities.append(RecycleBinItem(type="city", id=c.id, name=c.name, subtitle=f"Route: {route_name}" if route_name else "No route", deleted_at=c.deleted_at))
    customers = [RecycleBinItem(type="customer", id=c.id, name=c.business_name, subtitle=c.phone, deleted_at=c.deleted_at) for c in cust_rows]
    vendors = [RecycleBinItem(type="vendor", id=v.id, name=v.business_name, subtitle=v.phone, deleted_at=v.deleted_at) for v in vend_rows]
    catalog_products = [RecycleBinItem(type="catalog_product", id=p.id, name=p.our_product_id, subtitle=p.vendor_product_id, deleted_at=p.deleted_at) for p in cat_rows]
    addons = [RecycleBinItem(type="addon", id=a.id, name=a.our_product_id, subtitle=a.name or a.vendor_product_id, deleted_at=a.deleted_at) for a in addon_rows]
    staff = [RecycleBinItem(type="staff", id=s.id, name=s.name, subtitle=s.phone, deleted_at=s.deleted_at) for s in staff_rows]

    vendor_ids_for_notes = {r.vendor_id for r in receipt_rows} | {d.vendor_id for d in dn_rows}
    vendor_names = {
        v.id: v.business_name
        for v in (db.query(Vendor).filter(Vendor.id.in_(vendor_ids_for_notes)).all() if vendor_ids_for_notes else [])
    }
    receipts = [
        RecycleBinItem(
            type="receipt",
            id=r.id,
            name=f"{'Bill' if r.bill_status == 'billed' else 'Receipt'} — {vendor_names.get(r.vendor_id, f'Vendor #{r.vendor_id}')}",
            subtitle=r.bill_number or r.order_receipt_number or r.deleted_reason,
            deleted_at=r.deleted_at,
        )
        for r in receipt_rows
    ]
    debit_notes = [
        RecycleBinItem(
            type="debit_note",
            id=d.id,
            name=f"Debit note ₹{d.amount} — {vendor_names.get(d.vendor_id, f'Vendor #{d.vendor_id}')}",
            subtitle=d.notes or d.deleted_reason,
            deleted_at=d.deleted_at,
        )
        for d in dn_rows
    ]
    total = (
        len(routes) + len(cities) + len(customers) + len(vendors) + len(catalog_products) + len(addons) + len(staff)
        + len(receipts) + len(debit_notes)
    )
    return RecycleBinList(
        routes=routes, cities=cities, customers=customers, vendors=vendors, catalog_products=catalog_products,
        addons=addons, staff=staff, receipts=receipts, debit_notes=debit_notes, total=total,
    )


@router.get("/routes/{route_id}", response_model=RouteDetail, dependencies=[Depends(require_permission("recycle.read"))])
def get_deleted_route(route_id: int, db: Session = Depends(get_db)) -> RouteDetail:
    row = db.get(Route, route_id)
    if not row or row.is_active:
        raise HTTPException(404, "deleted route not found")
    pub = _route_public(row, db, include_deleted=True)
    city_rows = db.query(City).filter(City.route_id == route_id).order_by(City.name).all()
    cities = [_city_public(c, db, include_deleted_customers=True) for c in city_rows]
    return RouteDetail(**pub.model_dump(), cities=cities)


@router.get("/cities/{city_id}", response_model=CityDetail, dependencies=[Depends(require_permission("recycle.read"))])
def get_deleted_city(city_id: int, db: Session = Depends(get_db)) -> CityDetail:
    row = db.get(City, city_id)
    if not row or row.is_active:
        raise HTTPException(404, "deleted city not found")
    pub = _city_public(row, db, include_deleted_customers=True)
    customers = [customer_public(c, db) for c in db.query(Customer).filter(Customer.city_id == city_id).order_by(Customer.business_name).all()]
    return CityDetail(**pub.model_dump(), customers=customers)


@router.get("/customers/{customer_id}", response_model=CustomerPublic, dependencies=[Depends(require_permission("recycle.read"))])
def get_deleted_customer(customer_id: int, db: Session = Depends(get_db)) -> CustomerPublic:
    row = db.get(Customer, customer_id)
    if not row or row.is_active:
        raise HTTPException(404, "deleted customer not found")
    return customer_public(row, db)


@router.get("/vendors/{vendor_id}", response_model=VendorPublic, dependencies=[Depends(require_permission("recycle.read"))])
def get_deleted_vendor(vendor_id: int, db: Session = Depends(get_db)) -> VendorPublic:
    row = db.get(Vendor, vendor_id)
    if not row or row.is_active:
        raise HTTPException(404, "deleted vendor not found")
    return vendor_public(row, db)


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


@router.get("/catalog-products/{product_id}", response_model=CatalogProductPublic, dependencies=[Depends(require_permission("recycle.read"))])
def get_deleted_catalog_product(product_id: int, db: Session = Depends(get_db)) -> CatalogProductPublic:
    row = db.get(CatalogProduct, product_id)
    if not row or row.is_active:
        raise HTTPException(404, "deleted product not found")
    return catalog_public(row, db)


@router.get("/addons/{addon_id}", response_model=AddonPublic, dependencies=[Depends(require_permission("recycle.read"))])
def get_deleted_addon(addon_id: int, db: Session = Depends(get_db)) -> AddonPublic:
    row = db.get(AddonProduct, addon_id)
    if not row or row.is_active:
        raise HTTPException(404, "deleted addon not found")
    return addon_public(row, db)


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


@router.delete("/routes/{route_id}", dependencies=[Depends(require_permission("recycle.write"))])
def purge_route(route_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permission("recycle.write"))) -> dict:
    row = db.get(Route, route_id)
    if not row or row.is_active:
        raise HTTPException(404, "deleted route not found")
    log_from_auth(db, auth, action="purge", entity_type="route", entity_id=row.id, entity_label=row.name)
    db.delete(row)
    db.commit()
    return {"ok": True, "message": "route permanently deleted"}


@router.delete("/cities/{city_id}", dependencies=[Depends(require_permission("recycle.write"))])
def purge_city(city_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permission("recycle.write"))) -> dict:
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


@router.delete("/customers/{customer_id}", dependencies=[Depends(require_permission("recycle.write"))])
def purge_customer(customer_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permission("recycle.write"))) -> dict:
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


@router.delete("/vendors/{vendor_id}", dependencies=[Depends(require_permission("recycle.write"))])
def purge_vendor(vendor_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permission("recycle.write"))) -> dict:
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


@router.delete("/catalog-products/{product_id}", dependencies=[Depends(require_permission("recycle.write"))])
def purge_catalog_product(product_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permission("recycle.write"))) -> dict:
    row = db.get(CatalogProduct, product_id)
    if not row or row.is_active:
        raise HTTPException(404, "deleted product not found")
    db.query(CatalogAlternative).filter(
        (CatalogAlternative.product_id == product_id) | (CatalogAlternative.alternative_product_id == product_id)
    ).delete(synchronize_session=False)
    db.query(CatalogAddonLink).filter(CatalogAddonLink.catalog_product_id == product_id).delete(synchronize_session=False)
    if row.image_keys:
        delete_keys(row.image_keys)
    log_from_auth(db, auth, action="purge", entity_type="catalog", entity_id=row.id, entity_label=row.our_product_id)
    db.delete(row)
    db.commit()
    return {"ok": True, "message": "product permanently deleted"}


@router.delete("/addons/{addon_id}", dependencies=[Depends(require_permission("recycle.write"))])
def purge_addon(addon_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permission("recycle.write"))) -> dict:
    row = db.get(AddonProduct, addon_id)
    if not row or row.is_active:
        raise HTTPException(404, "deleted addon not found")
    db.query(CatalogAddonLink).filter(CatalogAddonLink.addon_product_id == addon_id).delete(synchronize_session=False)
    if row.image_keys:
        delete_keys(row.image_keys)
    log_from_auth(db, auth, action="purge", entity_type="addon", entity_id=row.id, entity_label=row.our_product_id)
    db.delete(row)
    db.commit()
    return {"ok": True, "message": "addon permanently deleted"}


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


@router.delete("/staff/{staff_id}", dependencies=[Depends(require_admin)])
def purge_staff(staff_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)) -> dict:
    row = db.get(Staff, staff_id)
    if not row or row.is_active:
        raise HTTPException(404, "deleted staff not found")
    log_from_auth(db, auth, action="purge", entity_type="staff", entity_id=row.id, entity_label=row.name)
    db.delete(row)
    db.commit()
    return {"ok": True, "message": "staff permanently deleted"}


@router.post("/receipts/{receipt_id}/restore", dependencies=[Depends(require_admin)])
def restore_receipt_endpoint(receipt_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)) -> dict:
    from app.services import response_cache

    result = restore_receipt(db, auth, receipt_id)
    response_cache.invalidate("stock:")
    response_cache.invalidate("shop:")
    return result


@router.delete("/receipts/{receipt_id}", dependencies=[Depends(require_admin)])
def purge_receipt_endpoint(receipt_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)) -> dict:
    from app.services import response_cache

    result = purge_receipt(db, auth, receipt_id)
    response_cache.invalidate("stock:")
    return result


@router.post("/debit-notes/{note_id}/restore", dependencies=[Depends(require_admin)])
def restore_debit_note_endpoint(note_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)) -> dict:
    from app.services import response_cache

    result = restore_debit_note(db, auth, note_id)
    response_cache.invalidate("stock:")
    return result


@router.delete("/debit-notes/{note_id}", dependencies=[Depends(require_admin)])
def purge_debit_note_endpoint(note_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)) -> dict:
    from app.services import response_cache

    result = purge_debit_note(db, auth, note_id)
    response_cache.invalidate("stock:")
    return result
