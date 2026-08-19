"""Add-on products API — full catalog-like CRUD for add-on items + product linking.

IMPORTANT: Static-path routes (/links, /stock-adjust, /recycle-bin) MUST be
registered before the parameterized /{addon_id} routes to avoid FastAPI matching
"links" or "stock-adjust" as an addon_id integer and returning 422.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import require_admin
from app.models.addon_product import AddonProduct, AddonStock, CatalogProductAddon
from app.models.catalog_product import CatalogProduct
from app.models.vendor import Vendor

router = APIRouter(prefix="/addons", tags=["addons"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class AddonProductCreate(BaseModel):
    our_product_id: str = Field(..., min_length=1, max_length=120)
    vendor_id: int = Field(..., ge=1)
    vendor_product_id: str = Field(..., min_length=1, max_length=255)
    name: str = Field(..., min_length=1, max_length=300)
    description: Optional[str] = Field(None, max_length=1000)
    category: Optional[str] = Field(None, max_length=120)
    unit: str = Field(default="pcs", max_length=50)
    buying_price: float = Field(..., ge=0)


class AddonProductUpdate(BaseModel):
    our_product_id: Optional[str] = Field(None, min_length=1, max_length=120)
    vendor_id: Optional[int] = Field(None, ge=1)
    vendor_product_id: Optional[str] = Field(None, min_length=1, max_length=255)
    name: Optional[str] = Field(None, min_length=1, max_length=300)
    description: Optional[str] = Field(None, max_length=1000)
    category: Optional[str] = Field(None, max_length=120)
    unit: Optional[str] = Field(None, max_length=50)
    buying_price: Optional[float] = Field(None, ge=0)


class AddonProductPublic(BaseModel):
    id: int
    our_product_id: str
    vendor_id: int
    vendor_product_id: str
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    unit: str
    buying_price: float
    stock: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AddonLinkIn(BaseModel):
    catalog_product_id: int = Field(..., ge=1)
    addon_product_id: int = Field(..., ge=1)
    quantity_per_unit: int = Field(default=1, ge=1)


class AddonLinkPublic(BaseModel):
    id: int
    catalog_product_id: int
    catalog_product_name: str
    addon_product_id: int
    addon_product_name: str
    quantity_per_unit: int


class AddonStockAdjustIn(BaseModel):
    addon_product_id: int
    delta: int


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_stock(db: Session, addon_id: int) -> int:
    row = db.get(AddonStock, addon_id)
    return row.quantity if row else 0


def _to_public(addon: AddonProduct, db: Session) -> AddonProductPublic:
    bp = addon.buying_price
    return AddonProductPublic(
        id=addon.id,
        our_product_id=addon.our_product_id or "",
        vendor_id=addon.vendor_id or 0,
        vendor_product_id=addon.vendor_product_id or "",
        name=addon.name,
        description=addon.description,
        category=addon.category,
        unit=addon.unit,
        buying_price=float(bp) if bp is not None else 0.0,
        stock=_get_stock(db, addon.id),
        created_at=addon.created_at,
        updated_at=addon.updated_at,
    )


# ── Static-path routes FIRST (must precede /{addon_id}) ──────────────────────

@router.get("", response_model=List[AddonProductPublic], dependencies=[Depends(require_admin)])
def list_addons(
    q: Optional[str] = None,
    vendor_id: Optional[int] = None,
    deleted: bool = Query(False),
    db: Session = Depends(get_db),
):
    query = db.query(AddonProduct)
    if deleted:
        query = query.filter(AddonProduct.deleted_at.isnot(None))
    else:
        query = query.filter(AddonProduct.deleted_at.is_(None), AddonProduct.is_active.is_(True))
    if vendor_id:
        query = query.filter(AddonProduct.vendor_id == vendor_id)
    if q and q.strip():
        term = f"%{q.strip()}%"
        from sqlalchemy import or_
        query = query.filter(
            or_(
                AddonProduct.name.ilike(term),
                AddonProduct.our_product_id.ilike(term),
                AddonProduct.vendor_product_id.ilike(term),
            )
        )
    rows = query.order_by(AddonProduct.id.asc()).all()
    return [_to_public(r, db) for r in rows]


@router.post("", response_model=AddonProductPublic, status_code=201, dependencies=[Depends(require_admin)])
def create_addon(body: AddonProductCreate, db: Session = Depends(get_db)):
    vend = db.get(Vendor, body.vendor_id)
    if vend is None or vend.deleted_at is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "vendor not found or inactive")
    addon = AddonProduct(
        our_product_id=body.our_product_id.strip(),
        vendor_id=body.vendor_id,
        vendor_product_id=body.vendor_product_id.strip(),
        name=body.name.strip(),
        description=body.description,
        category=body.category.strip() if body.category else None,
        unit=body.unit or "pcs",
        buying_price=Decimal(str(body.buying_price)),
    )
    db.add(addon)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        err = str(e.orig) if getattr(e, "orig", None) else ""
        if "uq_addon_our_product_id" in err or "our_product_id" in err:
            raise HTTPException(status.HTTP_409_CONFLICT, "our_product_id already in use") from None
        raise HTTPException(status.HTTP_409_CONFLICT, "duplicate add-on") from None
    db.refresh(addon)
    return _to_public(addon, db)


@router.get("/links", response_model=List[AddonLinkPublic], dependencies=[Depends(require_admin)])
def list_links(catalog_product_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(CatalogProductAddon)
    if catalog_product_id:
        q = q.filter(CatalogProductAddon.catalog_product_id == catalog_product_id)
    rows = q.all()
    result = []
    for r in rows:
        prod = db.get(CatalogProduct, r.catalog_product_id)
        addon = db.get(AddonProduct, r.addon_product_id)
        result.append(AddonLinkPublic(
            id=r.id,
            catalog_product_id=r.catalog_product_id,
            catalog_product_name=prod.name if prod else "",
            addon_product_id=r.addon_product_id,
            addon_product_name=addon.name if addon else "",
            quantity_per_unit=r.quantity_per_unit,
        ))
    return result


@router.post("/links", response_model=AddonLinkPublic, status_code=201, dependencies=[Depends(require_admin)])
def create_link(body: AddonLinkIn, db: Session = Depends(get_db)):
    prod = db.get(CatalogProduct, body.catalog_product_id)
    if not prod or prod.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "catalog product not found")
    addon = db.get(AddonProduct, body.addon_product_id)
    if not addon or addon.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "add-on not found")
    existing = db.query(CatalogProductAddon).filter_by(
        catalog_product_id=body.catalog_product_id,
        addon_product_id=body.addon_product_id,
    ).first()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "add-on already linked to this product")
    link = CatalogProductAddon(
        catalog_product_id=body.catalog_product_id,
        addon_product_id=body.addon_product_id,
        quantity_per_unit=body.quantity_per_unit,
    )
    db.add(link)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "add-on already linked to this product")
    db.refresh(link)
    return AddonLinkPublic(
        id=link.id,
        catalog_product_id=link.catalog_product_id,
        catalog_product_name=prod.name,
        addon_product_id=link.addon_product_id,
        addon_product_name=addon.name,
        quantity_per_unit=link.quantity_per_unit,
    )


@router.delete("/links/{link_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_link(link_id: int, db: Session = Depends(get_db)):
    link = db.get(CatalogProductAddon, link_id)
    if not link:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "link not found")
    db.delete(link)
    db.commit()


@router.post("/stock-adjust", status_code=200, dependencies=[Depends(require_admin)])
def adjust_stock(body: AddonStockAdjustIn, db: Session = Depends(get_db)):
    addon = db.get(AddonProduct, body.addon_product_id)
    if not addon or addon.deleted_at is not None or not addon.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "add-on not found or inactive")
    row = db.get(AddonStock, body.addon_product_id)
    if row is None:
        row = AddonStock(addon_product_id=body.addon_product_id, quantity=0)
        db.add(row)
    new_qty = row.quantity + body.delta
    if new_qty < 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"insufficient stock (current={row.quantity})")
    row.quantity = new_qty
    db.commit()
    return {"addon_product_id": body.addon_product_id, "quantity": new_qty}


# ── Parameterized /{addon_id} routes AFTER static routes ─────────────────────

@router.get("/{addon_id}", response_model=AddonProductPublic, dependencies=[Depends(require_admin)])
def get_addon(addon_id: int, db: Session = Depends(get_db)):
    addon = db.get(AddonProduct, addon_id)
    if addon is None or addon.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "add-on not found")
    return _to_public(addon, db)


@router.patch("/{addon_id}", response_model=AddonProductPublic, dependencies=[Depends(require_admin)])
def update_addon(addon_id: int, body: AddonProductUpdate, db: Session = Depends(get_db)):
    addon = db.get(AddonProduct, addon_id)
    if addon is None or addon.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "add-on not found")
    data = body.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no fields to update")
    if "vendor_id" in data:
        if db.get(Vendor, data["vendor_id"]) is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "vendor not found")
        addon.vendor_id = data.pop("vendor_id")
    for field, val in data.items():
        if field == "buying_price":
            addon.buying_price = Decimal(str(val)) if val is not None else Decimal("0")
        elif field in ("our_product_id", "vendor_product_id", "name"):
            setattr(addon, field, str(val).strip())
        elif field == "category":
            addon.category = val.strip() if val else None
        else:
            setattr(addon, field, val)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "duplicate our_product_id") from None
    db.refresh(addon)
    return _to_public(addon, db)


@router.post("/{addon_id}/restore", dependencies=[Depends(require_admin)])
def restore_addon(addon_id: int, db: Session = Depends(get_db)):
    addon = db.get(AddonProduct, addon_id)
    if addon is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "add-on not found")
    addon.deleted_at = None
    addon.is_active = True
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="cannot restore: our_product_id already in use by an active add-on",
        ) from None
    return {"ok": True, "id": addon_id}


@router.delete("/{addon_id}/permanent", dependencies=[Depends(require_admin)])
def permanent_delete_addon(addon_id: int, db: Session = Depends(get_db)):
    addon = db.get(AddonProduct, addon_id)
    if addon is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "add-on not found")
    db.delete(addon)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="cannot permanently delete: add-on is linked to catalog products; unlink first",
        ) from None
    return {"ok": True, "id": addon_id, "permanently_deleted": True}


@router.delete("/{addon_id}", dependencies=[Depends(require_admin)])
def delete_addon(addon_id: int, db: Session = Depends(get_db)):
    """Soft-delete: move to recycle bin."""
    addon = db.get(AddonProduct, addon_id)
    if addon is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "add-on not found")
    addon.deleted_at = datetime.now(timezone.utc)
    addon.is_active = False
    db.commit()
    return {"ok": True, "id": addon_id, "soft_deleted": True}
