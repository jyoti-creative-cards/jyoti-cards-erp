from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session, object_session

from app.models.bill_series import BillSeries
from app.models.catalog_alternative import CatalogAlternative
from app.models.catalog_product import CatalogProduct
from app.models.city import City
from app.models.customer import Customer
from app.models.customer_bill import CustomerBill, CustomerBillLine
from app.models.customer_order import CustomerOrder, CustomerOrderLine, CustomerOrderPlacement
from app.models.freight_agent import FreightAgent
from app.models.route import Route
from app.models.vendor_order import VendorOrder
from app.services.catalog_addons import addon_snapshots_map


def is_locked(kind: str, row) -> bool:
    if kind == "customer_bill":
        return getattr(row, "id", None) is not None
    if kind == "vendor_bill":
        return getattr(row, "bill_status", None) == "billed"
    if kind == "customer_order":
        if getattr(row, "closed_at", None):
            return True
        if getattr(row, "status", None) == "closed":
            return True
        return _customer_order_bucket(row) == "closed"
    if kind == "vendor_order":
        if getattr(row, "status", None) == "closed":
            return True
        return _vendor_order_bucket(row) == "closed"
    if kind in {"customer_receipt", "debit_note", "expense", "payment", "freight", "customer_return"}:
        return False
    raise ValueError(f"unsupported present kind: {kind}")


def freeze_card(db: Session, kind: str, row) -> dict:
    if kind != "customer_bill":
        raise ValueError(f"freeze_card not implemented for kind: {kind}")
    if not isinstance(row, CustomerBill):
        raise TypeError("customer_bill freeze_card expects CustomerBill")

    customer = db.get(Customer, row.customer_id)
    card = {
        "kind": kind,
        "bill_number": row.bill_number,
        "party_name": customer.business_name if customer else f"Customer #{row.customer_id}",
        "party": _customer_party_card(db, customer),
        "bill_series_name": _bill_series_name(db, row.bill_series_id),
        "bill_series_prefix": _bill_series_prefix(db, row.bill_series_id),
        "freight_agent_name": _freight_agent_name(db, row.freight_agent_id),
        "created_by_name": row.created_by_name,
        "lines": _customer_bill_lines_card(db, row),
    }
    row.card_json = card
    return card


def present(db: Session, kind: str, row) -> dict:
    locked = is_locked(kind, row)

    if kind == "customer_bill":
        card = _stored_or_live_customer_bill_card(db, row)
        out = deepcopy(card)
        out["locked"] = locked
        out["display_date"] = row.bill_date
        out["status"] = _status(row)
        out["party_name"] = out.get("party_name") or f"Customer #{row.customer_id}"
        return out

    if kind == "customer_order":
        if locked and isinstance(getattr(row, "card_json", None), dict):
            card = deepcopy(row.card_json)
        else:
            card = _live_customer_order_card(db, row)
        card["locked"] = locked
        card["display_date"] = row.placed_at
        card["status"] = _status(row)
        card["party_name"] = card.get("party_name") or _customer_name(db, row)
        return card

    raise ValueError(f"present not implemented for kind: {kind}")


def _status(row) -> str:
    if getattr(row, "deleted_at", None):
        return "voided"
    if getattr(row, "cancelled_at", None):
        return "cancelled"
    if getattr(row, "closed_at", None):
        return "closed"
    return "open"


def _stored_or_live_customer_bill_card(db: Session, bill: CustomerBill) -> dict:
    if isinstance(bill.card_json, dict):
        return deepcopy(bill.card_json)
    return {
        "kind": "customer_bill",
        "bill_number": bill.bill_number,
        "party_name": _customer_name_for_bill(db, bill),
        "party": _customer_party_card(db, db.get(Customer, bill.customer_id)),
        "bill_series_name": _bill_series_name(db, bill.bill_series_id),
        "bill_series_prefix": _bill_series_prefix(db, bill.bill_series_id),
        "freight_agent_name": _freight_agent_name(db, bill.freight_agent_id),
        "created_by_name": bill.created_by_name,
        "lines": _customer_bill_lines_card(db, bill),
    }


