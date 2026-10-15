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


def test_order_and_dispatch_messages_do_not_build_a_pdf():
    import inspect

    from app.services import whatsapp_notify

    order_src = inspect.getsource(whatsapp_notify.notify_order_confirmed)
    dispatch_src = inspect.getsource(whatsapp_notify.notify_dispatched)
    assert "_order_pdf" not in order_src
    assert "upload_media" not in order_src
    assert "header_media_id" not in order_src
    assert "upload_media" not in dispatch_src
    assert "header_media_id" not in dispatch_src
    bill_src = inspect.getsource(whatsapp_notify.notify_bill_created)
    assert "upload_media" in bill_src


def test_order_confirmation_writes_the_portal_link():
    params = order_confirmation_params("Sharma", "88", "1044 (+1)", 6, "12.00")
    assert ORDER_TEMPLATE == "order_confirmed_hindi"
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
    assert DISPATCH_TEMPLATE == "dispatch_sent_hindi"
    assert order_cancelled_params("Sharma", "88") == ["Sharma", "88"]
    assert bill_cancelled_params("Sharma", "A649") == ["Sharma", "A649"]
    assert ORDER_CANCEL_TEMPLATE == "order_cancelled_hindi"
    assert BILL_CANCEL_TEMPLATE == "bill_cancelled_hindi"
