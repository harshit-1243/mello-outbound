"""Edge-case tests that don't fit neatly into the other files.

These fill identified gaps: voice-tool note field, next-available cross-day search,
Hindi-script sport lookup signal, and voice-tool input validation completeness.
"""
from __future__ import annotations

import datetime as dt

import pytest

from app.booking.service import BookingService
from app.voice.tools import MAX_VOICE_OPTIONS, dispatch
from tests.factory import WORLD_DATE


T18 = dt.time(18, 0)
T19 = dt.time(19, 0)
T20 = dt.time(20, 0)


# ---------------------------------------------------------------------------
# 1. check_availability voice tool: note field on capped results.
# ---------------------------------------------------------------------------

def test_availability_note_present_when_results_are_capped(session):
    """When a sport has more than MAX_VOICE_OPTIONS available options the tool must
    attach a 'note' telling the LLM to ask the caller for a preferred time instead
    of listing everything — prevents token overflow in the mid-call context."""
    from tests.factory import build_world
    from app.booking.slotgen import generate_slots
    from sqlalchemy import select
    from app.db.models import Court, Facility, Offering, Sport, Section, Client
    from app.db.models import SECTION_STANDARD

    # Build a facility with a single court open 06:00–23:00 (17 hourly slots = 17 options).
    client = Client(name="Big", business_name="Overflow Arena")
    session.add(client)
    session.flush()
    fac = Facility(client_id=client.id, name="Overflow", opening_time=dt.time(6, 0),
                   closing_time=dt.time(23, 0), slot_duration_minutes=60)
    session.add(fac)
    session.flush()
    sport = Sport(client_id=client.id, name="Tennis")
    session.add(sport)
    session.flush()
    court = Court(client_id=client.id, facility_id=fac.id, name="Court 1")
    session.add(court)
    session.flush()
    section = Section(client_id=client.id, court_id=court.id, label="Court 1",
                      kind=SECTION_STANDARD, sort_order=0)
    session.add(section)
    session.flush()
    off = Offering(client_id=client.id, court_id=court.id, sport_id=sport.id,
                   name="Tennis", price=600, sections_required=1, section_kind=None)
    session.add(off)
    session.flush()
    generate_slots(session, court, fac, WORLD_DATE, days=1)
    session.commit()

    result = dispatch(session, client.id, "check_availability",
                      {"sport": "Tennis", "date": WORLD_DATE.isoformat()})

    assert len(result["options"]) == MAX_VOICE_OPTIONS, (
        f"Expected exactly {MAX_VOICE_OPTIONS} options; got {len(result['options'])}"
    )
    assert "note" in result, (
        "FLAW: no 'note' key when results were capped — the LLM has no signal that "
        "more times exist and will assume the list is exhaustive."
    )
    assert "more" in result["note"].lower()


# ---------------------------------------------------------------------------
# 2. get_next_available_slot: must advance to the next day when today is full.
# ---------------------------------------------------------------------------

def test_next_available_advances_to_next_day_when_today_full(session, world):
    """If every slot on the requested date is taken, get_next_available_slot must
    return a slot on the following day rather than None."""
    svc = BookingService(session, world.client_id)

    # Fill all badminton slots on world.D (18:00, 19:00, 20:00).
    svc.create_booking("A", "9100000001", world.badminton_off, world.D, T18)
    svc.create_booking("B", "9100000002", world.badminton_off, world.D, T19)
    svc.create_booking("C", "9100000003", world.badminton_off, world.D, T20)

    # Today is fully booked; next slot must be on world.D + 1.
    nxt = svc.get_next_available_slot("Badminton", world.D)
    assert nxt is not None, "FLAW: returned None instead of searching the next day."
    assert nxt.slot_date == world.D + dt.timedelta(days=1)
    assert nxt.sport == "Badminton"


# ---------------------------------------------------------------------------
# 3. Hindi-script sport lookup: documents (and pins) the current behaviour.
# ---------------------------------------------------------------------------

