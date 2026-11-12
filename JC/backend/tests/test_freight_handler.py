from fastapi import HTTPException

from app.services.freight_handler import resolve_handler
from app.services.order_desk_staff import DESK_ACCOUNTS


def test_vishnu_requires_one_of_three_people():
    assert resolve_handler("Vishnu Parcel", "rahul") == "Rahul"
    assert resolve_handler("VISHNU", "Ganesh") == "Ganesh"
    assert resolve_handler("Other Bus", "Rahul") is None
    try:
        resolve_handler("Vishnu Parcel", "")
    except HTTPException as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("missing person should be rejected")


def test_order_desk_logins():
    by_name = {row["name"]: row["password"] for row in DESK_ACCOUNTS}
    assert by_name["anmol"] == "anmolbhai"
    assert by_name["sudhir"] == "sudhirbhai"
    assert by_name["lokesh"] == "lokeshbhai"
    assert by_name["anshulorder"] == "anshulagrawal"
    assert by_name["jeevan"] == "jeevanbhaiya"
