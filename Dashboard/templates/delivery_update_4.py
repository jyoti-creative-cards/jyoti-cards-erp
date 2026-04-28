"""
`delivery_update_4` · Hindi (Utility) — name + receipt + contact + notes.
In Meta, body variables are **Text** (named) — set variable names to match `body_keys`.
Optional **Image** header in Manager: if we send a receipt image, first component is `header` image.
"""
from __future__ import annotations

TEMPLATE_KEY = "delivery_update"

SPEC: dict = {
    "name": "delivery_update_4",
    "language": "hi",
    "param_style": "named",
    "body_keys": (
        "name",
        "receipt",
        "contact",
        "notes",
    ),
    # If Manager has an image header, we attach via Cloud API `header` + media id
    "header": "image",
    "header_optional": True,
}
