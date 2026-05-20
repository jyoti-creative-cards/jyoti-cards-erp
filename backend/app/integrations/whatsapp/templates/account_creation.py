"""`account_creation_confirmation_3` · Hindi — new account credentials."""
from __future__ import annotations

TEMPLATE_KEY = "account_creation"

SPEC: dict = {
    "name": "account_creation_confirmation_3",
    "language": "hi",
    "param_style": "named",
    "body_keys": ("name", "phone", "password"),
    "buttons": (
        {
            "sub_type": "url",
            "index": 0,
            "suffix_env": "CUSTOMER_PORTAL_URL_BUTTON_SUFFIX",
            "skip_if_empty": True,
        },
    ),
}
