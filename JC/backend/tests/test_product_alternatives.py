"""The add-alternative call sends JSON. It must not be treated as a missing query field."""
from app.main import app
from app.schemas.catalog import AlternativeLinkIn


def test_alternative_link_reads_json_fields():
    body = AlternativeLinkIn.model_validate({
        "alternative_our_product_id": "1002 CARD",
        "alternative_product_id": 12,
    })
    assert body.alternative_our_product_id == "1002 CARD"
    assert body.alternative_product_id == 12


def test_add_alternative_route_expects_a_json_body():
    spec = app.openapi()
    post = spec["paths"]["/api/v1/catalog/products/{product_id}/alternatives"]["post"]
    schema = post["requestBody"]["content"]["application/json"]["schema"]
    assert schema["$ref"].endswith("/AlternativeLinkIn")
