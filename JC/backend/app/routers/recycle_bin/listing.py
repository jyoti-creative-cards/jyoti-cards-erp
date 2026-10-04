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
    cbill_rows = (
        db.query(CustomerBill).filter(CustomerBill.deleted_at.isnot(None)).order_by(CustomerBill.deleted_at.desc()).all()
    )
    cplacement_rows = (
        db.query(CustomerOrderPlacement)
        .filter(CustomerOrderPlacement.deleted_at.isnot(None))
        .order_by(CustomerOrderPlacement.deleted_at.desc())
        .all()
    )
    cret_rows = (
        db.query(CustomerReturn).filter(CustomerReturn.deleted_at.isnot(None)).order_by(CustomerReturn.deleted_at.desc()).all()
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

    from app.models.customer_order import CustomerOrder

    placement_order_ids = {p.customer_order_id for p in cplacement_rows}
    placement_orders = (
        {o.id: o.customer_id for o in db.query(CustomerOrder).filter(CustomerOrder.id.in_(placement_order_ids)).all()}
        if placement_order_ids else {}
    )
    customer_ids_for_notes = (
        {b.customer_id for b in cbill_rows}
        | {r.customer_id for r in cret_rows}
        | set(placement_orders.values())
    )
    customer_names = {
        c.id: c.business_name
        for c in (db.query(Customer).filter(Customer.id.in_(customer_ids_for_notes)).all() if customer_ids_for_notes else [])
    }
    customer_bills = [
        RecycleBinItem(
            type="customer_bill",
            id=b.id,
            name=f"Bill {b.bill_number} — {customer_names.get(b.customer_id, f'Customer #{b.customer_id}')}",
            subtitle=f"₹{b.grand_total}" + (f" — {b.deleted_reason}" if b.deleted_reason else ""),
            deleted_at=b.deleted_at,
        )
        for b in cbill_rows
    ]
    customer_placements = [
        RecycleBinItem(
            type="customer_placement",
            id=p.id,
            name=f"Order #{p.id} — {customer_names.get(placement_orders.get(p.customer_order_id), f'Order #{p.id}')}",
            subtitle=p.deleted_reason or p.customer_notes,
            deleted_at=p.deleted_at,
        )
        for p in cplacement_rows
    ]
    customer_returns = [
        RecycleBinItem(
            type="customer_return",
            id=r.id,
            name=f"Return {r.return_number} — {customer_names.get(r.customer_id, f'Customer #{r.customer_id}')}",
            subtitle=f"Credit ₹{r.credit_amount}" + (f" — {r.deleted_reason}" if r.deleted_reason else ""),
            deleted_at=r.deleted_at,
        )
        for r in cret_rows
    ]

    total = (
        len(routes) + len(cities) + len(customers) + len(vendors) + len(catalog_products) + len(addons) + len(staff)
        + len(receipts) + len(debit_notes) + len(customer_bills) + len(customer_placements) + len(customer_returns)
    )
    return RecycleBinList(
        routes=routes, cities=cities, customers=customers, vendors=vendors, catalog_products=catalog_products,
        addons=addons, staff=staff, receipts=receipts, debit_notes=debit_notes,
        customer_bills=customer_bills, customer_placements=customer_placements, customer_returns=customer_returns,
        total=total,
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

@router.get("/catalog-products/{product_id}", response_model=CatalogProductPublic, dependencies=[Depends(require_permission("recycle.read"))])
def get_deleted_catalog_product(product_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(get_auth_context)) -> CatalogProductPublic:
    row = db.get(CatalogProduct, product_id)
    if not row or row.is_active:
        raise HTTPException(404, "deleted product not found")
    return catalog_public(row, db, auth=auth)

@router.get("/addons/{addon_id}", response_model=AddonPublic, dependencies=[Depends(require_permission("recycle.read"))])
def get_deleted_addon(addon_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(get_auth_context)) -> AddonPublic:
    row = db.get(AddonProduct, addon_id)
    if not row or row.is_active:
        raise HTTPException(404, "deleted addon not found")
    return addon_public(row, db, auth=auth)
