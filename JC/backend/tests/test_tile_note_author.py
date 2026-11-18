"""A saved note and a saved marking remember who wrote them."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.board import TextEvent, TileNote
from app.routers.board import tile_note_payload
from app.services.text_events import latest_map


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_note_names_the_last_writer_and_marking_names_the_last_writer():
    db = _db()
    db.add(TileNote(tile_key="co:open:2", body="call tomorrow", updated_by_name="Fiza"))
    db.add(TextEvent(kind="order", subject="2", body="Old", actor_name="Lokesh"))
    db.commit()
    db.add(TextEvent(kind="order", subject="2", body="Transport", actor_name="Nikhil"))
    db.commit()

    notes = tile_note_payload(db, ["co:open:2"], detail=True)
    assert notes["co:open:2"]["body"] == "call tomorrow"
    assert notes["co:open:2"]["by"] == "Fiza"
    assert latest_map(db, [("order", "2")])["order:2"]["actor_name"] == "Nikhil"
    db.close()


def test_old_note_uses_the_history_name():
    db = _db()
    db.add(TileNote(tile_key="co:open:9", body="pack separate", updated_by_name=""))
    db.add(TextEvent(kind="note", subject="co:open:9", body="pack separate", actor_name="Anshul"))
    db.commit()

    notes = tile_note_payload(db, ["co:open:9"], detail=True)
    assert notes["co:open:9"]["by"] == "Anshul"
    db.close()
