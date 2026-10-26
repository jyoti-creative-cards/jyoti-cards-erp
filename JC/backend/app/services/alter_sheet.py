"""Replace the alternative list for the products on the alter sheet.

The link table is jc_catalog_alternatives. Each direction is its own row.
If A lists B, B also lists A. Products that are not on the sheet keep their
other alternatives. A removed link is removed in both directions.
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy.orm import Session

from app.models.catalog_alternative import CatalogAlternative
from app.models.catalog_product import CatalogProduct

CURRENT_YEAR = "2026-27"
MAX_ALTERNATIVES = 12


def _lead(our_product_id: str) -> str:
    return (our_product_id or "").strip().split(" ")[0]


def resolve_code(products: list[CatalogProduct], code: str) -> CatalogProduct | None:
    """One live product for a sheet number. Current year, then the plain name."""
    text = str(code).strip()
    if not text:
        return None
    live = [p for p in products if p.is_active and not p.deleted_at]
    exact = [p for p in live if (p.our_product_id or "").strip() == text]
    if len(exact) == 1:
        return exact[0]
    lead = [p for p in live if _lead(p.our_product_id) == text]
    current = [p for p in lead if (p.year_group or "") == CURRENT_YEAR]
    pool = current or lead
    if not pool:
        return None
    pool.sort(key=lambda p: (len(p.our_product_id or ""), p.id))
    return pool[0]


def desired_links(rows: list[tuple[str, list[str]]], products: list[CatalogProduct]) -> tuple[dict[int, set[int]], list[str]]:
    """Sheet product id -> alternative ids, including the reverse of every sheet row."""
    by_code: dict[str, CatalogProduct] = {}
    problems: list[str] = []
    codes = {item for item, _alts in rows}
    for _item, alts in rows:
        codes.update(alts)
    for code in codes:
        found = resolve_code(products, code)
        if found is None:
            problems.append(f"{code} does not match a product")
        else:
            by_code[code] = found
    if problems:
        return {}, problems
    wanted: dict[int, set[int]] = {}
    for item, alts in rows:
        product = by_code[item]
        ids = set()
        for alt in alts:
            other = by_code[alt]
            if other.id != product.id:
                ids.add(other.id)
        wanted.setdefault(product.id, set()).update(ids)
    for product_id, alts in list(wanted.items()):
        for alt_id in alts:
            if alt_id in wanted:
                wanted[alt_id].add(product_id)
    too_many = [str(pid) for pid, alts in wanted.items() if len(alts) > MAX_ALTERNATIVES]
    if too_many:
        problems.append("more than 12 alternatives for " + ", ".join(too_many))
        return {}, problems
    return wanted, []


def apply_alter_rows(db: Session, rows: list[tuple[str, list[str]]]) -> dict:
    products = db.query(CatalogProduct).all()
    wanted, problems = desired_links(rows, products)
    if problems:
        raise ValueError("; ".join(problems))
    sheet_ids = set(wanted)
    existing = db.query(CatalogAlternative).all()
    outgoing: dict[int, set[int]] = defaultdict(set)
    for row in existing:
        outgoing[row.product_id].add(row.alternative_product_id)
    removed = 0
    added = 0
    for product_id, alts in wanted.items():
        for old in outgoing.get(product_id, set()) - alts:
            for owner, other in ((product_id, old), (old, product_id)):
                gone = (
                    db.query(CatalogAlternative)
                    .filter(
                        CatalogAlternative.product_id == owner,
                        CatalogAlternative.alternative_product_id == other,
                    )
                    .delete(synchronize_session=False)
                )
                removed += int(gone or 0)
                outgoing[owner].discard(other)
        for alt_id in alts:
            for owner, other in ((product_id, alt_id), (alt_id, product_id)):
                if other in outgoing.get(owner, set()):
                    continue
                if owner not in sheet_ids and len(outgoing.get(owner, set())) >= MAX_ALTERNATIVES:
                    raise ValueError(f"product {owner} already has {MAX_ALTERNATIVES} alternatives")
                db.add(CatalogAlternative(product_id=owner, alternative_product_id=other))
                outgoing.setdefault(owner, set()).add(other)
                added += 1
    db.flush()
    return {"products": len(wanted), "added": added, "removed": removed}
