from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import AuthContext, get_auth_context, require_permission
from app.models.addon_product import AddonProduct
from app.models.addon_stock_ledger import AddonStockLedger
from app.models.expense import Expense
from app.models.vendor import Vendor
from app.schemas.addon import (
    AddonAdjustStockIn, AddonCreate, AddonDetail, AddonPublic, AddonReceiveStockIn, AddonUpdate,
)
from app.services.activity import log_from_auth
from app.services.addon_stock import add_addon_stock
from app.services.cost_visibility import hide_cost, hide_cost_in_diff_summary, hide_cost_in_snapshot_json
from app.services.history import TRACKED_FIELDS, diff_summary, list_entity_history, list_price_history, record_entity_history, record_price_change, row_snapshot
from app.services.storage import presigned_urls

router = APIRouter(prefix="/addons", tags=["addons"])


def _stock_status(row: AddonProduct) -> str:
    qty = int(row.quantity_on_hand or 0)
    if qty < 0:
        return "negative_stock"
    if qty == 0:
        return "out_of_stock"
    if qty <= int(row.low_stock_threshold or 5):
        return "low_stock"
    return "in_stock"


def _to_public(row: AddonProduct, db: Session, *, auth: AuthContext) -> AddonPublic:
    v = db.get(Vendor, row.vendor_id)
    keys = row.image_keys or []
    return AddonPublic(
        id=row.id,
        our_product_id=row.our_product_id,
        vendor_id=row.vendor_id,
        vendor_name=v.business_name if v else None,
        vendor_product_id=row.vendor_product_id,
        name=row.name,
        description=row.description,
        category=row.category,
        unit=row.unit,
        buying_price=hide_cost(format(row.buying_price, "f"), auth),
        image_keys=keys,
        image_urls=presigned_urls(keys),
        quantity_on_hand=int(row.quantity_on_hand or 0),
        low_stock_threshold=int(row.low_stock_threshold or 5),
        stock_status=_stock_status(row),
        is_active=row.is_active,
        created_at=row.created_at,
        updated_at=row.updated_at,
        deleted_at=row.deleted_at,
    )


@router.get("", response_model=List[AddonPublic], dependencies=[Depends(require_permission("addons.read"))])
def list_addons(
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
    search: Optional[str] = Query(None),
    vendor_id: Optional[int] = Query(None),
    stock_status: Optional[str] = Query(None),
) -> List[AddonPublic]:
    q = db.query(AddonProduct).filter(AddonProduct.is_active.is_(True))
    if vendor_id:
        q = q.filter(AddonProduct.vendor_id == vendor_id)
    if search:
        s = f"%{search.lower()}%"
        q = q.filter(or_(
            func.lower(AddonProduct.our_product_id).like(s),
            func.lower(AddonProduct.name).like(s),
            func.lower(AddonProduct.vendor_product_id).like(s),
        ))
    rows = q.order_by(AddonProduct.id.desc()).all()
    if stock_status:
        rows = [r for r in rows if _stock_status(r) == stock_status]
    return [_to_public(r, db, auth=auth) for r in rows]


@router.get("/{addon_id}", response_model=AddonDetail, dependencies=[Depends(require_permission("addons.read"))])
def get_addon(addon_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(get_auth_context)) -> AddonDetail:
    row = db.get(AddonProduct, addon_id)
    if not row:
        raise HTTPException(404, "addon not found")
    pub = _to_public(row, db, auth=auth)
    ph = [{"buying_price": hide_cost(format(p.buying_price, "f"), auth), "recorded_at": p.recorded_at.isoformat()} for p in list_price_history(db, "addon_product", addon_id)]
    eh = [
        {
            "change_summary": hide_cost_in_diff_summary(h.change_summary, auth),
            "valid_from": h.valid_from.isoformat(),
            "snapshot_json": hide_cost_in_snapshot_json(h.snapshot_json, auth),
        }
        for h in list_entity_history(db, "addon_product", addon_id)
    ]
    moves = (
        db.query(AddonStockLedger)
        .filter(AddonStockLedger.addon_product_id == addon_id)
        .order_by(AddonStockLedger.id.desc())
        .limit(100)
        .all()
    )
    sm = [
        {
            "entry_type": m.entry_type,
            "quantity_delta": m.quantity_delta,
            "balance_after": m.balance_after,
            "notes": m.notes,
            "party": m.party,
            "created_by_name": m.created_by_name,
            "created_at": m.created_at.isoformat(),
        }
        for m in moves
    ]
    return AddonDetail(**pub.model_dump(), price_history=ph, change_history=eh, stock_movements=sm)


