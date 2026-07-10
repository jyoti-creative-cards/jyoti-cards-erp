from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import AuthContext, get_auth_context, require_permission
from app.models.city import City
from app.models.customer import Customer
from app.models.route import Route
from app.schemas.customer import (
    CityDetail,
    CityIn,
    CityPublic,
    CityUpdate,
    RouteDetail,
    RouteIn,
    RoutePublic,
    RouteUpdate,
)

router = APIRouter(prefix="/routes", tags=["routes"])
city_router = APIRouter(prefix="/cities", tags=["cities"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _route_public(row: Route, db: Session, *, include_deleted: bool = False) -> RoutePublic:
    city_q = db.query(func.count(City.id)).filter(City.route_id == row.id)
    cust_q = db.query(func.count(Customer.id)).filter(Customer.route_id == row.id)
    if not include_deleted:
        city_q = city_q.filter(City.is_active.is_(True))
        cust_q = cust_q.filter(Customer.is_active.is_(True))
    return RoutePublic(
        id=row.id,
        name=row.name,
        notes=row.notes,
        is_active=row.is_active,
        city_count=city_q.scalar() or 0,
        customer_count=cust_q.scalar() or 0,
        deleted_at=row.deleted_at,
        created_at=row.created_at,
    )


def _city_public(row: City, db: Session, *, include_deleted_customers: bool = False) -> CityPublic:
    route_name = None
    if row.route_id:
        r = db.get(Route, row.route_id)
        route_name = r.name if r else None
    cust_q = db.query(func.count(Customer.id)).filter(Customer.city_id == row.id)
    if not include_deleted_customers:
        cust_q = cust_q.filter(Customer.is_active.is_(True))
    return CityPublic(
        id=row.id,
        name=row.name,
        route_id=row.route_id,
        route_name=route_name,
        is_active=row.is_active,
        customer_count=cust_q.scalar() or 0,
        deleted_at=row.deleted_at,
        created_at=row.created_at,
    )


@router.get("", response_model=List[RoutePublic], dependencies=[Depends(require_permission("setup.read"))])
def list_routes(db: Session = Depends(get_db)) -> List[RoutePublic]:
    rows = db.query(Route).filter(Route.is_active.is_(True)).order_by(Route.name).all()
    return [_route_public(r, db) for r in rows]


@router.get("/{route_id}", response_model=RouteDetail, dependencies=[Depends(require_permission("setup.read"))])
def get_route(route_id: int, db: Session = Depends(get_db)) -> RouteDetail:
    row = db.get(Route, route_id)
    if not row:
        raise HTTPException(404, "route not found")
    pub = _route_public(row, db, include_deleted=not row.is_active)
    city_rows = db.query(City).filter(City.route_id == route_id).order_by(City.name).all()
    if row.is_active:
        city_rows = [c for c in city_rows if c.is_active]
    cities = [_city_public(c, db) for c in city_rows]
    return RouteDetail(**pub.model_dump(), cities=cities)


@router.post("", response_model=RoutePublic, status_code=201, dependencies=[Depends(require_permission("setup.write"))])
def create_route(body: RouteIn, db: Session = Depends(get_db)) -> RoutePublic:
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "name required")
    row = Route(name=name, notes=(body.notes or "").strip() or None)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "route name already exists") from None
    db.refresh(row)
    return _route_public(row, db)


@router.patch("/{route_id}", response_model=RoutePublic, dependencies=[Depends(require_permission("setup.write"))])
def update_route(route_id: int, body: RouteUpdate, db: Session = Depends(get_db)) -> RoutePublic:
    row = db.get(Route, route_id)
    if not row or not row.is_active:
        raise HTTPException(404, "route not found")
    data = body.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(400, "no fields to update")
    if "name" in data and data["name"]:
        row.name = data["name"].strip()
    if "notes" in data:
        row.notes = (data["notes"] or "").strip() or None
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "route name already exists") from None
    db.refresh(row)
    return _route_public(row, db)


@router.delete("/{route_id}", status_code=204, dependencies=[Depends(require_permission("setup.write"))])
def delete_route(route_id: int, db: Session = Depends(get_db)) -> None:
    row = db.get(Route, route_id)
    if not row or not row.is_active:
        raise HTTPException(404, "route not found")
    row.is_active = False
    row.deleted_at = _now()
    db.commit()


@city_router.get("", response_model=List[CityPublic], dependencies=[Depends(require_permission("setup.read"))])
def list_cities(route_id: Optional[int] = None, db: Session = Depends(get_db)) -> List[CityPublic]:
    q = db.query(City).filter(City.is_active.is_(True))
    if route_id:
        q = q.filter(City.route_id == route_id)
    return [_city_public(r, db) for r in q.order_by(City.name).all()]


@city_router.get("/{city_id}", response_model=CityDetail, dependencies=[Depends(require_permission("setup.read"))])
def get_city(city_id: int, db: Session = Depends(get_db)) -> CityDetail:
    from app.routers.customers import _to_public as customer_public

    row = db.get(City, city_id)
    if not row:
        raise HTTPException(404, "city not found")
    pub = _city_public(row, db, include_deleted_customers=not row.is_active)
    cust_q = db.query(Customer).filter(Customer.city_id == city_id)
    if row.is_active:
        cust_q = cust_q.filter(Customer.is_active.is_(True))
    customers = [customer_public(c, db) for c in cust_q.order_by(Customer.business_name).all()]
    return CityDetail(**pub.model_dump(), customers=customers)


@city_router.post("", response_model=CityPublic, status_code=201, dependencies=[Depends(require_permission("setup.write"))])
def create_city(body: CityIn, db: Session = Depends(get_db)) -> CityPublic:
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "name required")
    if body.route_id:
        route = db.get(Route, body.route_id)
        if not route or not route.is_active:
            raise HTTPException(400, "route not found")
    row = City(name=name, route_id=body.route_id)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "city name already exists") from None
    db.refresh(row)
    return _city_public(row, db)


@city_router.patch("/{city_id}", response_model=CityPublic, dependencies=[Depends(require_permission("setup.write"))])
def update_city(city_id: int, body: CityUpdate, db: Session = Depends(get_db)) -> CityPublic:
    row = db.get(City, city_id)
    if not row or not row.is_active:
        raise HTTPException(404, "city not found")
    data = body.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(400, "no fields to update")
    if "name" in data and data["name"]:
        row.name = data["name"].strip()
    if "route_id" in data:
        rid = data["route_id"]
        if rid:
            route = db.get(Route, rid)
            if not route or not route.is_active:
                raise HTTPException(400, "route not found")
        row.route_id = rid
        db.query(Customer).filter(Customer.city_id == city_id, Customer.is_active.is_(True)).update({"route_id": rid})
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "city name already exists") from None
    db.refresh(row)
    return _city_public(row, db)


@city_router.delete("/{city_id}", status_code=204, dependencies=[Depends(require_permission("setup.write"))])
def delete_city(city_id: int, db: Session = Depends(get_db)) -> None:
    row = db.get(City, city_id)
    if not row or not row.is_active:
        raise HTTPException(404, "city not found")
    row.is_active = False
    row.deleted_at = _now()
    db.commit()
