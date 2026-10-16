"""Item-number search that returns a photo and the stock on hand."""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import AuthContext, get_auth_context
from app.models.catalog_product import CatalogProduct
from app.models.stock import StockBalance
from app.services.storage import presigned_urls

router = APIRouter(prefix="/items", tags=["items"])


def _matches(our_id: str, raw: str) -> bool:
    our = (our_id or "").strip()
    query = raw.strip()
    if not our or not query:
        return False
    if query.isdigit():
        head = re.match(r"0*(\d+)", our)
        if not head or head.group(1) != str(int(query)):
            return False
        rest = our[head.end():]
        return rest == "" or not rest[0].isdigit()
    folded = our.upper()
    wanted = query.upper()
    return folded == wanted or folded.startswith(wanted + " ")


@router.get("/lookup")
def lookup_item(
    q: str = Query(..., min_length=1, max_length=80),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
) -> dict:
    if not auth.is_admin and not auth.has("items.lookup") and not auth.has("catalog.read") and not auth.has("stock.read"):
        raise HTTPException(403, "permission denied")
    # Other staff still pass has() for every permission. The lookup account
    # only passes items.lookup, so the check above is what fences them in.
    needle = q.strip()
    rows = (
        db.query(CatalogProduct)
        .filter(
            CatalogProduct.is_active.is_(True),
            CatalogProduct.deleted_at.is_(None),
            CatalogProduct.our_product_id.ilike(f"{needle}%"),
        )
        .order_by(CatalogProduct.our_product_id.asc(), CatalogProduct.id.asc())
        .limit(40)
        .all()
    )
    matched = [row for row in rows if _matches(row.our_product_id, needle)][:12]
    balances = {}
    if matched:
        ids = [row.id for row in matched]
        for balance in db.query(StockBalance).filter(StockBalance.catalog_product_id.in_(ids)).all():
            balances[balance.catalog_product_id] = int(balance.quantity_on_hand or 0)
    items = []
    for row in matched:
        urls = presigned_urls((row.image_keys or [])[:1])
        items.append({
            "our_product_id": row.our_product_id,
            "year_group": row.year_group,
            "quantity_on_hand": balances.get(row.id, 0),
            "image_url": urls[0] if urls else None,
        })
    return {"items": items}
