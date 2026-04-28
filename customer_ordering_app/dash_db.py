"""Load Dashboard/db.py by file path; refresh when file changes (Streamlit reruns)."""
from __future__ import annotations

import importlib.util
import os
import sys

_DASHBOARD_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "Dashboard")
)
_DASH_DB_PATH = os.path.join(_DASHBOARD_DIR, "db.py")
_MODELS_PATH = os.path.join(_DASHBOARD_DIR, "models.py")
_MOD = None
_MTIME_DB: float | None = None
_MTIME_MODELS: float | None = None
_MODULE_NAME = "dashboard_business_db"


def get_dashboard_db():
    global _MOD, _MTIME_DB, _MTIME_MODELS
    m_db = os.path.getmtime(_DASH_DB_PATH)
    m_models = os.path.getmtime(_MODELS_PATH)
    if (
        _MOD is None
        or m_db != _MTIME_DB
        or m_models != _MTIME_MODELS
    ):
        # Force db.py to re-bind schema DDL from models.py (e.g. new AR/AP tables).
        sys.modules.pop("dashboard_business_db", None)
        sys.modules.pop("_dashboard_schema_models", None)
        spec = importlib.util.spec_from_file_location(_MODULE_NAME, _DASH_DB_PATH)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load {_DASH_DB_PATH}")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[_MODULE_NAME] = mod
        spec.loader.exec_module(mod)
        _MOD = mod
        _MTIME_DB = m_db
        _MTIME_MODELS = m_models
    return _MOD
