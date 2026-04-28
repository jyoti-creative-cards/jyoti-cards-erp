"""PostgreSQL driver shim + DDL init (Supabase). Used when DATABASE_URL is set."""
from __future__ import annotations

import os
import re
import socket
from typing import Any, Optional
from urllib.parse import urlparse

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None
    dict_row = None  # type: ignore


def use_postgres() -> bool:
    """True when ``DATABASE_URL`` is set. Call at runtime — Streamlit secrets load before first DB use."""
    return bool((os.environ.get("DATABASE_URL") or "").strip())


def database_url() -> str:
    """Supabase / Postgres URI from ``DATABASE_URL`` (Streamlit secrets or ``Dashboard/.env``)."""
    u = (os.environ.get("DATABASE_URL") or "").strip()
    if len(u) >= 2 and u[0] == u[-1] and u[0] in "\"'":
        u = u[1:-1].strip()
    if not u:
        raise RuntimeError("DATABASE_URL is not set")
    return u


def _remote_supabase_needs_ssl(uri: str) -> bool:
    """Streamlit Cloud → Supabase needs TLS; skip forcing sslmode when URI already sets it or host is local."""
    if "sslmode=" in uri.lower():
        return False
    try:
        host = (urlparse(uri).hostname or "").lower()
    except Exception:
        return True
    return host not in ("localhost", "127.0.0.1", "::1")


def _ipv4_hostaddr(hostname: Optional[str], port: int) -> Optional[str]:
    """Prefer IPv4 so Streamlit Cloud avoids broken IPv6 routes to Supabase."""
    if not hostname or hostname.lower() in ("localhost", "127.0.0.1", "::1"):
        return None
    try:
        return socket.gethostbyname(hostname)
    except OSError:
        pass
    try:
        infos = socket.getaddrinfo(hostname, port, socket.AF_INET, socket.SOCK_STREAM)
        if infos:
            return str(infos[0][4][0])
    except OSError:
        pass
    return None


def pg_connect():
    """Raw ``psycopg`` connection — same URL + TLS + IPv4 ``hostaddr`` for hosted DB."""
    if psycopg is None:
        raise RuntimeError("Install psycopg: pip install 'psycopg[binary]'")
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    uri = database_url()
    try:
        params = conninfo_to_dict(uri)
    except Exception as e:
        raise RuntimeError("DATABASE_URL could not be parsed") from e
    host = params.get("host")
    port = int(params.get("port") or 5432)
    if _remote_supabase_needs_ssl(uri):
        params.setdefault("sslmode", "require")
    ha = _ipv4_hostaddr(host, port)
    if ha:
        params["hostaddr"] = ha
    conninfo = make_conninfo(**params)
    return psycopg.connect(conninfo, autocommit=False)


def adapt_sql(sql: str) -> str:
    """Minimal SQLite → Postgres query tweaks (placeholders + date helpers)."""
    s = sql
    s = s.replace("datetime('now')", "CURRENT_TIMESTAMP")
    s = s.replace("date('now', '-30 days')", "(CURRENT_DATE - INTERVAL '30 days')")
    s = s.replace("date('now', '-30 days')", "(CURRENT_DATE - INTERVAL '30 days')")
    if "date(co.created_at) >= date('now', '-30 days')" in s:
        s = s.replace(
            "date(co.created_at) >= date('now', '-30 days')",
            "co.created_at::date >= (CURRENT_DATE - INTERVAL '30 days')",
        )
    if "?" in s:
        s = s.replace("?", "%s")
    return s


class _ShimCursor:
    __slots__ = ("_cur", "lastrowid", "_sql")

    def __init__(self, cur: Any, last_id: Optional[int], sql_hint: str):
        self._cur = cur
        self.lastrowid = last_id
        self._sql = sql_hint

    def fetchone(self) -> Any:
        return self._cur.fetchone()

    def fetchall(self) -> Any:
        return self._cur.fetchall()


class PgConnectionWrapper:
    """Mimics sqlite3.Connection patterns used in db.py (execute → cursor with lastrowid)."""

    def __init__(self, conn: Any):
        self._c = conn

    def execute(self, sql: str, params: Optional[tuple | list] = None):
        sql_a = adapt_sql(sql)
        params = tuple(params) if params is not None else ()
        cur = self._c.cursor(row_factory=dict_row)
        cur.execute(sql_a, params)
        last_id: Optional[int] = None
        st = sql_a.lstrip().upper()
        if st.startswith("INSERT"):
            cur2 = self._c.cursor()
            cur2.execute("SELECT LASTVAL()")
            lr = cur2.fetchone()
            cur2.close()
            if lr is not None:
                last_id = int(lr[0])
        return _ShimCursor(cur, last_id, sql_a)

    def executemany(self, sql: str, seq_of_params):
        sql_a = adapt_sql(sql)
        cur = self._c.cursor()
        cur.executemany(sql_a, seq_of_params)
        cur.close()

    def executescript(self, script: str) -> None:
        parts = [p.strip() for p in script.split(";") if p.strip()]
        for p in parts:
            sql_a = adapt_sql(p + ";")
            cur = self._c.cursor()
            cur.execute(sql_a)
            cur.close()

    def commit(self) -> None:
        self._c.commit()

    def rollback(self) -> None:
        self._c.rollback()

    def close(self) -> None:
        self._c.close()

    def __enter__(self) -> "PgConnectionWrapper":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type:
            self._c.rollback()
        else:
            self._c.commit()
        self._c.close()


def connect_postgres():
    return PgConnectionWrapper(pg_connect())


def table_columns_pg(conn: PgConnectionWrapper, table: str) -> set[str]:
    cur = conn._c.cursor()
    cur.execute(
        """
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        """,
        (table.lower(),),
    )
    rows = cur.fetchall()
    cur.close()
    out = set()
    for r in rows:
        if isinstance(r, dict):
            out.add(str(r["column_name"]))
        else:
            out.add(str(r[0]))
    return out


def table_exists_pg(conn: PgConnectionWrapper, table: str) -> bool:
    cur = conn._c.cursor()
    cur.execute(
        """
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = %s
        """,
        (table.lower(),),
    )
    ok = cur.fetchone() is not None
    cur.close()
    return ok


def list_tables_pg(conn: PgConnectionWrapper) -> list[str]:
    cur = conn._c.cursor()
    cur.execute(
        """
        SELECT tablename FROM pg_catalog.pg_tables
        WHERE schemaname = 'public' ORDER BY tablename
        """
    )
    rows = cur.fetchall()
    cur.close()
    return [str(r[0]) if not isinstance(r, dict) else str(r["tablename"]) for r in rows]
