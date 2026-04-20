import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base

# DB_PATH resolved from env (set by render.yaml to /data/ops.db)
DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(os.path.dirname(__file__)), "ops.db"))

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
