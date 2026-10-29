"""A payment stays in the account that was named. NC, cash, and ICICI are not one pot."""

from __future__ import annotations


def resolve_payment_account(
    selected_name: str | None,
    reference: str | None,
    known_names: list[str],
) -> tuple[str | None, str]:
    """Return (account, reference).

    If the reference is exactly an account name, that account wins. Typing NC
    in the reference must not land in cash.
    """
    ref = (reference or "").strip()
    selected = (selected_name or "").strip() or None
    match = next((name for name in known_names if name.lower() == ref.lower()), None) if ref else None
    account = match or selected
    if not ref:
        ref = account or "Payment"
    return account, ref
