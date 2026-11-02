"""How a customer is named on screens, statements, and receipts."""

from __future__ import annotations


def format_party_label(
    name: str | None,
    city: str | None = None,
    marker_1: str | None = None,
    marker_2: str | None = None,
) -> str:
    base = (name or "").strip()
    place = (city or "").strip()
    if place:
        base = f"{base} — {place}" if base else place
    marks = " ".join(part.strip() for part in (marker_1, marker_2) if part and str(part).strip())
    if marks:
        return f"{base} · {marks}" if base else marks
    return base
