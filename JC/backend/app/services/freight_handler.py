"""Vishnu Parcel is one agent with three people who can pick a parcel."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm.attributes import flag_modified

HANDLERS = ("Vishnu", "Rahul", "Ganesh")


def agent_needs_handler(agent_name: str | None) -> bool:
    return "vishnu" in (agent_name or "").casefold()


def resolve_handler(agent_name: str | None, raw: str | None) -> str | None:
    if not agent_needs_handler(agent_name):
        return None
    text = (raw or "").strip()
    for name in HANDLERS:
        if text.casefold() == name.casefold():
            return name
    raise HTTPException(400, "Select who picked it: Vishnu, Rahul, or Ganesh")


def stamp_handler(bill, handler: str | None, *, agent_name: str | None = None) -> None:
    bill.freight_handler = handler
    totals = dict(bill.totals_json or {})
    if agent_name:
        totals["freight_agent_name"] = agent_name
    if handler:
        totals["freight_handler"] = handler
    else:
        totals.pop("freight_handler", None)
    bill.totals_json = totals
    flag_modified(bill, "totals_json")


def apply_freight_handler(db, bill, raw: str | None) -> None:
    from app.models.freight_agent import FreightAgent

    agent = None
    if bill.freight_agent_id and (bill.transport_mode or "") == "bus":
        agent = db.get(FreightAgent, bill.freight_agent_id)
    handler = resolve_handler(agent.name if agent else None, raw)
    stamp_handler(bill, handler, agent_name=agent.name if agent else None)