def test_sport_lookup_devanagari_returns_empty_not_error(session, world):
    """A Devanagari sport name (e.g. 'फुटबॉल') currently returns an empty options
    list — the same response as 'no availability'. This test documents that behaviour.

    The ideal fix is to return {"options": [], "unknown_sport": True} so the LLM
    can distinguish 'I don't know that sport' from 'nothing free today'. Until that
    fix lands, this test ensures the response at least doesn't crash or hallucinate.
    """
    result = dispatch(session, world.client_id, "check_availability",
                      {"sport": "फुटबॉल", "date": world.D.isoformat()})
    assert "error" not in result, "Should not crash on Devanagari sport name."
    assert result.get("options") == [], (
        "Expected empty options list for an unrecognised sport name."
    )
    # Document the missing signal: ideally this would also assert unknown_sport=True.
    # assert result.get("unknown_sport") is True  # <-- uncomment after fix


# ---------------------------------------------------------------------------
# 4. create_booking voice tool: phone validation completeness.
# ---------------------------------------------------------------------------

def test_voice_tool_rejects_phone_too_short(session, world):
    """A 3-digit phone number is not a valid contact — create_booking must reject it."""
    result = dispatch(session, world.client_id, "create_booking", {
        "name": "Ghost", "phone_number": "123",
        "offering_id": world.football_off, "date": world.D.isoformat(), "time": "19:00",
    })
    assert "error" in result, (
        "FLAW: create_booking accepted a 3-digit phone number — "
        "member/group matching and WhatsApp delivery would silently fail."
    )


def test_voice_tool_rejects_phone_with_letters(session, world):
    """A phone string containing letters must be rejected, not stored."""
    result = dispatch(session, world.client_id, "create_booking", {
        "name": "Robot", "phone_number": "abcdefghij",
        "offering_id": world.football_off, "date": world.D.isoformat(), "time": "19:00",
    })
    assert "error" in result, (
        "FLAW: create_booking accepted a non-numeric phone number."
    )


# ---------------------------------------------------------------------------
# 5. find_my_bookings: upcoming-only filter (past bookings not shown to caller).
# ---------------------------------------------------------------------------

def test_find_my_bookings_excludes_past_bookings(session, world):
    """Bookings on a past date must not appear in find_my_bookings results — a caller
    can't cancel something that's already happened, and showing it is confusing.

    We simulate 'yesterday' by creating a booking on world.D, then querying with
    today=world.D + 1 so that world.D becomes a past date from the service's
    perspective. This is the correct way to test time-relative logic without
    mutating the DB slot dates (which would also invalidate other slot queries).
    """
    svc_now = BookingService(session, world.client_id)
    svc_now.create_booking("Time Traveller", "9800000099", world.football_off, world.D, T19)

    # From the perspective of 'tomorrow', world.D is yesterday.
    tomorrow = world.D + dt.timedelta(days=1)
    svc_tomorrow = BookingService(session, world.client_id, today=tomorrow)
    bookings = svc_tomorrow.find_bookings_for_phone("9800000099")

    assert bookings == [], (
        "FLAW: find_my_bookings returned a past-dated booking — "
        "callers should only see upcoming bookings they can still act on."
    )


# ---------------------------------------------------------------------------
# 6. Reschedule into a past time is rejected.
# ---------------------------------------------------------------------------

def test_reschedule_my_booking_to_past_is_rejected(session, world):
    """Rescheduling to a date in the past must be rejected with an error, not silently
    move the booking to an unreachable slot."""
    out = dispatch(session, world.client_id, "create_booking", {
        "name": "Mover", "phone_number": "9700000011",
        "offering_id": world.badminton_off, "date": world.D.isoformat(), "time": "18:00",
    })
    assert out.get("booked") is True

    yesterday = world.D - dt.timedelta(days=1)
    result = dispatch(session, world.client_id, "reschedule_my_booking", {
        "phone_number": "9700000011",
        "date": world.D.isoformat(),
        "new_date": yesterday.isoformat(),
        "new_time": "18:00",
    })
    assert "error" in result, (
        "FLAW: reschedule_my_booking accepted a past date — "
        "the booking would be unreachable and the slot wasted."
    )
