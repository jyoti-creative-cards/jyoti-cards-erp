"""`account_creation_confirmation_3` · Hindi — new account credentials."""
from __future__ import annotations

# Logical key for `send_wa_template("account_creation", ...)`
TEMPLATE_KEY = "account_creation"

# "Text" / named variables in Manager → `param_style: "named"`, `parameter_name` in API.
SPEC: dict = {
    "name": "account_creation_confirmation_3",
    "language": "hi",
    "param_style": "named",
    "body_keys": ("name", "phone", "password"),
}
