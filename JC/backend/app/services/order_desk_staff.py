"""Two booking clerks: jeevan and sudhir. Login is the name, not a phone."""

from __future__ import annotations

import logging

from app.db.session import SessionLocal
from app.models.staff import Staff
from app.services.passwords import hash_password
from app.services.permissions import dump_permissions

logger = logging.getLogger("jc.order_desk")

DESK_PERMISSIONS = [
    "customers.read",
    "customer_orders.read",
    "customer_orders.write",
    "desk.book",
]

DESK_ACCOUNTS = (
    {"name": "jeevan", "password": "jeevanbhai@JCC", "phone": "6191000001"},
    {"name": "sudhir", "password": "sud_jcc", "phone": "6191000002"},
)


def ensure_order_desk_staff() -> None:
    db = SessionLocal()
    try:
        perms = dump_permissions(DESK_PERMISSIONS)
        for spec in DESK_ACCOUNTS:
            row = (
                db.query(Staff)
                .filter(Staff.deleted_at.is_(None), Staff.name.ilike(spec["name"]))
                .order_by(Staff.id.asc())
                .first()
            )
            if row is None:
                taken = db.query(Staff).filter(Staff.phone == spec["phone"]).one_or_none()
                if taken is not None:
                    logger.warning("order desk phone %s already used", spec["phone"])
                    continue
                row = Staff(
                    name=spec["name"],
                    phone=spec["phone"],
                    password_hash=hash_password(spec["password"]),
                    permissions_json=perms,
                    is_active=True,
                )
                db.add(row)
                continue
            row.name = spec["name"]
            row.password_hash = hash_password(spec["password"])
            row.permissions_json = perms
            row.is_active = True
            row.deleted_at = None
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
