"""Behavioural tests for the booking engine — the rules that must never break."""
from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.booking import errors, privacy
from app.booking.service import BookingService
from app.db.models import Booking, Section, Slot

T18, T19, T20 = dt.time(18, 0), dt.time(19, 0), dt.time(20, 0)


def svc(session, world) -> BookingService:
    return BookingService(session, world.client_id)


# ---- availability / options ----

def test_availability_returns_priced_options(session, world):
    opts = svc(session, world).check_availability("Football", world.D)
    assert {o.start_time for o in opts} == {T18, T19, T20}
    assert all(o.offering_id == world.football_off and o.price == 1200 for o in opts)
    assert next(o for o in opts if o.start_time == T18).is_member_only is True  # peak turf


def test_basketball_lists_half_and_full_options(session, world):
    opts = svc(session, world).check_availability("Basketball", world.D, T19)
    prices = {o.option_name: o.price for o in opts}
    assert prices == {"Basketball (3-point)": 700, "Basketball (full court)": 1000}


def test_unknown_sport_is_empty(session, world):
    assert svc(session, world).check_availability("Hockey", world.D) == []


# ---- shared turf: football / cricket mutual exclusion ----

def test_football_and_cricket_share_the_turf(session, world):
    s = svc(session, world)
    s.create_booking("U", world.stranger, world.football_off, world.D, T19)
    assert s.check_availability("Cricket", world.D, T19) == []
    with pytest.raises(errors.SlotUnavailable):
        s.create_booking("V", "9000000022", world.cricket_off, world.D, T19)


# ---- pickleball: 3 concurrent, middle filled first ----

def test_pickleball_three_concurrent_middle_first(session, world):
    s = svc(session, world)
    c1 = s.create_booking("P1", world.stranger, world.pickleball_off, world.D, T19)
    assert c1.sections == ["Middle"]  # keep rims open for basketball
    c2 = s.create_booking("P2", "9000000031", world.pickleball_off, world.D, T19)
    c3 = s.create_booking("P3", "9000000032", world.pickleball_off, world.D, T19)
    assert sorted(c2.sections + c3.sections) == ["Rim A", "Rim C"]
    with pytest.raises(errors.SlotUnavailable):
        s.create_booking("P4", "9000000033", world.pickleball_off, world.D, T19)


# ---- half-court basketball: rim only, max two ----

def test_half_court_uses_rims_only_then_middle_free_for_pickleball(session, world):
    s = svc(session, world)
    h1 = s.create_booking("H1", world.stranger, world.bball_half_off, world.D, T20)
    h2 = s.create_booking("H2", "9000000041", world.bball_half_off, world.D, T20)
    assert sorted(h1.sections + h2.sections) == ["Rim A", "Rim C"]
    with pytest.raises(errors.SlotUnavailable):  # no rim left
        s.create_booking("H3", "9000000042", world.bball_half_off, world.D, T20)
    # The middle is still bookable for pickleball alongside the two half-courts.
    p = s.create_booking("P", "9000000043", world.pickleball_off, world.D, T20)
    assert p.sections == ["Middle"]


# ---- full-court basketball: all three sections, atomic, blocks everything ----

def test_full_court_books_all_sections_atomically(session, world):
    s = svc(session, world)
    conf = s.create_booking("F", world.stranger, world.bball_full_off, world.D, T19)
    assert sorted(conf.sections) == ["Middle", "Rim A", "Rim C"] and conf.amount == 1000
    rows = session.scalars(
        select(Booking).where(Booking.booking_group_id == conf.booking_group_id)
    ).all()
    assert len(rows) == 3 and sum(1 for r in rows if r.is_primary) == 1
    assert s.check_availability("Pickleball", world.D, T19) == []
    assert s.check_availability("Basketball", world.D, T19) == []


def test_full_court_blocked_when_a_section_is_taken(session, world):
    s = svc(session, world)
    s.create_booking("P", world.stranger, world.pickleball_off, world.D, T19)  # takes middle
    assert all(o.option_name != "Basketball (full court)"
               for o in s.check_availability("Basketball", world.D, T19))
    with pytest.raises(errors.SlotUnavailable):
        s.create_booking("F", "9000000051", world.bball_full_off, world.D, T19)


