"""Portal link is written into the Hindi WhatsApp bodies."""
from app.services.whatsapp_notify import (
    BILL_CANCEL_TEMPLATE,
    BILL_TEMPLATE,
    DISPATCH_TEMPLATE,
    ORDER_CANCEL_TEMPLATE,
    ORDER_TEMPLATE,
    PORTAL_URL,
    bill_cancelled_params,
    bill_ready_params,
    dispatch_ready_params,
    order_cancelled_params,
    order_confirmation_params,
)


def test_order_confirmation_writes_the_portal_link():
    params = order_confirmation_params("Sharma", "88", "1044 (+1)", 6, "12.00")
    assert ORDER_TEMPLATE == "order_confirmation"
    assert params[0] == "Sharma"
    assert params[1] == "88"
    assert params[2] == "1044 (+1)"
    assert params[3] == "6"
    assert params[4] == "12.00"
    assert params[5] == PORTAL_URL
    assert PORTAL_URL == "https://jyoticards.vercel.app"


def test_bill_and_dispatch_name_the_hindi_templates():
    assert bill_ready_params("Sharma", "A649", "1250.00") == ["Sharma", "A649", "1250.00"]
    assert dispatch_ready_params("Sharma", "A649") == ["Sharma", "A649"]
    assert BILL_TEMPLATE == "bill_ready_hindi"
    assert DISPATCH_TEMPLATE == "dispatch_ready_hindi"
    assert order_cancelled_params("Sharma", "88") == ["Sharma", "88"]
    assert bill_cancelled_params("Sharma", "A649") == ["Sharma", "A649"]
    assert ORDER_CANCEL_TEMPLATE == "order_cancelled_hindi"
    assert BILL_CANCEL_TEMPLATE == "bill_cancelled_hindi"
