"""One free-text marking on an order, plus the customer's own words."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.customer_order import CustomerOrder

PORTAL_SOURCES = {"app", "portal", "shop"}
MARK_MAX = 400
_SKIP = {"order placed by admin (phone)", "offline order", "order placed by admin"}


def clean_mark(value: str | None) -> str | None:
    text = " ".join((value or "").split())
    if not text or text.lower() in _SKIP:
        return None
    return text[:MARK_MAX]


def _merge(current: str | None, extra: str | None) -> str | None:
    left = clean_mark(current)
    right = clean_mark(extra)
    if not right:
        return left
    if not left:
        return right
    parts = {part.strip().casefold() for part in left.split("·")}
    if right.casefold() in parts:
        return left
    return f"{left} · {right}"


def note_onto_order(order: CustomerOrder | None, *, source: str | None, notes: str | None) -> None:
    """Portal words stay the customer marking. Any other note fills an empty order marking."""
    text = clean_mark(notes)
    if order is None or not text:
        return
    if (source or "").strip().lower() in PORTAL_SOURCES:
        order.customer_marking = text
        return
    if not clean_mark(order.marking):
        order.marking = text


def set_order_marking(order: CustomerOrder | None, text: str | None) -> None:
    if order is None:
        return
    order.marking = clean_mark(text)


def carry_marks(src: CustomerOrder | None, dest: CustomerOrder | None) -> None:
    """Keep the marking when a new order is folded into the open one."""
    if src is None or dest is None or src is dest:
        return
    staff = clean_mark(src.marking)
    if staff:
        dest.marking = staff
    cust = clean_mark(src.customer_marking)
    if cust:
        dest.customer_marking = cust


def resolve_pair(order: CustomerOrder | None, placement_rows: list[tuple[str | None, str | None]]) -> tuple[str | None, str | None]:
    """Staff marking, then customer marking. Old notes fill a column that is still empty."""
    staff = clean_mark(getattr(order, "marking", None))
    cust = clean_mark(getattr(order, "customer_marking", None))
    leg_staff: list[str] = []
    leg_cust: list[str] = []
    if staff is None or cust is None:
        for source, notes in placement_rows:
            text = clean_mark(notes)
            if not text:
                continue
            bucket = leg_cust if (source or "").strip().lower() in PORTAL_SOURCES else leg_staff
            if text not in bucket:
                bucket.append(text)
    if staff is None:
        staff = " · ".join(leg_staff) or None
    if cust is None:
        cust = " · ".join(leg_cust) or None
    if staff and cust and staff.casefold() == cust.casefold():
        cust = None
    return staff, cust


def one_mark(*values) -> str | None:
    """Every old line, joined into the single marking."""
    parts: list[str] = []
    seen: set[str] = set()
    for value in values:
        items = value if isinstance(value, (list, tuple)) else [value]
        for item in items:
            for piece in str(item or "").split("·"):
                text = clean_mark(piece)
                if not text:
                    continue
                key = text.casefold()
                if key in seen:
                    continue
                seen.add(key)
                parts.append(text)
    return " · ".join(parts) or None


def _last_piece(value: str | None) -> str | None:
    latest = None
    for piece in str(value or "").split("·"):
        text = clean_mark(piece)
        if text:
            latest = text
    return latest


def single_mark(staff: str | None, cust: str | None = None) -> str | None:
    """The latest marking only. A stored join keeps its last piece."""
    return _last_piece(staff) or _last_piece(cust)


def mark_list(staff: str | None, cust: str | None = None) -> list[str]:
    text = single_mark(staff, cust)
    return [text] if text else []


def set_live_marking(db: Session, customer_id: int, *, kind: str, text: str | None) -> None:
    """Write the sentence onto the customer's live order. Empty clears it."""
    value = clean_mark(text)
    orders = (
        db.query(CustomerOrder)
        .filter(
            CustomerOrder.customer_id == customer_id,
            CustomerOrder.is_open.is_(True),
            CustomerOrder.bucket.in_(["received", "open"]),
        )
        .all()
    )
    if not orders:
        latest = (
            db.query(CustomerOrder)
            .filter(CustomerOrder.customer_id == customer_id)
            .order_by(CustomerOrder.id.desc())
            .first()
        )
        orders = [latest] if latest is not None else []
    for order in orders:
        if kind == "customer":
            order.customer_marking = value
        else:
            order.marking = value
            order.customer_marking = None
