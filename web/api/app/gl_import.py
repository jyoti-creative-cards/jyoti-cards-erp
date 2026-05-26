"""Import ``Dashboard/gl.py`` after ``db`` is on the path."""
from __future__ import annotations


def load_gl():
    from app.db_import import load_dashboard_db

    load_dashboard_db()
    import gl as gl_mod  # noqa: PLC0415

    return gl_mod
