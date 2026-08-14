"""Mode of transport — bus / transport / self-pickup rules."""
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.services.transport_mode import normalize_transport
from app.services.customer_bill_math import assert_discount_xor


def test_bus_keeps_agent_and_charges():
    out = normalize_transport(
        transport_mode="bus",
        freight_agent_id=7,
        freight_charges="50",
        transport_receipt_number="ignore-me",
    )
    assert out["transport_mode"] == "bus"
    assert out["freight_agent_id"] == 7
    assert out["freight_charges"] == Decimal("50.00")
    assert out["transport_receipt_number"] is None


def test_bus_without_agent_rejected():
    with pytest.raises(HTTPException) as ei:
        normalize_transport(
            transport_mode="bus",
            freight_agent_id=None,
            freight_charges="50",
            transport_receipt_number=None,
        )
    assert ei.value.status_code == 400


def test_transport_charges_ok_empty_receipt():
    out = normalize_transport(
        transport_mode="transport",
        freight_agent_id=99,
        freight_charges="25.5",
        transport_receipt_number="  ",
    )
    assert out["transport_mode"] == "transport"
    assert out["freight_agent_id"] is None
    assert out["freight_charges"] == Decimal("25.50")
    assert out["transport_receipt_number"] is None


def test_transport_keeps_receipt_when_set():
    out = normalize_transport(
        transport_mode="transport",
        freight_agent_id=None,
        freight_charges="10",
        transport_receipt_number=" LR-44 ",
    )
    assert out["transport_receipt_number"] == "LR-44"


def test_transport_without_charges_rejected():
    with pytest.raises(HTTPException) as ei:
        normalize_transport(
            transport_mode="transport",
            freight_agent_id=None,
            freight_charges=None,
            transport_receipt_number="LR-1",
        )
    assert ei.value.status_code == 400


def test_self_pickup_clears_all():
    out = normalize_transport(
        transport_mode="self_pickup",
        freight_agent_id=3,
        freight_charges="40",
        transport_receipt_number="x",
    )
    assert out == {
        "transport_mode": "self_pickup",
        "freight_agent_id": None,
        "freight_charges": None,
        "transport_receipt_number": None,
    }


def test_missing_mode_rejected():
    with pytest.raises(HTTPException) as ei:
        normalize_transport(
            transport_mode=None,
            freight_agent_id=None,
            freight_charges=None,
            transport_receipt_number=None,
        )
    assert ei.value.status_code == 400


def test_overall_plus_line_discount_rejected():
    with pytest.raises(HTTPException) as ei:
        assert_discount_xor(
            overall_percent=10,
            lines=[{"discount_percent": 5, "catalog_product_id": 1}],
        )
    assert ei.value.status_code == 400


def test_overall_plus_line_net_rejected():
    with pytest.raises(HTTPException) as ei:
        assert_discount_xor(
            overall_percent=10,
            lines=[{"net_rate": 90, "catalog_product_id": 1}],
        )
    assert ei.value.status_code == 400


def test_overall_alone_ok():
    assert_discount_xor(overall_percent=10, lines=[{"catalog_product_id": 1}])


def test_line_disc_alone_ok():
    assert_discount_xor(
        overall_percent=None,
        lines=[{"discount_percent": 5, "catalog_product_id": 1}],
    )
