"""Double-entry general ledger: chart of accounts, journal entries, trial balance, P&L."""
from __future__ import annotations

import sqlite3
from typing import Any, List, Optional, Sequence, Tuple

# Account codes (stable API)
AC_CASH = "1000"
AC_AR = "1100"
AC_INVENTORY = "1200"
AC_AP = "2000"
AC_EQUITY = "3000"
AC_SALES = "4000"
AC_COGS = "5000"

SCHEMA = """
CREATE TABLE IF NOT EXISTS gl_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    acc_type TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_gl_accounts_type ON gl_accounts (acc_type);

CREATE TABLE IF NOT EXISTS gl_journal_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_date TEXT NOT NULL,
    description TEXT,
    ref_type TEXT,
    ref_id INTEGER,
    reversal_of_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_gl_je_date ON gl_journal_entries (entry_date);
CREATE INDEX IF NOT EXISTS idx_gl_je_ref ON gl_journal_entries (ref_type, ref_id);

CREATE TABLE IF NOT EXISTS gl_journal_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    journal_id INTEGER NOT NULL,
    account_id INTEGER NOT NULL,
    debit REAL NOT NULL DEFAULT 0,
    credit REAL NOT NULL DEFAULT 0,
    FOREIGN KEY (journal_id) REFERENCES gl_journal_entries (id) ON DELETE CASCADE,
    FOREIGN KEY (account_id) REFERENCES gl_accounts (id),
    CHECK (debit >= 0 AND credit >= 0 AND (debit = 0 OR credit = 0))
);
CREATE INDEX IF NOT EXISTS idx_gl_lines_j ON gl_journal_lines (journal_id);
CREATE INDEX IF NOT EXISTS idx_gl_lines_a ON gl_journal_lines (account_id);
"""


def _connect() -> sqlite3.Connection:
    from db import DB_PATH

    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    return c


def init_gl_schema(conn: Optional[sqlite3.Connection] = None) -> None:
    own = conn is None
    if own:
        conn = _connect()
    try:
        conn.executescript(SCHEMA)
        _seed_accounts_if_empty(conn)
        conn.commit()
    finally:
        if own:
            conn.close()


def init_gl_full() -> None:
    """Create GL tables, seed default accounts. Safe to call on every app start."""
    with _connect() as c:
        c.executescript(SCHEMA)
        _seed_accounts_if_empty(c)
        c.commit()


def _seed_accounts_if_empty(conn) -> None:
    n = int(
        conn.execute("SELECT COUNT(*) AS c FROM gl_accounts").fetchone()["c"]
    )
    if n > 0:
        return
    rows = [
        (AC_CASH, "Cash and bank", "asset"),
        (AC_AR, "Accounts receivable", "asset"),
        (AC_INVENTORY, "Inventory", "asset"),
        (AC_AP, "Accounts payable", "liability"),
        (AC_EQUITY, "Equity", "equity"),
        (AC_SALES, "Sales revenue", "revenue"),
        (AC_COGS, "Cost of goods sold", "expense"),
    ]
    conn.executemany(
        "INSERT INTO gl_accounts (code, name, acc_type) VALUES (?, ?, ?)",
        rows,
    )
    conn.commit()


def get_account_id_by_code(conn, code: str) -> int:
    r = conn.execute(
        "SELECT id FROM gl_accounts WHERE code = ?", (code,)
    ).fetchone()
    if not r:
        raise ValueError(f"GL account {code} missing; run init")
    return int(r["id"])


def _validate_and_sum_lines(
    c: sqlite3.Connection, lines: Sequence[Tuple[str, float, float]]
) -> list[tuple[int, float, float]]:
    out: list[tuple[int, float, float]] = []
    t_debit = 0.0
    t_credit = 0.0
    for acode, d, cr in lines:
        di = float(d)
        ci = float(cr)
        if di < 0 or ci < 0 or (di > 0.0001 and ci > 0.0001):
            raise ValueError("Each line: debit or credit, not both")
        aid = get_account_id_by_code(c, acode)
        out.append((aid, di, ci))
        t_debit += di
        t_credit += ci
    if abs(t_debit - t_credit) > 0.005:
        raise ValueError(f"Journal not balanced: Dr {t_debit} Cr {t_credit}")
    return out


