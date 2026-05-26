"""Resolve repo ``Dashboard/db.py`` on ``sys.path`` (local / Railway)."""
from __future__ import annotations

import sys
from pathlib import Path


def _find_repo_with_dashboard(start: Path) -> Path:
    here = start.resolve()
    for p in [here, *here.parents]:
        dash = p / "Dashboard" / "db.py"
        if dash.is_file():
            return p
    raise RuntimeError(
        "Dashboard/db.py not found: run API from repo root or set PYTHONPATH to repo root."
    )


def load_dashboard_db():
    """Import ``db`` from ``<repo>/Dashboard/db.py``."""
    here = Path(__file__).resolve()
    repo_root = _find_repo_with_dashboard(here.parent)
    dash = repo_root / "Dashboard"
    dash_str = str(dash)
    repo_str = str(repo_root)
    if repo_str not in sys.path:
        sys.path.insert(0, repo_str)
    if dash_str not in sys.path:
        sys.path.insert(0, dash_str)
    import db as dashboard_db  # noqa: PLC0415

    return dashboard_db