# ---- double-booking guarantee ----

def test_double_booking_same_section_raises(session, world):
    s = svc(session, world)
    s.create_booking("A", "9000000011", world.football_off, world.D, T20)
    with pytest.raises(errors.SlotUnavailable):
        s.create_booking("B", "9000000012", world.football_off, world.D, T20)


def test_partial_unique_index_blocks_duplicate_confirmed(session, world):
    s = svc(session, world)
    conf = s.create_booking("A", "9000000011", world.football_off, world.D, T19)
    first = session.get(Booking, conf.booking_id)
    session.add(Booking(
        client_id=first.client_id, slot_id=first.slot_id, court_id=first.court_id,
        section_id=first.section_id, sport_id=first.sport_id, offering_id=first.offering_id,
        customer_name="B", customer_phone="2", status="confirmed",
    ))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_cancelled_booking_frees_the_section(session, world):
    s = svc(session, world)
    conf = s.create_booking("Temp", world.stranger, world.football_off, world.D, T19)
    booking = session.get(Booking, conf.booking_id)
    booking.status = "cancelled"
    session.commit()
    conf2 = s.create_booking("New", "9000000099", world.football_off, world.D, T19)
    assert conf2.booking_id != conf.booking_id


def test_booking_nonexistent_time_raises_not_found(session, world):
    with pytest.raises(errors.SlotNotFound):
        svc(session, world).create_booking("X", world.stranger, world.football_off, world.D, dt.time(7, 0))


# ---- membership ----

def test_member_only_slot_requires_active_member(session, world):
    s = svc(session, world)
    with pytest.raises(errors.MembershipRequired):
        s.create_booking("Stranger", world.stranger, world.football_off, world.D, T18)
    with pytest.raises(errors.MembershipRequired):  # expired member
        s.create_booking("Amit", world.amit, world.football_off, world.D, T18)
    conf = s.create_booking("Rahul", world.rahul, world.football_off, world.D, T18)
    assert conf.booking_id


def test_verify_member_and_phone_normalization(session, world):
    s = svc(session, world)
    assert s.verify_member(world.rahul).can_book_member_only is True
    amit = s.verify_member(world.amit)
    assert amit.is_member is True and amit.status == "expired" and amit.can_book_member_only is False
    assert s.verify_member(world.stranger).is_member is False
    assert s.verify_member("+919876500001").is_member is True
    assert s.verify_member("098765 00001").is_member is True


def test_membership_auto_expires_by_date(session, world):
    before = BookingService(session, world.client_id, today=dt.date(2025, 6, 1))
    assert before.verify_member(world.rahul).can_book_member_only is True
    after = BookingService(session, world.client_id, today=dt.date(2099, 6, 1))
    info = after.verify_member(world.rahul)
    assert info.can_book_member_only is False and info.status == "expired"


# ---- pricing ----

def test_pricing_per_offering_member_free(session, world):
    s = svc(session, world)
    nonmember = s.create_booking("Stranger", world.stranger, world.football_off, world.D, T19)
    assert nonmember.amount == 1200 and nonmember.is_member_booking is False
    member = s.create_booking("Rahul", world.rahul, world.football_off, world.D, T20)
    assert member.amount == 0 and member.is_member_booking is True
    half = s.create_booking("H", "9000000061", world.bball_half_off, world.D, T19)
    assert half.amount == 700
    full = s.create_booking("F", "9000000062", world.bball_full_off, world.D, T20)
    assert full.amount == 1000


# ---- group restriction ----

def test_group_restriction_blocks_same_timeslot(session, world):
    s = svc(session, world)
    s.create_booking("Rahul", world.rahul, world.football_off, world.D, T19)
    # Priya (same group) blocked at the same time, even on a different court.
    with pytest.raises(errors.GroupRestrictionViolation):
        s.create_booking("Priya", world.priya, world.pickleball_off, world.D, T19)
    assert s.check_group_restriction(world.priya, world.D, T19).allowed is False
    assert s.check_group_restriction(world.stranger, world.D, T19).allowed is True
    assert s.check_group_restriction(world.priya, world.D, T20).allowed is True


