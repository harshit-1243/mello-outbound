"""Domain exceptions for the booking engine.

Each carries a ``code`` (stable, for tools/clients) and a human-readable message. The voice layer
maps these to natural spoken responses; the REST API maps them to HTTP 409/404/422.
"""
from __future__ import annotations


class BookingError(Exception):
    code = "booking_error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class SlotNotFound(BookingError):
    code = "slot_not_found"


class SlotUnavailable(BookingError):
    """The requested slot is already booked or blocked."""

    code = "slot_unavailable"


class MembershipRequired(BookingError):
    """Slot is reserved for active members and the caller is not one."""

    code = "membership_required"


class GroupRestrictionViolation(BookingError):
    """Another member of the caller's group already holds this time slot."""

    code = "group_restriction"


class InvalidInput(BookingError):
    """Caller-supplied data is unusable (empty name, junk phone number, ...)."""

    code = "invalid_input"
