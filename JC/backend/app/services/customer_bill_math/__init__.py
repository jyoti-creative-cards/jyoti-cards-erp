"""customer_bill_math package. Import from app.services.customer_bill_math."""

from app.services.customer_bill_math import core as _core

for _name, _value in vars(_core).items():
    if _name.startswith("__") and _name.endswith("__"):
        continue
    globals()[_name] = _value

__all__ = getattr(_core, "__all__", [name for name in vars(_core) if not name.startswith("_")])
