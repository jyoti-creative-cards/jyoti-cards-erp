"""Implementation lives in app.services.customer_selling."""
from app.services.customer_selling.buckets import get_open_customer_order, get_or_create_customer_order, _get_or_create_open_line, add_to_customer_open
from app.services.customer_selling.stock import reserve_stock, restore_stock
from app.services.customer_selling.lines import edit_customer_open_qty, edit_customer_placement_line_qty, replace_received_placement
from app.services.customer_selling.cancel import cancel_customer_placement
from app.services.customer_selling.confirm import confirm_received_order, promote_placement_to_confirmed, close_received_order_if_fully_billed, get_open_unbilled_placement
from app.services.customer_selling.place import append_or_create_portal_placement, create_portal_placement, create_received_placement

__all__ = [
    "_get_or_create_open_line",
    "add_to_customer_open",
    "append_or_create_portal_placement",
    "cancel_customer_placement",
    "close_received_order_if_fully_billed",
    "confirm_received_order",
    "create_portal_placement",
    "create_received_placement",
    "edit_customer_open_qty",
    "edit_customer_placement_line_qty",
    "get_open_customer_order",
    "get_open_unbilled_placement",
    "get_or_create_customer_order",
    "promote_placement_to_confirmed",
    "replace_received_placement",
    "reserve_stock",
    "restore_stock",
]
