import re


def parse_customer_message(message: str):
    text = (message or "").strip()
    lowered = text.lower()

    if any(word in lowered for word in ["available", "stock", "price", "rate"]):
        return {"intent": "catalog_query", "text": text}

    pairs = re.findall(r"(\d+)\s*(?:pcs|pc|x)?\s*([A-Za-z0-9\- ]+)", text)
    if pairs:
        items = []
        for qty, name in pairs:
            items.append({"quantity": float(qty), "name": name.strip()})
        return {"intent": "place_order", "items": items, "text": text}

    if "status" in lowered or "order" in lowered:
        return {"intent": "order_status", "text": text}

    return {"intent": "unknown", "text": text}
