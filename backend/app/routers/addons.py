"""Add-on products API — create add-ons, link to cards, adjust stock."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import require_admin
from app.models.addon_product import AddonProduct, AddonStock, CatalogProductAddon
from app.models.catalog_product import CatalogProduct

router = APIRouter(prefix="/addons", tags=["addons"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class AddonProductIn(BaseModel):
    name: str
    description: Optional[str] = None
    unit: str = "pcs"


class AddonProductPublic(BaseModel):
    id: int
    name: str
    description: Optional[str]
    unit: str
    stock: int


class AddonLinkIn(BaseModel):
    catalog_product_id: int
    addon_product_id: int
    quantity_per_card: int = 1


class AddonLinkPublic(BaseModel):
    id: int
    catalog_product_id: int
    catalog_product_name: str
    addon_product_id: int
    addon_product_name: str
    quantity_per_card: int


class AddonStockAdjustIn(BaseModel):
    addon_product_id: int
    delta: int   # positive = receive stock, negative = remove


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_stock(db: Session, addon_id: int) -> int:
    row = db.get(AddonStock, addon_id)
    return row.quantity if row else 0


def _to_public(addon: AddonProduct, db: Session) -> AddonProductPublic:
    return AddonProductPublic(
        id=addon.id,
        name=addon.name,
        description=addon.description,
        unit=addon.unit,
        stock=_get_stock(db, addon.id),
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=List[AddonProductPublic], dependencies=[Depends(require_admin)])
def list_addons(db: Session = Depends(get_db)):
    rows = db.query(AddonProduct).filter(AddonProduct.is_active.is_(True)).all()
    return [_to_public(r, db) for r in rows]


@router.post("", response_model=AddonProductPublic, status_code=201, dependencies=[Depends(require_admin)])
def create_addon(body: AddonProductIn, db: Session = Depends(get_db)):
    addon = AddonProduct(name=body.name, description=body.description, unit=body.unit)
    db.add(addon)
    db.commit()
    db.refresh(addon)
    return _to_public(addon, db)


@router.delete("/{addon_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_addon(addon_id: int, db: Session = Depends(get_db)):
    addon = db.get(AddonProduct, addon_id)
    if not addon:
        raise HTTPException(404, "not found")
    addon.is_active = False
    db.commit()


# ── Stock ─────────────────────────────────────────────────────────────────────

@router.post("/stock-adjust", status_code=200, dependencies=[Depends(require_admin)])
def adjust_stock(body: AddonStockAdjustIn, db: Session = Depends(get_db)):
    """Add or remove stock for an add-on."""
    addon = db.get(AddonProduct, body.addon_product_id)
    if not addon:
        raise HTTPException(404, "add-on not found")
    row = db.get(AddonStock, body.addon_product_id)
    if row is None:
        row = AddonStock(addon_product_id=body.addon_product_id, quantity=0)
        db.add(row)
    new_qty = row.quantity + body.delta
    if new_qty < 0:
        raise HTTPException(400, f"insufficient stock (current={row.quantity})")
    row.quantity = new_qty
    db.commit()
    return {"addon_product_id": body.addon_product_id, "quantity": new_qty}


# ── Links (card ↔ add-on) ─────────────────────────────────────────────────────

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
            quantity_per_card=r.quantity_per_card,
        ))
    return result


@router.post("/links", response_model=AddonLinkPublic, status_code=201, dependencies=[Depends(require_admin)])
def create_link(body: AddonLinkIn, db: Session = Depends(get_db)):
    prod = db.get(CatalogProduct, body.catalog_product_id)
    if not prod:
        raise HTTPException(404, "catalog product not found")
    addon = db.get(AddonProduct, body.addon_product_id)
    if not addon:
        raise HTTPException(404, "add-on not found")
    link = CatalogProductAddon(
        catalog_product_id=body.catalog_product_id,
        addon_product_id=body.addon_product_id,
        quantity_per_card=body.quantity_per_card,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return AddonLinkPublic(
        id=link.id,
        catalog_product_id=link.catalog_product_id,
        catalog_product_name=prod.name,
        addon_product_id=link.addon_product_id,
        addon_product_name=addon.name,
        quantity_per_card=link.quantity_per_card,
    )


@router.delete("/links/{link_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_link(link_id: int, db: Session = Depends(get_db)):
    link = db.get(CatalogProductAddon, link_id)
    if not link:
        raise HTTPException(404, "not found")
    db.delete(link)
    db.commit()