def post_journal(
    entry_date: str,
    description: str,
    ref_type: Optional[str],
    ref_id: Optional[int],
    lines: Sequence[Tuple[str, float, float]],
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    """
    lines: (account_code, debit, credit)  — each line has one side only.
    Returns new journal id.
    """
    own = conn is None
    if own:
        conn = _connect()
    try:
        validated = _validate_and_sum_lines(conn, lines)
        cur = conn.execute(
            """
            INSERT INTO gl_journal_entries (entry_date, description, ref_type, ref_id, reversal_of_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (entry_date[:10], description, ref_type, ref_id, None),
        )
        jid = int(cur.lastrowid)
        for aid, d, crd in validated:
            conn.execute(
                """
                INSERT INTO gl_journal_lines (journal_id, account_id, debit, credit)
                VALUES (?, ?, ?, ?)
                """,
                (jid, aid, d, crd),
            )
        if own:
            conn.commit()
        return jid
    finally:
        if own:
            conn.close()


def post_reversal(
    source_journal_id: int,
    entry_date: str,
    description: str,
    ref_type: Optional[str],
    ref_id: Optional[int],
) -> int:
    with _connect() as conn:
        lns = conn.execute(
            "SELECT account_id, debit, credit FROM gl_journal_lines WHERE journal_id = ?",
            (source_journal_id,),
        ).fetchall()
        if not lns:
            raise ValueError("Source journal not found or empty")
        rev: list[Tuple[str, float, float]] = []
        for r in lns:
            aid = int(r["account_id"])
            ac = conn.execute(
                "SELECT code FROM gl_accounts WHERE id = ?", (aid,)
            ).fetchone()
            if not ac:
                continue
            d, c = float(r["debit"]), float(r["credit"])
            if d > 0.0001:
                rev.append((ac["code"], 0.0, d))
            else:
                rev.append((ac["code"], c, 0.0))
    jid = post_journal(entry_date, description, ref_type, ref_id, rev, conn=None)
    with _connect() as c2:
        c2.execute(
            "UPDATE gl_journal_entries SET reversal_of_id = ? WHERE id = ?",
            (source_journal_id, jid),
        )
        c2.commit()
    return jid


def list_gl_accounts() -> list[dict[str, Any]]:
    with _connect() as c:
        r = c.execute(
            "SELECT id, code, name, acc_type, is_active FROM gl_accounts "
            "WHERE is_active = 1 ORDER BY code"
        ).fetchall()
    return [dict(x) for x in r]


def trial_balance(conn: Optional[sqlite3.Connection] = None) -> list[dict[str, Any]]:
    own = conn is None
    if own:
        conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT a.code, a.name, a.acc_type,
                COALESCE(SUM(l.debit - l.credit), 0) AS balance_debit
            FROM gl_accounts a
            LEFT JOIN gl_journal_lines l ON l.account_id = a.id
            WHERE a.is_active = 1
            GROUP BY a.id
            ORDER BY a.code
            """
        ).fetchall()
        return [dict(x) for x in rows]
    finally:
        if own:
            conn.close()


def journal_list(limit: int = 200) -> list[dict[str, Any]]:
    with _connect() as conn:
        r = conn.execute(
            f"""
            SELECT j.id, j.entry_date, j.description, j.ref_type, j.ref_id, j.reversal_of_id,
                (SELECT SUM(debit) FROM gl_journal_lines WHERE journal_id = j.id) AS total_dr
            FROM gl_journal_entries j
            ORDER BY j.id DESC
            LIMIT {int(limit)}
            """
        ).fetchall()
    return [dict(x) for x in r]


def journal_lines(journal_id: int) -> list[dict[str, Any]]:
    with _connect() as conn:
        r = conn.execute(
            """
            SELECT a.code, a.name, l.debit, l.credit
            FROM gl_journal_lines l
            JOIN gl_accounts a ON a.id = l.account_id
            WHERE l.journal_id = ?
            ORDER BY l.id
            """,
            (journal_id,),
        ).fetchall()
    return [dict(x) for x in r]


def pnl_to_date(through_yyyy_mm_dd: str) -> dict[str, float]:
    d = through_yyyy_mm_dd[:10]
    with _connect() as conn:
        rev = float(
            conn.execute(
                """
                SELECT COALESCE(SUM(l.credit - l.debit), 0) AS s
                FROM gl_journal_lines l
                JOIN gl_accounts a ON a.id = l.account_id AND a.acc_type = 'revenue'
                JOIN gl_journal_entries j ON j.id = l.journal_id
                WHERE j.entry_date <= ?
                """,
                (d,),
            ).fetchone()["s"]
        )
        exp = float(
            conn.execute(
                """
                SELECT COALESCE(SUM(l.debit - l.credit), 0) AS s
                FROM gl_journal_lines l
                JOIN gl_accounts a ON a.id = l.account_id AND a.acc_type = 'expense'
                JOIN gl_journal_entries j ON j.id = l.journal_id
                WHERE j.entry_date <= ?
                """,
                (d,),
            ).fetchone()["s"]
        )
    return {"revenue": rev, "expense": exp, "net_income": rev - exp}
