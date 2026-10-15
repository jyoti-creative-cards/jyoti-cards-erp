"""Portal order list: confirmed, billed, and dispatched stay distinct."""
from app.routers.shop.list_order_history import portal_order_status


def test_new_order_is_not_confirmed():
    assert portal_order_status(
        bucket="received", placement_status="received", quantity=10, quantity_billed=0, dispatched=False
    ) == "new"


def test_confirmed_order_stays_visible():
    assert portal_order_status(
        bucket="open", placement_status="open", quantity=10, quantity_billed=0, dispatched=False
    ) == "confirmed"


def test_billed_then_dispatched():
    assert portal_order_status(
        bucket="open", placement_status="open", quantity=10, quantity_billed=10, dispatched=False
    ) == "billed"
    assert portal_order_status(
        bucket="open", placement_status="open", quantity=10, quantity_billed=10, dispatched=True
    ) == "dispatched"
