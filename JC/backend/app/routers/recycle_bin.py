from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import AuthContext, get_auth_context, require_admin, require_permission
from app.models.addon_product import AddonProduct
from app.models.catalog_addon_link import CatalogAddonLink
from app.models.catalog_alternative import CatalogAlternative
from app.models.catalog_product import CatalogProduct
from app.models.city import City
from app.models.customer import Customer
from app.models.route import Route
from app.models.staff import Staff
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
    total = len(routes) + len(cities) + len(customers) + len(vendors) + len(catalog_products) + len(addons) + len(staff)
    return RecycleBinList(routes=routes, cities=cities, customers=customers, vendors=vendors, catalog_products=catalog_products, addons=addons, staff=staff, total=total)


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
def restore_route(route_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(Route, route_id)
    if not row or row.is_active:
        raise HTTPException(404, "deleted route not found")
    if db.query(Route).filter(Route.name == row.name, Route.is_active.is_(True), Route.id != route_id).first():
        raise HTTPException(409, "an active route with this name already exists")
    row.is_active = True
    row.deleted_at = None
    db.commit()
    return {"ok": True, "message": "route restored"}


@router.post("/cities/{city_id}/restore", dependencies=[Depends(require_permission("recycle.write"))])
def restore_city(city_id: int, db: Session = Depends(get_db)) -> dict:
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
    db.commit()
    return {"ok": True, "message": "city restored"}


@router.post("/customers/{customer_id}/restore", dependencies=[Depends(require_permission("recycle.write"))])
def restore_customer(customer_id: int, db: Session = Depends(get_db)) -> dict:
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
    db.commit()
    return {"ok": True, "message": "customer restored"}


@router.post("/vendors/{vendor_id}/restore", dependencies=[Depends(require_permission("recycle.write"))])
def restore_vendor(vendor_id: int, db: Session = Depends(get_db)) -> dict:
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
def restore_catalog_product(product_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(CatalogProduct, product_id)
    if not row or row.is_active:
        raise HTTPException(404, "deleted product not found")
    if db.query(CatalogProduct).filter(CatalogProduct.our_product_id == row.our_product_id, CatalogProduct.is_active.is_(True), CatalogProduct.id != product_id).first():
        raise HTTPException(409, "active product with same our_product_id exists")
    vendor = db.get(Vendor, row.vendor_id)
    if not vendor or not vendor.is_active or vendor.deleted_at:
        raise HTTPException(400, "linked vendor is deleted — restore vendor first")
    row.is_active = True
    row.deleted_at = None
    db.commit()
    return {"ok": True, "message": "product restored"}


@router.post("/addons/{addon_id}/restore", dependencies=[Depends(require_permission("recycle.write"))])
def restore_addon(addon_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(AddonProduct, addon_id)
    if not row or row.is_active:
        raise HTTPException(404, "deleted addon not found")
    if db.query(AddonProduct).filter(AddonProduct.our_product_id == row.our_product_id, AddonProduct.is_active.is_(True), AddonProduct.id != addon_id).first():
        raise HTTPException(409, "active addon with same our_product_id exists")
    row.is_active = True
    row.deleted_at = None
    db.commit()
    return {"ok": True, "message": "addon restored"}


@router.delete("/routes/{route_id}", dependencies=[Depends(require_permission("recycle.write"))])
def purge_route(route_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(Route, route_id)
    if not row or row.is_active:
        raise HTTPException(404, "deleted route not found")
    db.delete(row)
    db.commit()
    return {"ok": True, "message": "route permanently deleted"}


@router.delete("/cities/{city_id}", dependencies=[Depends(require_permission("recycle.write"))])
def purge_city(city_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(City, city_id)
    if not row or row.is_active:
        raise HTTPException(404, "deleted city not found")
    vend_n = db.query(Vendor).filter(Vendor.city_id == city_id).count()
    cust_n = db.query(Customer).filter(Customer.city_id == city_id).count()
    if vend_n or cust_n:
        raise HTTPException(400, f"city still linked to {vend_n} vendor(s) and {cust_n} customer(s) — purge those first")
    db.delete(row)
    db.commit()
    return {"ok": True, "message": "city permanently deleted"}


@router.delete("/customers/{customer_id}", dependencies=[Depends(require_permission("recycle.write"))])
def purge_customer(customer_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(Customer, customer_id)
    if not row or row.is_active:
        raise HTTPException(404, "deleted customer not found")
    db.delete(row)
    db.commit()
    return {"ok": True, "message": "customer permanently deleted"}


@router.delete("/vendors/{vendor_id}", dependencies=[Depends(require_permission("recycle.write"))])
def purge_vendor(vendor_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(Vendor, vendor_id)
    if not row or row.is_active:
        raise HTTPException(404, "deleted vendor not found")
    cat_n = db.query(CatalogProduct).filter(CatalogProduct.vendor_id == vendor_id).count()
    addon_n = db.query(AddonProduct).filter(AddonProduct.vendor_id == vendor_id).count()
    if cat_n or addon_n:
        raise HTTPException(400, f"vendor still has {cat_n} catalog and {addon_n} addon product(s) — purge those first")
    db.delete(row)
    db.commit()
    return {"ok": True, "message": "vendor permanently deleted"}


@router.delete("/catalog-products/{product_id}", dependencies=[Depends(require_permission("recycle.write"))])
def purge_catalog_product(product_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(CatalogProduct, product_id)
    if not row or row.is_active:
        raise HTTPException(404, "deleted product not found")
    db.query(CatalogAlternative).filter(
        (CatalogAlternative.product_id == product_id) | (CatalogAlternative.alternative_product_id == product_id)
    ).delete(synchronize_session=False)
    db.query(CatalogAddonLink).filter(CatalogAddonLink.catalog_product_id == product_id).delete(synchronize_session=False)
    if row.image_keys:
        delete_keys(row.image_keys)
    db.delete(row)
    db.commit()
    return {"ok": True, "message": "product permanently deleted"}


@router.delete("/addons/{addon_id}", dependencies=[Depends(require_permission("recycle.write"))])
def purge_addon(addon_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(AddonProduct, addon_id)
    if not row or row.is_active:
        raise HTTPException(404, "deleted addon not found")
    db.query(CatalogAddonLink).filter(CatalogAddonLink.addon_product_id == addon_id).delete(synchronize_session=False)
    if row.image_keys:
        delete_keys(row.image_keys)
    db.delete(row)
    db.commit()
    return {"ok": True, "message": "addon permanently deleted"}


@router.post("/staff/{staff_id}/restore", dependencies=[Depends(require_admin)])
def restore_staff(staff_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(Staff, staff_id)
    if not row or row.is_active:
        raise HTTPException(404, "deleted staff not found")
    if db.query(Staff).filter(Staff.phone == row.phone, Staff.is_active.is_(True), Staff.id != staff_id).first():
        raise HTTPException(409, "an active staff with this phone already exists")
    row.is_active = True
    row.deleted_at = None
    db.commit()
    return {"ok": True, "message": "staff restored"}


@router.delete("/staff/{staff_id}", dependencies=[Depends(require_admin)])
def purge_staff(staff_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(Staff, staff_id)
    if not row or row.is_active:
        raise HTTPException(404, "deleted staff not found")
    db.delete(row)
    db.commit()
    return {"ok": True, "message": "staff permanently deleted"}
