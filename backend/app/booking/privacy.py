"""Privacy layer.

The playbook requires that booking identities are *never* exposed to third-party callers. The
booking service already avoids returning names from availability queries; this module centralizes
the one place a name may be revealed — to the booking's own owner (matched by phone) — so the rule
is explicit and testable.
"""
from __future__ import annotations

from app.booking.util import normalize_phone
from app.db.models import Booking

REDACTED = "(private)"


def name_for_requester(booking: Booking, requester_phone: str | None) -> str:
    """Return the customer name only if the requester owns the booking; else a redacted marker."""
    if requester_phone and normalize_phone(requester_phone) == normalize_phone(booking.customer_phone):
        return booking.customer_name
    return REDACTED
