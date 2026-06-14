"""Adversarial audit tests — probe suspected flaws found during the code review.

Each test documents the EXPECTED-CORRECT behaviour. A failing test here = a confirmed flaw.
These are written to expose bugs, so several are expected to fail until the engine is fixed.
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

from app.booking import errors
from app.booking.service import BookingService
from app.booking.slotgen import generate_slots
from app.db.models import (
    SECTION_STANDARD,
    SLOT_BLOCKED,
    Booking,
    Client,
    Court,
    Facility,
    Offering,
    Section,
    Slot,
    Sport,
)
from app.voice.tools import dispatch
from tests.factory import WORLD_DATE


T18 = dt.time(18, 0)
T19 = dt.time(19, 0)
T20 = dt.time(20, 0)


# ---------------------------------------------------------------------------
# 1. Phone-format consistency: bookings store the caller's raw phone string,
#    but group rules match Booking.customer_phone against Member.phone with a
#    raw SQL IN — so a "+91"-formatted booking must still trigger group rules.
# ---------------------------------------------------------------------------

def test_group_timeslot_rule_catches_plus91_formatted_booking(session, world):
    svc = BookingService(session, world.client_id)
    # Priya books with the Exotel-style caller ID (+91 prefix).
    svc.create_booking("Priya", "+919876500002", world.football_off, world.D, T19)
    # Rahul (same group) tries the same timeslot on another court — must be blocked.
    check = svc.check_group_restriction("9876500001", world.D, T19)
    assert check.allowed is False, (
        "FLAW: group one-per-timeslot rule missed because the booking stored "
        "'+919876500002' raw while Member.phone is '9876500002' (raw-string IN match)."
    )


def test_group_weekly_cap_counts_plus91_formatted_bookings(session, world):
    svc = BookingService(session, world.client_id)
    # Cap is 2 for Sunday League. Two bookings made with +91-formatted numbers.
    svc.create_booking("Priya", "+919876500002", world.football_off, world.D, T19)
    svc.create_booking("Priya", "+91 98765 00002", world.badminton_off, world.D, T20)
    # Third booking by Rahul in the same week must hit the cap.
    with pytest.raises(errors.GroupRestrictionViolation):
        svc.create_booking("Rahul", "9876500001", world.pickleball_off, world.D, T18)


def test_booking_phone_is_normalized_at_write_time(session, world):
    """Whatever +91/spacing format the caller uses, the stored phone is the normalized
    digits — so member matching, group rules, and owner lookups all agree."""
    svc = BookingService(session, world.client_id)
    svc.create_booking("Sam", "+91 90000 00000", world.football_off, world.D, T19)
    svc.create_booking("Sam", "09000000000", world.badminton_off, world.D, T19)
    stored = session.scalars(
        Booking.__table__.select().with_only_columns(Booking.customer_phone)
    ).all()
    assert set(stored) == {"9000000000"}


# ---------------------------------------------------------------------------
# 2. Time travel: nothing stops booking / offering slots in the past.
# ---------------------------------------------------------------------------

def test_booking_a_past_date_is_rejected(session, world):
    svc = BookingService(session, world.client_id, today=world.D + dt.timedelta(days=1))
    # world.D is now "yesterday" relative to the service's reference date.
    with pytest.raises(errors.BookingError):
        svc.create_booking("Late", "9111111111", world.football_off, world.D, T19)


def test_availability_excludes_past_dates(session, world):
    svc = BookingService(session, world.client_id, today=world.D + dt.timedelta(days=1))
    options = svc.check_availability("Football", world.D)
    assert options == [], "FLAW: yesterday's slots are still offered as bookable."


# ---------------------------------------------------------------------------
# 3. Blocked slots must not be bookable (availability already filters them).
# ---------------------------------------------------------------------------

def test_blocked_slot_not_bookable(session, world):
    from sqlalchemy import select, update

    slot_id = session.scalar(
        select(Slot.id)
        .where(Slot.court_id == world.turf_id, Slot.slot_date == world.D, Slot.start_time == T19)
    )
    session.execute(update(Slot).where(Slot.id == slot_id).values(status=SLOT_BLOCKED))
    session.commit()
    svc = BookingService(session, world.client_id)
    assert svc.check_availability("Football", world.D, T19) == []
    with pytest.raises(errors.BookingError):
        svc.create_booking("X", "9222222222", world.football_off, world.D, T19)


# ---------------------------------------------------------------------------
# 4. Reschedule edge cases.
# ---------------------------------------------------------------------------

def test_reschedule_to_same_time_is_a_safe_noop(session, world):
    svc = BookingService(session, world.client_id)
    conf = svc.create_booking("Ravi", "9333333333", world.football_off, world.D, T19)
    out = svc.reschedule_booking(conf.booking_id, world.D, T19)
    assert out.start_time == T19
    active = session.scalars(
        Booking.__table__.select().where(Booking.status == "confirmed")
    ).all()
    assert len(active) == 1


def test_failed_reschedule_must_not_lose_the_original_booking(session, world):
    """Reschedule a non-member's booking into the members-only 18:00 turf slot.
    The rule check raises AFTER the old rows were cancelled+flushed. The caller
    (REST layer) closes the session, rolling back — original must survive."""
    svc = BookingService(session, world.client_id)
    conf = svc.create_booking("Visitor", "9444444444", world.football_off, world.D, T19)
    with pytest.raises(errors.MembershipRequired):
        svc.reschedule_booking(conf.booking_id, world.D, T18)
    # Simulate what get_session/voice handler does after an exception: close/rollback.
    session.rollback()
    refreshed = session.get(Booking, conf.booking_id)
    assert refreshed.status == "confirmed", (
        "FLAW: a failed reschedule left the original booking cancelled."
    )


def test_reschedule_within_week_not_blocked_by_own_weekly_cap(session, world):
    svc = BookingService(session, world.client_id)
    c1 = svc.create_booking("Rahul", "9876500001", world.football_off, world.D, T19)
    svc.create_booking("Priya", "9876500002", world.badminton_off, world.D, T20)
    # Cap (2) reached. Moving an existing booking within the week must still work.
    out = svc.reschedule_booking(c1.booking_id, world.D + dt.timedelta(days=1), T19)
    assert out.slot_date == world.D + dt.timedelta(days=1)


# ---------------------------------------------------------------------------
# 5. Weekly cap calendar boundary (Mon–Sun).
# ---------------------------------------------------------------------------

def test_weekly_cap_resets_on_monday(session, world):
    # WORLD_DATE is a Wednesday. Sunday = +4 days, next Monday = +5 days.
    sunday = world.D + dt.timedelta(days=4)
    monday = world.D + dt.timedelta(days=5)
    # Extend the slot window so those dates exist.
    from sqlalchemy import select

    facility = session.scalar(select(Facility).where(Facility.client_id == world.client_id))
    turf = session.get(Court, world.turf_id)
    generate_slots(session, turf, facility, world.D + dt.timedelta(days=2), days=5)
    session.commit()

    svc = BookingService(session, world.client_id)
    svc.create_booking("Rahul", "9876500001", world.football_off, world.D, T19)       # Wed
    svc.create_booking("Priya", "9876500002", world.football_off, sunday, T19)        # Sun — cap (2) now full
    with pytest.raises(errors.GroupRestrictionViolation):
        svc.create_booking("Rahul", "9876500001", world.football_off, sunday, T20)    # 3rd in same week
    # New calendar week — must be allowed again.
    conf = svc.create_booking("Rahul", "9876500001", world.football_off, monday, T19)
    assert conf.slot_date == monday


# ---------------------------------------------------------------------------
# 6. Voice-tool input validation: empty / junk phone numbers.
# ---------------------------------------------------------------------------

def test_voice_tool_rejects_empty_phone(session, world):
    result = dispatch(session, world.client_id, "create_booking", {
        "name": "Ghost", "phone_number": "", "offering_id": world.football_off,
        "date": world.D.isoformat(), "time": "19:00",
    })
    assert "error" in result, (
        "FLAW: create_booking accepted an empty phone number — the facility "
        "has no way to reach the customer, and member/group matching is meaningless."
    )


def test_voice_tool_rejects_absurd_name(session, world):
    result = dispatch(session, world.client_id, "create_booking", {
        "name": "x" * 500, "phone_number": "9555555555",
        "offering_id": world.football_off, "date": world.D.isoformat(), "time": "19:00",
    })
    # String(200) column: SQLite silently accepts, Postgres would raise DataError mid-call.
    assert "error" in result or len(result.get("customer_name", "")) <= 200


# ---------------------------------------------------------------------------
# 7. Context blowout: check_availability without a time, on a realistic
#    full-size facility (6 courts, 06:00–23:00) — measures the JSON the LLM
#    would receive. Cerebras free tier context is 8K tokens.
# ---------------------------------------------------------------------------

def test_availability_payload_fits_voice_llm_context(session):
    client = Client(name="Big", business_name="Big Arena")
    session.add(client)
    session.flush()
    fac = Facility(client_id=client.id, name="Big", opening_time=dt.time(6, 0),
                   closing_time=dt.time(23, 0), slot_duration_minutes=60)
    session.add(fac)
    session.flush()
    badminton = Sport(client_id=client.id, name="Badminton")
    session.add(badminton)
    session.flush()
    for i in range(3):  # the seed's three badminton courts
        court = Court(client_id=client.id, facility_id=fac.id, name=f"Badminton {i}")
        session.add(court)
        session.flush()
        session.add(Section(client_id=client.id, court_id=court.id,
                            label=f"Badminton {i}", kind=SECTION_STANDARD, sort_order=0))
        session.flush()
        session.add(Offering(client_id=client.id, court_id=court.id, sport_id=badminton.id,
                             name="Badminton", price=500, sections_required=1, section_kind=None))
        session.flush()
        generate_slots(session, court, fac, WORLD_DATE, days=1)
    session.commit()

    result = dispatch(session, client.id, "check_availability",
                      {"sport": "Badminton", "date": WORLD_DATE.isoformat()})
    payload = json.dumps(result)
    approx_tokens = len(payload) / 4
    print(f"\n[measure] check_availability(no time) for ONE sport: {len(result['options'])} options, "
          f"{len(payload)} chars ≈ {approx_tokens:.0f} tokens")
    assert approx_tokens < 2000, (
        f"FLAW: a single no-time availability call returns ≈{approx_tokens:.0f} tokens of JSON; "
        "several of these plus the system prompt (~1.5K) + tools (~700) overflows the 8K context "
        "of the free Cerebras tier mid-call."
    )


# ---------------------------------------------------------------------------
# 8. Sport name handling from a bilingual LLM.
# ---------------------------------------------------------------------------

def test_sport_lookup_tolerates_whitespace_and_case(session, world):
    svc = BookingService(session, world.client_id)
    assert svc.check_availability("  FOOTBALL ", world.D, T19) != []


def test_sport_lookup_in_hindi_script_finds_nothing(session, world):
    """Documents (not asserts-correct) that a Devanagari sport name silently returns
    'no availability' instead of an explicit 'unknown sport' signal the LLM could react to."""
    svc = BookingService(session, world.client_id)
    assert svc.check_availability("फुटबॉल", world.D, T19) == []
