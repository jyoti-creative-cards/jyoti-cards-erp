from app.routers.customers.support import friendly_whatsapp_error


def test_unregistered_whatsapp_account_is_a_short_sentence():
    raw = '{"error":{"message":"This account is not registered","code":133010}}'
    text = friendly_whatsapp_error(raw)
    assert "133010" in text
    assert "Party saved" in text
    assert "error" not in text.lower() or "not registered" in text.lower()
    assert "{" not in text