def test_group_weekly_cap_blocks_excess(session, world):
    s = svc(session, world)
    s.create_booking("Rahul", world.rahul, world.football_off, world.D, T19)
    s.create_booking("Priya", world.priya, world.football_off, world.D + dt.timedelta(days=1), T19)
    with pytest.raises(errors.GroupRestrictionViolation):  # cap = 2 reached this week
        s.create_booking("Rahul", world.rahul, world.football_off, world.D + dt.timedelta(days=1), T20)


# ---- next available ----

def test_next_available_option_advances(session, world):
    s = svc(session, world)
    nxt = s.get_next_available_slot("Badminton", world.D)
    assert nxt is not None and nxt.start_time == T18 and nxt.offering_id == world.badminton_off
    s.create_booking("X", world.stranger, world.badminton_off, world.D, T18)
    assert s.get_next_available_slot("Badminton", world.D).start_time == T19


# ---- privacy ----

def test_privacy_name_only_for_owner(session, world):
    conf = svc(session, world).create_booking("Rahul Sharma", world.rahul, world.football_off, world.D, T20)
    booking = session.get(Booking, conf.booking_id)
    assert privacy.name_for_requester(booking, world.rahul) == "Rahul Sharma"
    assert privacy.name_for_requester(booking, "+919876500001") == "Rahul Sharma"
    assert privacy.name_for_requester(booking, world.stranger) == privacy.REDACTED
    assert privacy.name_for_requester(booking, None) == privacy.REDACTED


# ---- dashboard: list / cancel / reschedule ----

def test_list_bookings_one_row_per_logical_booking(session, world):
    s = svc(session, world)
    s.create_booking("Solo", world.stranger, world.football_off, world.D, T19)
    s.create_booking("Baller", "9000000071", world.bball_full_off, world.D, T19)  # 3 sections
    rows = s.list_bookings()
    assert len(rows) == 2  # full-court counts once, not three times
    full = next(r for r in rows if r.option_name == "Basketball (full court)")
    assert sorted(full.sections) == ["Middle", "Rim A", "Rim C"] and full.amount == 1000


def test_cancel_frees_all_sections(session, world):
    s = svc(session, world)
    conf = s.create_booking("Baller", world.stranger, world.bball_full_off, world.D, T19)
    assert s.check_availability("Pickleball", world.D, T19) == []  # court full
    s.cancel_booking(conf.booking_id)
    # All three section rows cancelled, and the court is bookable again.
    assert s.list_bookings() == []
    assert len(s.check_availability("Pickleball", world.D, T19)) == 1


def test_reschedule_moves_booking_and_frees_old_time(session, world):
    s = svc(session, world)
    conf = s.create_booking("Mover", world.stranger, world.football_off, world.D, T19)
    moved = s.reschedule_booking(conf.booking_id, world.D, T20)
    assert moved.start_time == T20
    # Old time is free again; new time is taken.
    assert len(s.check_availability("Football", world.D, T19)) == 1
    assert s.check_availability("Football", world.D, T20) == []


def test_reschedule_to_taken_time_keeps_original(session, world):
    s = svc(session, world)
    conf = s.create_booking("A", world.stranger, world.football_off, world.D, T19)
    s.create_booking("B", "9000000012", world.football_off, world.D, T20)
    with pytest.raises(errors.SlotUnavailable):
        s.reschedule_booking(conf.booking_id, world.D, T20)
    # Failed reschedule leaves the original booking intact.
    assert session.get(Booking, conf.booking_id).status == "confirmed"
    assert s.check_availability("Football", world.D, T19) == []


# ---- tenant isolation ----

def test_tenant_isolation(session, world):
    a = BookingService(session, world.client_id)  # noqa: F841 — parity with B
    b = BookingService(session, world.client_b_id)
    assert all(o.offering_id == world.b_football_off for o in b.check_availability("Football", world.D))
    assert b.verify_member(world.rahul).is_member is False
    with pytest.raises(errors.SlotNotFound):  # cannot reach A's offering
        b.create_booking("X", world.stranger, world.football_off, world.D, T19)
