"""`account_creation_confirmation_3` · Hindi — new account credentials."""
from __future__ import annotations

# Logical key for `send_wa_template("account_creation", ...)`
TEMPLATE_KEY = "account_creation"

# "Text" / named variables in Manager → `param_style: "named"`, `parameter_name` in API.
# Portal: set the Visit URL in Meta to https://jyoti-cards.streamlit.app (static) — no API param needed.
# If Meta URL uses a dynamic suffix {{1}}, set env CUSTOMER_PORTAL_URL_BUTTON_SUFFIX (e.g. empty or path).
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
