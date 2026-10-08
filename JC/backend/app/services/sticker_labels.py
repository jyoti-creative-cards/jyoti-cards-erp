"""Read and store the Hindi sticker line for one customer."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.sticker_label import StickerLabel
from app.services.sticker_hindi import hindi_city, hindi_name


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
