"""Phone-number normalization — one canonical form everywhere (Stage 0 fix).

The booking engine historically stored numbers raw (``9876500001``) while callers arrive with a
country code (``+919876500001``); that mismatch silently broke member/DNC matching (see
AUDIT_FINDINGS). Every outbound code path that compares numbers — especially the opt-out / DNC
check — MUST go through ``normalize_phone`` so a match can never be missed on formatting alone.
"""
from __future__ import annotations

import phonenumbers

DEFAULT_REGION = "IN"  # bare 10-digit numbers are interpreted as Indian


def normalize_phone(raw: str | None, region: str = DEFAULT_REGION) -> str | None:
    """Return the E.164 form (``+919876500001``) or None if it isn't a valid number.

    Handles the formats we actually see: bare 10-digit, 0-prefixed, spaced, and already-+91.
    """
    if not raw:
        return None
    s = str(raw).strip()
    try:
        parsed = phonenumbers.parse(s, None if s.startswith("+") else region)
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(parsed):
        return None
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def same_number(a: str | None, b: str | None, region: str = DEFAULT_REGION) -> bool:
    """True iff both parse to the same valid E.164 number (format-insensitive)."""
    na, nb = normalize_phone(a, region), normalize_phone(b, region)
    return na is not None and na == nb
