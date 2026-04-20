import os
import sqlite3
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base

def _resolve_db_path() -> str:
    project_default = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ops.db")
    requested = (os.getenv("DB_PATH", "") or "").strip()
    candidates = [requested, project_default, "/tmp/ops.db"]
    seen = set()
    for path in candidates:
        if not path or path in seen:
            continue
        seen.add(path)
        try:
            parent = os.path.dirname(path) or "."
            os.makedirs(parent, exist_ok=True)
            conn = sqlite3.connect(path)
            conn.close()
            return path
        except Exception:
            continue
    return project_default


DB_PATH = _resolve_db_path()

# WAL mode for concurrent reads from multiple services
engine = create_engine(
    f"sqlite:///{DB_PATH}",
    echo=False,
    connect_args={"check_same_thread": False, "timeout": 30},
)

@event.listens_for(engine, "connect")
def _set_wal(dbapi_conn, connection_record):
    dbapi_conn.execute("PRAGMA journal_mode=WAL")
    dbapi_conn.execute("PRAGMA synchronous=NORMAL")
    dbapi_conn.execute("PRAGMA foreign_keys=ON")

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from db import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    _run_sqlite_migrations()


def _run_sqlite_migrations():
    """Add any missing columns added after initial schema creation."""
    with engine.connect() as conn:
        existing = {row[1] for row in conn.execute(
            __import__("sqlalchemy").text("PRAGMA table_info(products)")
        )}
        migrations = [
            ("products", "website_visible", "ALTER TABLE products ADD COLUMN website_visible INTEGER DEFAULT 1"),
            ("products", "website_description", "ALTER TABLE products ADD COLUMN website_description TEXT"),
            ("vendors",  "owner_name",  "ALTER TABLE vendors ADD COLUMN owner_name VARCHAR(200)"),
            ("vendors",  "firm_name",   "ALTER TABLE vendors ADD COLUMN firm_name VARCHAR(200)"),
            ("vendors",  "billing_condition", "ALTER TABLE vendors ADD COLUMN billing_condition VARCHAR(50) DEFAULT '100%'"),
        ]
        for table, col, sql in migrations:
            cols = {row[1] for row in conn.execute(
                __import__("sqlalchemy").text(f"PRAGMA table_info({table})")
            )}
            if col not in cols:
                try:
                    conn.execute(__import__("sqlalchemy").text(sql))
                    conn.commit()
                except Exception:
                    pass
