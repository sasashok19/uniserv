"""Identity normalisation (Feature 03, Phase 1 — plain text).

PHASE_2 will replace direct field matching with HMAC blind-index lookups.
"""

import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberFormat

from app.config import settings


def normalise_phone(raw: str, region: str | None = None) -> str:
    """Normalise a phone number to E.164 (e.g. '+919876543210').

    Raises ValueError if the number cannot be parsed.
    """
    if raw is None or not raw.strip():
        raise ValueError("phone is empty")
    raw = raw.strip()
    # A leading '+' means the number is already international; no region needed.
    default_region = None if raw.startswith("+") else (region or settings.default_region)
    try:
        parsed = phonenumbers.parse(raw, default_region)
    except NumberParseException as exc:
        raise ValueError(f"invalid phone number: {raw}") from exc
    return phonenumbers.format_number(parsed, PhoneNumberFormat.E164)


def normalise_email(raw: str) -> str:
    """Lowercase, strip Gmail-style '+' aliases from the local part."""
    if raw is None or "@" not in raw:
        raise ValueError(f"invalid email: {raw}")
    local, _, domain = raw.strip().lower().partition("@")
    local = local.split("+")[0]
    return f"{local}@{domain}"