def _live_customer_order_card(db: Session, placement: CustomerOrderPlacement) -> dict:
    customer = _customer_for_order(db, placement)
    lines = (
        db.query(CustomerOrderLine)
        .filter(CustomerOrderLine.placement_id == placement.id)
        .order_by(CustomerOrderLine.id.asc())
        .all()
    )
    return {
        "kind": "customer_order",
        "party_name": customer.business_name if customer else f"Customer #{placement.customer_order_id}",
        "party": _customer_party_card(db, customer),
        "lines": _line_cards_for_order(db, lines),
    }


def _customer_bill_lines_card(db: Session, bill: CustomerBill) -> list[dict]:
    lines = (
        db.query(CustomerBillLine)
        .filter(CustomerBillLine.bill_id == bill.id)
        .order_by(CustomerBillLine.id.asc())
        .all()
    )
    return _line_cards_for_bill(db, lines)


def _line_cards_for_bill(db: Session, lines: list[CustomerBillLine]) -> list[dict]:
    product_ids = [int(line.catalog_product_id) for line in lines]
    products = _products_by_id(db, product_ids)
    addon_map = addon_snapshots_map(db, product_ids, with_images=False) if product_ids else {}
    alt_map = _alternatives_map(db, product_ids)
    out: list[dict] = []
    for line in lines:
        prod = products.get(int(line.catalog_product_id))
        out.append(
            _product_line_card(
                prod,
                catalog_product_id=int(line.catalog_product_id),
                fallback_our_product_id=line.our_product_id,
                unit_price=line.unit_price,
                addons=addon_map.get(int(line.catalog_product_id)) or [],
                alternatives=alt_map.get(int(line.catalog_product_id)) or [],
            )
        )
    return out


def _line_cards_for_order(db: Session, lines: list[CustomerOrderLine]) -> list[dict]:
    product_ids = [int(line.catalog_product_id) for line in lines]
    products = _products_by_id(db, product_ids)
    addon_map = addon_snapshots_map(db, product_ids, with_images=False) if product_ids else {}
    alt_map = _alternatives_map(db, product_ids)
    out: list[dict] = []
    for line in lines:
        prod = products.get(int(line.catalog_product_id))
        addons = line.addons_json if line.addons_json is not None else addon_map.get(int(line.catalog_product_id)) or []
        out.append(
            _product_line_card(
                prod,
                catalog_product_id=int(line.catalog_product_id),
                fallback_our_product_id=line.our_product_id,
                unit_price=line.unit_price,
                addons=addons,
                alternatives=alt_map.get(int(line.catalog_product_id)) or [],
            )
        )
    return out


def _product_line_card(
    prod: CatalogProduct | None,
    *,
    catalog_product_id: int,
    fallback_our_product_id: str,
    unit_price: Decimal | None,
    addons: list[dict],
    alternatives: list[dict],
) -> dict:
    return {
        "catalog_product_id": catalog_product_id,
        "our_product_id": prod.our_product_id if prod else fallback_our_product_id,
        "vendor_product_id": prod.vendor_product_id if prod else None,
        "year_group": prod.year_group if prod else None,
        "category": prod.category if prod else None,
        "series": prod.series if prod else None,
        "unit": prod.unit if prod else None,
        "marking": prod.marking if prod else None,
        "buying_price": _money_str(prod.buying_price if prod else None),
        "selling_price": _money_str(prod.selling_price if prod else None),
        "unit_price": _money_str(unit_price),
        "image_keys": list(prod.image_keys or []) if prod else [],
        "addons": deepcopy(addons),
        "alternatives": deepcopy(alternatives),
    }


def _customer_party_card(db: Session, customer: Customer | None) -> dict | None:
    if not customer:
        return None
    city = db.get(City, customer.city_id) if customer.city_id else None
    route_id = customer.route_id or (city.route_id if city else None)
    route = db.get(Route, route_id) if route_id else None
    return {
        "business_name": customer.business_name,
        "person_name": customer.person_name,
        "phone": customer.phone,
        "address": customer.address,
        "city_name": city.name if city else None,
        "route_name": route.name if route else None,
        "gst_number": customer.gst_number,
        "party_number": customer.party_number,
        "marker_1": customer.marker_1,
        "marker_2": customer.marker_2,
        "payment_type": customer.payment_type,
    }


