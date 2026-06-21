"""Outbound conversation tools — the actions the goal-driven bot can take on an outbound call.

Each returns a ``ToolResult`` carrying a short Hinglish line to speak, whether the call should end,
and the resulting disposition. Booking changes reuse ``BookingService`` (same engine as inbound);
opt-out persists to the permanent ``OptOut`` list so the number is never dialed again.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import select

from app.booking import errors
from app.booking.service import BookingService
from app.db.models import (
    DISPOSITION_CALLBACK_REQUESTED,
    DISPOSITION_CONFIRMED,
    DISPOSITION_OPT_OUT,
    DISPOSITION_REFUSED,
    DISPOSITION_RESCHEDULED,
    DISPOSITION_WRONG_NUMBER,
    OptOut,
)
from app.voice.phone import normalize_phone


@dataclass
class ToolResult:
    ok: bool
    message: str
    end_call: bool = False
    disposition: str | None = None
    action: str | None = None  # e.g. "transfer"


def _date(s: str) -> dt.date:
    return dt.date.fromisoformat(str(s).strip())


def _time(s: str) -> dt.time:
    h, m = str(s).strip().split(":")[:2]
    return dt.time(int(h), int(m))


def _already_opted(session, client_id: int, phone: str) -> bool:
    return session.scalar(select(OptOut).where(OptOut.client_id == client_id, OptOut.phone == phone)) is not None


def _persist_optout(session, contact, reason: str) -> None:
    phone = normalize_phone(contact.phone) or contact.phone
    if not _already_opted(session, contact.client_id, phone):
        session.add(OptOut(client_id=contact.client_id, phone=phone, reason=reason, source="call"))
    contact.dnc = True


def confirm_booking(session, contact, campaign) -> ToolResult:
    """Caller confirms the existing booking — goal achieved."""
    return ToolResult(True, "Perfect — aapki booking confirm hai. Dhanyavaad! 🙏", end_call=True, disposition=DISPOSITION_CONFIRMED)


def reschedule_booking(session, contact, campaign, *, new_date: str, new_time: str) -> ToolResult:
    """Move the booking to a new date/time (reuses the booking engine; same court/option kept)."""
    ctx = contact.context_json or {}
    phone = ctx.get("booking_phone") or contact.phone
    svc = BookingService(session, contact.client_id)
    try:
        svc.reschedule_booking_for_phone(
            phone,
            _date(ctx["booking_date"]),
            _time(ctx["booking_time"]) if ctx.get("booking_time") else None,
            _date(new_date),
            _time(new_time),
        )
    except errors.BookingError:
        return ToolResult(False, "Us time pe slot available nahi hai — koi aur time bataaiye?")
    except (KeyError, ValueError):
        return ToolResult(True, "Theek hai, team aapko callback de degi.", end_call=True, disposition=DISPOSITION_CALLBACK_REQUESTED)
    return ToolResult(True, "Ho gaya — aapki booking move kar di. Dhanyavaad!", end_call=True, disposition=DISPOSITION_RESCHEDULED)


def cancel_booking(session, contact, campaign) -> ToolResult:
    """Caller doesn't want the booking — cancel it (frees the slot) and close."""
    ctx = contact.context_json or {}
    phone = ctx.get("booking_phone") or contact.phone
    svc = BookingService(session, contact.client_id)
    try:
        svc.cancel_booking_for_phone(
            phone,
            _date(ctx["booking_date"]),
            _time(ctx["booking_time"]) if ctx.get("booking_time") else None,
        )
    except (errors.BookingError, KeyError, ValueError):
        pass  # nothing to cancel / already gone — still a refusal outcome
    return ToolResult(True, "Theek hai, maine booking cancel kar di. Dhanyavaad!", end_call=True, disposition=DISPOSITION_REFUSED)


def opt_out(session, contact, campaign, *, reason: str = "caller requested") -> ToolResult:
    """Honor 'stop calling' IMMEDIATELY: persist to the permanent DNC list, apologize, end."""
    _persist_optout(session, contact, reason)
    return ToolResult(True, "Zaroor — main aapko dobara call nahi karungi. Aapka din shubh ho! 🙏", end_call=True, disposition=DISPOSITION_OPT_OUT)


def log_callback(session, contact, campaign, *, when_hint: str | None = None) -> ToolResult:
    """Caller is busy / wants a callback — log it and close politely."""
    return ToolResult(True, "Bilkul, hamari team aapko baad mein call karegi. Dhanyavaad!", end_call=True, disposition=DISPOSITION_CALLBACK_REQUESTED)


def transfer_to_human(session, contact, campaign) -> ToolResult:
    """Hand off to a live agent (real flow bridges a second leg; here we flag it)."""
    return ToolResult(True, "Main aapko hamari team se connect karti hoon — ek minute.", end_call=True, disposition=DISPOSITION_CALLBACK_REQUESTED, action="transfer")


def wrong_number(session, contact, campaign) -> ToolResult:
    """Reached the wrong person — apologize, mark so we never dial this number again."""
    _persist_optout(session, contact, "wrong_number")
    return ToolResult(True, "Oh, maaf kijiye — galti se call ho gaya. Aapka din achha rahe!", end_call=True, disposition=DISPOSITION_WRONG_NUMBER)
