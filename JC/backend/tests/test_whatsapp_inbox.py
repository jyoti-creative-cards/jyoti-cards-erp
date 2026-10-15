"""Inbound WhatsApp webhook messages land in the inbox, once each."""
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.city import City  # noqa: F401 — customer foreign key
from app.models.customer import Customer
from app.models.route import Route  # noqa: F401
from app.models.whatsapp_message import WhatsAppMessage
from app.services.whatsapp_inbox import ingest_payload, message_text, phone_key


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _payload(wamid="wamid.1", phone="918952839355", body="Bill mil gaya", name="Patel"):
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "changes": [{
                "value": {
                    "contacts": [{"wa_id": phone, "profile": {"name": name}}],
                    "messages": [{
                        "from": phone,
                        "id": wamid,
                        "timestamp": "1760500000",
                        "type": "text",
                        "text": {"body": body},
                    }],
                },
                "field": "messages",
            }],
        }],
    }


def test_phone_key_keeps_last_ten():
    assert phone_key("+91 89528 39355") == "8952839355"
    assert message_text({"type": "image", "image": {"caption": "photo"}}) == ("image", "[Photo] photo")


def test_inbound_text_links_the_customer_and_ignores_duplicates():
    db = _db()
    db.add(Customer(business_name="Patel Graphics", phone="8952839355", password_hash="x"))
    db.commit()
    assert ingest_payload(db, _payload()) == 1
    assert ingest_payload(db, _payload()) == 0
    row = db.query(WhatsAppMessage).one()
    assert row.direction == "in"
    assert row.phone == "8952839355"
    assert row.body == "Bill mil gaya"
    assert row.contact_name == "Patel"
    assert row.customer_id == 1
    got = row.wa_timestamp
    if got.tzinfo is None:
        got = got.replace(tzinfo=timezone.utc)
    assert got == datetime.fromtimestamp(1760500000, tz=timezone.utc)