@router.post("", response_model=AddonPublic, status_code=201, dependencies=[Depends(require_permission("addons.write"))])
def create_addon(body: AddonCreate, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permission("addons.write"))) -> AddonPublic:
    if not db.get(Vendor, body.vendor_id):
        raise HTTPException(400, "vendor not found")
    clash = db.query(AddonProduct).filter(
        AddonProduct.our_product_id == body.our_product_id.strip(), AddonProduct.is_active.is_(True)
    ).first()
    if clash:
        raise HTTPException(409, "our_product_id already exists")
    row = AddonProduct(
        our_product_id=body.our_product_id.strip(),
        vendor_id=body.vendor_id,
        vendor_product_id=body.vendor_product_id.strip(),
        name=body.name,
        description=body.description,
        category=body.category,
        unit=body.unit.strip(),
        buying_price=body.buying_price.quantize(Decimal("0.01")),
        image_keys=body.image_keys or [],
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "duplicate our_product_id") from None
    db.refresh(row)
    record_price_change(db, "addon_product", row.id, row.buying_price)
    log_from_auth(db, auth, action="create", entity_type="addon", entity_id=row.id, entity_label=row.our_product_id)
    db.commit()
    return _to_public(row, db, auth=auth)


@router.patch("/{addon_id}", response_model=AddonPublic, dependencies=[Depends(require_permission("addons.write"))])
def update_addon(addon_id: int, body: AddonUpdate, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permission("addons.write"))) -> AddonPublic:
    row = db.get(AddonProduct, addon_id)
    if not row or not row.is_active:
        raise HTTPException(404, "addon not found")
    before = row_snapshot(row, TRACKED_FIELDS["addon_product"])
    data = body.model_dump(exclude_unset=True)
    price_changed = False
    if "buying_price" in data and data["buying_price"] is not None:
        row.buying_price = data["buying_price"].quantize(Decimal("0.01"))
        price_changed = True
        del data["buying_price"]
    for k, v in data.items():
        setattr(row, k, v)
    if price_changed:
        record_price_change(db, "addon_product", row.id, row.buying_price)
    after = row_snapshot(row, TRACKED_FIELDS["addon_product"])
    summary = diff_summary("addon_product", before, after)
    if summary != "updated":
        record_entity_history(db, "addon_product", row.id, before, summary)
    log_from_auth(
        db,
        auth,
        action="update",
        entity_type="addon",
        entity_id=row.id,
        entity_label=row.our_product_id,
        detail=summary if summary != "updated" else None,
    )
    db.commit()
    db.refresh(row)
    return _to_public(row, db, auth=auth)


@router.post("/{addon_id}/receive-stock", response_model=AddonPublic, dependencies=[Depends(require_permission("addons.write"))])
def receive_addon_stock(
    addon_id: int,
    body: AddonReceiveStockIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("addons.write")),
) -> AddonPublic:
    row = db.get(AddonProduct, addon_id)
    if not row or not row.is_active:
        raise HTTPException(404, "addon not found")
    vendor = db.get(Vendor, row.vendor_id)
    add_addon_stock(
        db,
        addon_product_id=addon_id,
        quantity=body.quantity,
        entry_type="received",
        reference_type="addon_receive",
        party=vendor.business_name if vendor else None,
        notes=body.note,
        created_by_name=auth.actor_name,
    )
    if body.total_cost is not None and body.total_cost > 0:
        try:
            exp_date = date.fromisoformat(body.expense_date) if body.expense_date else date.today()
        except ValueError:
            exp_date = date.today()
        db.add(Expense(
            expense_date=exp_date,
            category="addon stock",
            description=f"{row.name or row.our_product_id} x{body.quantity} from {vendor.business_name if vendor else 'vendor'}"
            + (f" — {body.note}" if body.note else ""),
            amount=body.total_cost,
            reference=row.our_product_id,
            created_by_name=auth.actor_name,
        ))
    log_from_auth(
        db, auth, action="update", entity_type="addon", entity_id=row.id, entity_label=row.our_product_id,
        detail=f"received stock +{body.quantity}",
    )
    db.commit()
    db.refresh(row)
    return _to_public(row, db, auth=auth)


@router.post("/{addon_id}/adjust-stock", response_model=AddonPublic, dependencies=[Depends(require_permission("addons.write"))])
def adjust_addon_stock(
    addon_id: int,
    body: AddonAdjustStockIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("addons.write")),
) -> AddonPublic:
    row = db.get(AddonProduct, addon_id)
    if not row or not row.is_active:
        raise HTTPException(404, "addon not found")
    add_addon_stock(
        db,
        addon_product_id=addon_id,
        quantity=body.delta,
        entry_type="adjustment",
        reference_type="addon_adjust",
        notes=body.reason,
        created_by_name=auth.actor_name,
    )
    log_from_auth(
        db, auth, action="update", entity_type="addon", entity_id=row.id, entity_label=row.our_product_id,
        detail=f"stock adjustment {body.delta:+d} ({body.reason})",
    )
    db.commit()
    db.refresh(row)
    return _to_public(row, db, auth=auth)


@router.delete("/{addon_id}", status_code=204, dependencies=[Depends(require_permission("addons.write"))])
def delete_addon(addon_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permission("addons.write"))) -> None:
    row = db.get(AddonProduct, addon_id)
    if not row or not row.is_active:
        raise HTTPException(404, "addon not found")
    row.is_active = False
    row.deleted_at = datetime.now(timezone.utc)
    log_from_auth(db, auth, action="delete", entity_type="addon", entity_id=row.id, entity_label=row.our_product_id)
    db.commit()
