"""Multi-token search helpers — each token must match any of the given columns."""
from __future__ import annotations

from typing import Any, Iterable, Optional, Sequence

from sqlalchemy import ColumnElement, and_, func, or_


def search_tokens(q: str | None) -> list[str]:
    if not q:
        return []
    return [t for t in str(q).strip().lower().split() if t]


def token_match(q: str | None, columns: Iterable) -> ColumnElement | None:
    """AND of tokens; each token ORs across columns (lowercased LIKE %token%)."""
    tokens = search_tokens(q)
    if not tokens:
        return None
    cols = list(columns)
    if not cols:
        return None
    parts = []
    for tok in tokens:
        pat = f"%{tok}%"
        parts.append(or_(*[func.lower(c).like(pat) for c in cols]))
    return and_(*parts) if len(parts) > 1 else parts[0]


def party_search_rank(
    *,
    business_name: Optional[str] = None,
    city_name: Optional[str] = None,
    person_name: Optional[str] = None,
    alias: Optional[str] = None,
    phone: Optional[str] = None,
    tokens: Sequence[str],
) -> tuple:
    """Sort key: business matches first, then city, then person/alias, then other.

    Lower tuple sorts first.
    """
    biz = (business_name or "").lower()
    city = (city_name or "").lower()
    person = f"{person_name or ''} {alias or ''}".lower().strip()
    if not tokens:
        return (0, 0, 0, biz)

    biz_hits = sum(1 for t in tokens if t in biz)
    city_hits = sum(1 for t in tokens if t in city)
    person_hits = sum(1 for t in tokens if t in person)

    if biz_hits:
        tier, hits = 0, biz_hits
    elif city_hits:
        tier, hits = 1, city_hits
    elif person_hits:
        tier, hits = 2, person_hits
    else:
        tier, hits = 3, 0

    starts = 1 if tokens and biz.startswith(tokens[0]) else 0
    return (tier, -hits, -starts, biz)


def sort_parties_by_search(
    rows: list[Any],
    q: str | None,
    *,
    business_attr: str = "business_name",
    city_attr: str = "city_name",
    person_attr: str = "person_name",
    alias_attr: str = "alias",
    phone_attr: str = "phone",
    city_lookup: dict[int, str] | None = None,
    city_id_attr: str = "city_id",
) -> list[Any]:
    """Stable rank sort for customer/vendor-like rows when searching."""
    tokens = search_tokens(q)
    if not tokens:
        return rows

    def city_of(row: Any) -> str:
        direct = getattr(row, city_attr, None)
        if direct:
            return str(direct)
        if isinstance(row, dict) and row.get(city_attr):
            return str(row[city_attr])
        if city_lookup is not None:
            cid = getattr(row, city_id_attr, None)
            if cid is None and isinstance(row, dict):
                cid = row.get(city_id_attr)
            if cid is not None:
                return city_lookup.get(int(cid), "") or ""
        return ""

    def field(row: Any, attr: str) -> str:
        if isinstance(row, dict):
            return str(row.get(attr) or "")
        return str(getattr(row, attr, None) or "")

    return sorted(
        rows,
        key=lambda r: party_search_rank(
            business_name=field(r, business_attr),
            city_name=city_of(r),
            person_name=field(r, person_attr),
            alias=field(r, alias_attr),
            phone=field(r, phone_attr),
            tokens=tokens,
        ),
    )