def _alternatives_map(db: Session, product_ids: list[int]) -> dict[int, list[dict]]:
    if not product_ids:
        return {}
    rows = (
        db.query(CatalogAlternative)
        .filter(CatalogAlternative.product_id.in_(product_ids))
        .order_by(CatalogAlternative.id.asc())
        .all()
    )
    alt_ids = [int(row.alternative_product_id) for row in rows]
    alt_products = _products_by_id(db, alt_ids)
    grouped: dict[int, list[dict]] = {pid: [] for pid in product_ids}
    for row in rows:
        alt = alt_products.get(int(row.alternative_product_id))
        if not alt:
            continue
        grouped.setdefault(int(row.product_id), []).append(
            {
                "catalog_product_id": int(alt.id),
                "our_product_id": alt.our_product_id,
                "vendor_product_id": alt.vendor_product_id,
                "year_group": alt.year_group,
                "category": alt.category,
                "series": alt.series,
                "unit": alt.unit,
                "marking": alt.marking,
                "buying_price": _money_str(alt.buying_price),
                "selling_price": _money_str(alt.selling_price),
                "image_keys": list(alt.image_keys or []),
            }
        )
    return grouped


def _products_by_id(db: Session, product_ids: list[int]) -> dict[int, CatalogProduct]:
    unique_ids = sorted({int(pid) for pid in product_ids if pid})
    if not unique_ids:
        return {}
    return {
        int(prod.id): prod
        for prod in db.query(CatalogProduct).filter(CatalogProduct.id.in_(unique_ids)).all()
    }


def _bill_series_name(db: Session, bill_series_id: int | None) -> str | None:
    series = db.get(BillSeries, bill_series_id) if bill_series_id else None
    return series.name if series else None


def _bill_series_prefix(db: Session, bill_series_id: int | None) -> str | None:
    series = db.get(BillSeries, bill_series_id) if bill_series_id else None
    return series.prefix if series else None


def _freight_agent_name(db: Session, freight_agent_id: int | None) -> str | None:
    agent = db.get(FreightAgent, freight_agent_id) if freight_agent_id else None
    return agent.name if agent else None


def _customer_for_order(db: Session, placement: CustomerOrderPlacement) -> Customer | None:
    order = db.get(CustomerOrder, placement.customer_order_id)
    if not order:
        return None
    return db.get(Customer, order.customer_id)


def _customer_name(db: Session, placement: CustomerOrderPlacement) -> str:
    customer = _customer_for_order(db, placement)
    if customer:
        return customer.business_name
    return f"Customer #{placement.customer_order_id}"


def _customer_name_for_bill(db: Session, bill: CustomerBill) -> str:
    customer = db.get(Customer, bill.customer_id)
    if customer:
        return customer.business_name
    return f"Customer #{bill.customer_id}"


def _customer_order_bucket(row) -> str | None:
    order = getattr(row, "order", None)
    if order is not None:
        return getattr(order, "bucket", None)
    customer_order_id = getattr(row, "customer_order_id", None)
    session = object_session(row)
    if session is not None and customer_order_id:
        order = session.get(CustomerOrder, customer_order_id)
        if order is not None:
            return order.bucket
    return getattr(row, "bucket", None)


def _vendor_order_bucket(row) -> str | None:
    order = getattr(row, "order", None)
    if order is not None:
        return getattr(order, "bucket", None)
    vendor_order_id = getattr(row, "vendor_order_id", None)
    session = object_session(row)
    if session is not None and vendor_order_id:
        order = session.get(VendorOrder, vendor_order_id)
        if order is not None:
            return order.bucket
    return getattr(row, "bucket", None)


def _money_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value, "f")
    return format(Decimal(str(value)), "f")
