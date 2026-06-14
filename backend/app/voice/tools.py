"""The booking tools the LLM calls mid-conversation (book, check, cancel, reschedule), plus a
framework-agnostic dispatcher.

``ANTHROPIC_TOOLS`` is the tool list in Anthropic's tool-use format. ``dispatch`` executes a single
tool call against the booking engine and returns a JSON-serializable dict (success payload or a
structured error the model can speak gracefully).

Booking flow: ``check_availability`` returns bookable *options* (each with an ``offering_id`` and a
price); the model offers one to the caller, then passes that ``offering_id`` back to
``create_booking``. The engine allocates the right sections (e.g. a full-court basketball booking
reserves all three sections atomically).
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy.orm import Session

from app.booking import errors
from app.booking.service import BookingService

ANTHROPIC_TOOLS: list[dict[str, Any]] = [
    {
        "name": "check_availability",
        "description": (
            "List bookable options for a sport on a date, optionally at a specific start time. "
            "One sport can have several options (e.g. half-court vs full-court basketball), each "
            "returned separately with its own 'offering_id', 'option_name', 'court_name', and "
            "'price' (INR for non-members; active members book free). Pass the chosen 'offering_id' "
            "to create_booking. Never returns who booked anything."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sport": {"type": "string", "description": "Sport, e.g. Football, Pickleball, Basketball"},
                "date": {"type": "string", "description": "Date as YYYY-MM-DD"},
                "time": {"type": "string", "description": "Optional 24-hour start time HH:MM"},
            },
            "required": ["sport", "date"],
        },
    },
    {
        "name": "verify_member",
        "description": (
            "Check whether a phone number belongs to an active member (may book members-only slots "
            "and books free). Does not return the member's name."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"phone_number": {"type": "string"}},
            "required": ["phone_number"],
        },
    },
    {
        "name": "check_group_restriction",
        "description": (
            "Check whether booking a given date+time would violate the caller's group rules "
            "(another group member already holds that time, or the group's weekly limit is reached). "
            "create_booking also enforces this; use this to check proactively."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "phone_number": {"type": "string"},
                "date": {"type": "string", "description": "YYYY-MM-DD"},
                "time": {"type": "string", "description": "24-hour HH:MM"},
            },
            "required": ["phone_number", "date", "time"],
        },
    },
    {
        "name": "create_booking",
        "description": (
            "Finalize a booking for a specific option. Pass the 'offering_id' from "
            "check_availability. Enforces availability, membership, and group rules, and allocates "
            "the needed sections. On success returns the confirmation including 'amount' (INR "
            "charged; 0 for active members), 'sections', and 'option_name'. On failure returns an "
            "error code (slot_unavailable, membership_required, group_restriction, slot_not_found)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "phone_number": {"type": "string"},
                "offering_id": {"type": "integer", "description": "offering_id from check_availability"},
                "date": {"type": "string", "description": "YYYY-MM-DD"},
                "time": {"type": "string", "description": "24-hour HH:MM"},
            },
            "required": ["name", "phone_number", "offering_id", "date", "time"],
        },
    },
    {
        "name": "get_next_available_slot",
        "description": (
            "Find the earliest available option for a sport from a date onward. Use to offer an "
            "alternative when the requested time is taken. Returns an option with its offering_id."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sport": {"type": "string"},
                "date": {"type": "string", "description": "YYYY-MM-DD"},
            },
            "required": ["sport", "date"],
        },
    },
    {
        "name": "find_my_bookings",
        "description": (
            "List the caller's own upcoming bookings, matched by their phone number. Use when "
            "the caller asks what they have booked, or before cancelling/rescheduling. Only ever "
            "pass the caller's own number — never look up someone else's."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"phone_number": {"type": "string"}},
            "required": ["phone_number"],
        },
    },
    {
        "name": "cancel_my_booking",
        "description": (
            "Cancel the caller's own booking, located by their phone number and the booking "
            "date (add the time if they have several that day). Confirm with the caller before "
            "calling this — it frees the slot immediately."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "phone_number": {"type": "string"},
                "date": {"type": "string", "description": "YYYY-MM-DD"},
                "time": {"type": "string", "description": "Optional 24-hour HH:MM"},
            },
            "required": ["phone_number", "date"],
        },
    },
    {
        "name": "reschedule_my_booking",
        "description": (
            "Move the caller's own booking to a new date/time, located by their phone number "
            "and the current booking date (+ time if they have several that day). The same "
            "option/court is kept; if the new time is full, nothing changes and an error returns."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "phone_number": {"type": "string"},
                "date": {"type": "string", "description": "Current booking date YYYY-MM-DD"},
                "time": {"type": "string", "description": "Current booking time HH:MM (if several that day)"},
                "new_date": {"type": "string", "description": "New date YYYY-MM-DD"},
                "new_time": {"type": "string", "description": "New 24-hour time HH:MM"},
            },
            "required": ["phone_number", "date", "new_date", "new_time"],
        },
    },
]

# Cap how many availability options a single tool result hands the LLM. A full free day can be
# 50+ options (~3.3K tokens of JSON) — enough to overflow the 8K-context free LLM tier mid-call.
MAX_VOICE_OPTIONS = 10


def _parse_date(value: str) -> dt.date:
    return dt.date.fromisoformat(value.strip())


def _parse_time(value: str) -> dt.time:
    parts = value.strip().split(":")
    if len(parts) < 2:
        raise ValueError(f"Invalid time '{value}', expected HH:MM")
    return dt.time(int(parts[0]), int(parts[1]))


def dispatch(session: Session, client_id: int, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute one tool call and return a JSON-serializable result dict."""
    svc = BookingService(session, client_id)
    try:
        if name == "check_availability":
            time = arguments.get("time")
            options = svc.check_availability(
                arguments["sport"],
                _parse_date(arguments["date"]),
                _parse_time(time) if time else None,
            )
            result = {"options": [o.model_dump(mode="json") for o in options[:MAX_VOICE_OPTIONS]]}
            if len(options) > MAX_VOICE_OPTIONS:
                result["note"] = (
                    f"{len(options) - MAX_VOICE_OPTIONS} more times are free that day; "
                    "ask the caller what time suits them instead of listing everything."
                )
            return result

        if name == "verify_member":
            return svc.verify_member(arguments["phone_number"]).model_dump(mode="json")

        if name == "check_group_restriction":
            result = svc.check_group_restriction(
                arguments["phone_number"],
                _parse_date(arguments["date"]),
                _parse_time(arguments["time"]),
            )
            return result.model_dump(mode="json")

        if name == "create_booking":
            confirmation = svc.create_booking(
                name=arguments["name"],
                phone=arguments["phone_number"],
                offering_id=int(arguments["offering_id"]),
                date=_parse_date(arguments["date"]),
                time=_parse_time(arguments["time"]),
                source="voice",
            )
            return {"booked": True, **confirmation.model_dump(mode="json")}

        if name == "get_next_available_slot":
            option = svc.get_next_available_slot(arguments["sport"], _parse_date(arguments["date"]))
            return {"option": option.model_dump(mode="json") if option else None}

        if name == "find_my_bookings":
            bookings = svc.find_bookings_for_phone(arguments["phone_number"])
            return {"bookings": [b.model_dump(mode="json") for b in bookings[:5]]}

        if name == "cancel_my_booking":
            time = arguments.get("time")
            summary = svc.cancel_booking_for_phone(
                arguments["phone_number"],
                _parse_date(arguments["date"]),
                _parse_time(time) if time else None,
            )
            return {"cancelled": True, **summary.model_dump(mode="json")}

        if name == "reschedule_my_booking":
            time = arguments.get("time")
            confirmation = svc.reschedule_booking_for_phone(
                arguments["phone_number"],
                _parse_date(arguments["date"]),
                _parse_time(time) if time else None,
                _parse_date(arguments["new_date"]),
                _parse_time(arguments["new_time"]),
            )
            return {"rescheduled": True, **confirmation.model_dump(mode="json")}

        return {"error": "unknown_tool", "message": f"No tool named {name}."}

    except errors.BookingError as exc:
        return {"error": exc.code, "message": exc.message}
    except (KeyError, ValueError) as exc:
        return {"error": "bad_input", "message": str(exc)}
