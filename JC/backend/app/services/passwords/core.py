from __future__ import annotations

import secrets

import bcrypt

# Easy to read/type from WhatsApp — no I/O/0/1 ambiguity
_PORTAL_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def generate_portal_password(length: int = 8) -> str:
    """Unique customer portal password (not guessable from phone)."""
    n = max(6, min(int(length or 8), 16))
    return "".join(secrets.choice(_PORTAL_ALPHABET) for _ in range(n))


def customer_portal_password(name: str, phone: str) -> str:
    """First word of the name, @, then the first four digits of the mobile."""
    parts = (name or "").strip().split()
    word = parts[0] if parts else "PARTY"
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if len(digits) > 10 and digits.startswith("91"):
        digits = digits[-10:]
    four = (digits + "0000")[:4]
    return f"{word}@{four}"


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("ascii"))
    except ValueError:
        return False
