"""Routes and Cities CRUD."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import require_admin
from app.models.city import City
from app.models.route import Route

router = APIRouter(prefix="/routes", tags=["routes"])
city_router = APIRouter(prefix="/cities", tags=["cities"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class RouteIn(BaseModel):
    name: str
    notes: Optional[str] = None

class RoutePublic(BaseModel):
    id: int
    name: str
    notes: Optional[str] = None
    is_active: bool
    model_config = {"from_attributes": True}

class CityIn(BaseModel):
    name: Optional[str] = None
    route_id: Optional[int] = None

class CityPublic(BaseModel):
    id: int
    name: str
    route_id: Optional[int] = None
    is_active: bool
    model_config = {"from_attributes": True}


# ── Route endpoints ───────────────────────────────────────────────────────────

@router.get("", response_model=List[RoutePublic], dependencies=[Depends(require_admin)])
def list_routes(db: Session = Depends(get_db)):
    return db.query(Route).filter(Route.is_active.is_(True)).order_by(Route.name).all()


@router.post("", response_model=RoutePublic, status_code=201, dependencies=[Depends(require_admin)])
def create_route(body: RouteIn, db: Session = Depends(get_db)):
    row = Route(name=body.name.strip(), notes=(body.notes or "").strip() or None)
    db.add(row); db.commit(); db.refresh(row)
    return row


@router.patch("/{route_id}", response_model=RoutePublic, dependencies=[Depends(require_admin)])
def update_route(route_id: int, body: RouteIn, db: Session = Depends(get_db)):
    row = db.get(Route, route_id)
    if not row:
        raise HTTPException(404, "route not found")
    row.name = body.name.strip()
    row.notes = (body.notes or "").strip() or None
    db.commit(); db.refresh(row)
    return row


@router.delete("/{route_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_route(route_id: int, db: Session = Depends(get_db)):
    row = db.get(Route, route_id)
    if row:
        row.is_active = False
        db.commit()


# ── City endpoints ────────────────────────────────────────────────────────────

@city_router.get("", response_model=List[CityPublic], dependencies=[Depends(require_admin)])
def list_cities(route_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(City).filter(City.is_active.is_(True))
    if route_id:
        q = q.filter(City.route_id == route_id)
    return q.order_by(City.name).all()


@city_router.post("", response_model=CityPublic, status_code=201, dependencies=[Depends(require_admin)])
def create_city(body: CityIn, db: Session = Depends(get_db)):
    if not body.name or not body.name.strip():
        raise HTTPException(400, "name required")
    row = City(name=body.name.strip(), route_id=body.route_id)
    db.add(row); db.commit(); db.refresh(row)
    return row


@city_router.patch("/{city_id}", response_model=CityPublic, dependencies=[Depends(require_admin)])
def update_city(city_id: int, body: CityIn, db: Session = Depends(get_db)):
    row = db.get(City, city_id)
    if not row:
        raise HTTPException(404, "city not found")
    if body.name is not None:
        row.name = body.name.strip()
    row.route_id = body.route_id
    db.commit(); db.refresh(row)
    return row


@city_router.delete("/{city_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_city(city_id: int, db: Session = Depends(get_db)):
    row = db.get(City, city_id)
    if row:
        row.is_active = False
        db.commit()
