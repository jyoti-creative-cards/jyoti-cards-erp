from pathlib import Path

import app.main  # noqa: F401

ALLOWED_LOOSE = ["ap_ledger.py"]


def test_loose_service_modules_are_packages():
    root = Path(__file__).resolve().parents[1] / "app" / "services"
    loose = [p.name for p in root.glob("*.py") if p.name != "__init__.py"]
    assert loose == ALLOWED_LOOSE


def test_service_facades_import():
    import importlib

    root = Path(__file__).resolve().parents[1] / "app" / "services"
    for folder in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("__")):
        importlib.import_module(f"app.services.{folder.name}")
    for module in ALLOWED_LOOSE:
        importlib.import_module(f"app.services.{module.removesuffix('.py')}")
