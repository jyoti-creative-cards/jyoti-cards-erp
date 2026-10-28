"""addon_stock package. Import from app.services.addon_stock."""

from app.services.addon_stock import core as _core

for _name, _value in vars(_core).items():
    if _name.startswith("__") and _name.endswith("__"):
        continue
    globals()[_name] = _value

__all__ = getattr(_core, "__all__", [name for name in vars(_core) if not name.startswith("_")])
