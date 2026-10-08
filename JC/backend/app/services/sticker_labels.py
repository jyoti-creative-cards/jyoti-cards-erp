"""Hindi sticker lines, and a log of each A5 print."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import String, cast, or_
from sqlalchemy.orm import Session

from app.models.sticker_label import StickerLabel
from app.models.sticker_print import StickerPrint
from app.services.sticker_hindi import hindi_city, hindi_name

_IST = ZoneInfo("Asia/Kolkata")


def label_for_customer(db: Session, customer, city_name: str | None) -> StickerLabel:
    name = (customer.business_name or "").strip()
    city = (city_name or "").strip()
    row = db.get(StickerLabel, customer.id)
    if row is not None and row.source_name == name and row.source_city == city:
        return row
    name_hi = hindi_name(name)
    city_hi = hindi_city(city)
    if row is None:
        row = StickerLabel(
            customer_id=customer.id,
            name_hi=name_hi,
            city_hi=city_hi,
            source_name=name,
            source_city=city,
        )
        db.add(row)
    else:
        row.name_hi = name_hi
        row.city_hi = city_hi
        row.source_name = name
        row.source_city = city
    db.commit()
    db.refresh(row)
    return row


def english_print_stamp(dt: datetime) -> str:
    """Print time in English, India time. Digits and month names, same idea as the phone."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone(_IST)
    hour = local.hour % 12 or 12
    ampm = "am" if local.hour < 12 else "pm"
    return f"{local.day} {local.strftime('%b')} {local.year}, {hour}:{local.minute:02d} {ampm}"


def print_payload(row: StickerPrint) -> dict:
    return {
        "id": row.id,
        "customer_id": row.customer_id,
        "party_number": row.party_number,
        "business_name": row.business_name,
        "name_hi": row.name_hi,
        "city_name": row.city_name,
        "city_hi": row.city_hi,
        "phone": row.phone,
        "printed_by": row.printed_by,
        "printed_at": row.printed_at.isoformat() if row.printed_at else None,
        "printed_label": english_print_stamp(row.printed_at) if row.printed_at else "",
    }


def record_sticker_print(db: Session, customer, city_name: str | None, printed_by: str) -> StickerPrint:
    label = label_for_customer(db, customer, city_name)
    row = StickerPrint(
        customer_id=customer.id,
        party_number=customer.party_number,
        business_name=(customer.business_name or "").strip(),
        name_hi=label.name_hi,
        city_name=(city_name or "").strip(),
        city_hi=label.city_hi,
        phone=customer.phone or "",
        printed_by=(printed_by or "").strip(),
        printed_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_sticker_prints(db: Session, q: str | None, limit: int = 40) -> list[StickerPrint]:
    query = db.query(StickerPrint).order_by(StickerPrint.printed_at.desc(), StickerPrint.id.desc())
    text = (q or "").strip()
    if text:
        like = f"%{text}%"
        query = query.filter(or_(
            StickerPrint.business_name.ilike(like),
            StickerPrint.city_name.ilike(like),
            StickerPrint.phone.ilike(like),
            StickerPrint.name_hi.ilike(like),
            cast(StickerPrint.party_number, String).ilike(like),
        ))
    return query.limit(max(1, min(limit, 100))).all()
