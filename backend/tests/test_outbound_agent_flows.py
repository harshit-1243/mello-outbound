"""Outbound agent — conversation edge & robustness cases (TEST_PLAN section 7).

These exercise the goal-driven practice-mode brain on the paths the existing suite didn't assert:
the scripted reschedule happy path, the slot-unavailable reprompt, silence / garbled-input
exhaustion, intent-priority precedence, and Devanagari intent matching. Zero API calls.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from app.booking.service import BookingService
from app.db.models import (
    CONTACT_PENDING,
    DISPOSITION_CALLBACK_REQUESTED,
    DISPOSITION_OPT_OUT,
    DISPOSITION_REFUSED,
    DISPOSITION_RESCHEDULED,
    DISPOSITION_WRONG_NUMBER,
    OBJECTIVE_BOOKING_CONFIRMATION,
    OBJECTIVE_PROMO_OFFER,
    Campaign,
    OptOut,
    OutboundContact,
)
from app.voice import outbound_tools as T
from app.voice.conversation import GenericObjectiveConversation
from app.voice.objective import run_scripted

BOOKING_PHONE = "9876500001"  # stored (bare) format on the booking row


def _campaign(session, cid, objective=OBJECTIVE_BOOKING_CONFIRMATION):
    c = Campaign(
        client_id=cid, name="Confirm", objective_type=objective,
        window_start=dt.time(0, 0), window_end=dt.time(23, 59), timezone="Asia/Kolkata",
    )
    session.add(c)
    session.flush()
    return c


def _contact(session, cid, camp, ctx=None, phone="+919876500001"):
    c = OutboundContact(
        client_id=cid, campaign_id=camp.id, phone=phone, consent_basis="existing_customer",
        state=CONTACT_PENDING, context_json=ctx or {"service": "Badminton", "when": "kal shaam"},
    )
    session.add(c)
    session.flush()
    return c


def _make_booking(session, world, phone=BOOKING_PHONE, d=dt.date(2030, 7, 3), t=dt.time(18, 0)):
    svc = BookingService(session, world.client_id)
    return svc.create_booking(name="Cust", phone=phone, offering_id=world.badminton_off, date=d, time=t, source="voice")


def _booking_ctx(d="2030-07-03", t="18:00"):
    return {"service": "Badminton", "when": "kal", "booking_phone": BOOKING_PHONE,
            "booking_date": d, "booking_time": t}


# 7.1 — scripted reschedule with a parseable date+time → RESCHEDULED + booking moved
def test_scripted_reschedule_moves_booking(session, world):
    _make_booking(session, world)
    camp = _campaign(session, world.client_id)
    contact = _contact(session, world.client_id, camp, ctx=_booking_ctx())

    disp, transcript = run_scripted(session, contact, camp, ["reschedule karna hai", "2030-07-04 19:00"])
    assert disp == DISPOSITION_RESCHEDULED
    svc = BookingService(session, world.client_id)
    moved = svc.find_bookings_for_phone(BOOKING_PHONE)
    assert any(b.slot_date == dt.date(2030, 7, 4) and b.start_time == dt.time(19, 0) for b in moved)


# 7.2 — reschedule onto an already-occupied slot → tool returns not-ok with a reprompt
def test_reschedule_onto_occupied_slot_reprompts(session, world):
    _make_booking(session, world, phone=BOOKING_PHONE, d=dt.date(2030, 7, 3), t=dt.time(18, 0))
    # Occupy the target slot (single-capacity badminton court) with a different customer.
    _make_booking(session, world, phone="9000000123", d=dt.date(2030, 7, 4), t=dt.time(19, 0))
    camp = _campaign(session, world.client_id)
    contact = _contact(session, world.client_id, camp, ctx=_booking_ctx())

    r = T.reschedule_booking(session, contact, camp, new_date="2030-07-04", new_time="19:00")
    assert r.ok is False and not r.end_call
    assert "available" in r.message.lower()


# 7.3 — explicit "no" in booking confirmation cancels the booking → REFUSED
def test_no_cancels_booking(session, world):
    _make_booking(session, world)
    camp = _campaign(session, world.client_id)
    contact = _contact(session, world.client_id, camp, ctx=_booking_ctx())

    disp, _ = run_scripted(session, contact, camp, ["nahi, cancel kar do"])
    assert disp == DISPOSITION_REFUSED
    assert BookingService(session, world.client_id).find_bookings_for_phone(BOOKING_PHONE) == []


# 7.4 — two silent turns → callback
def test_two_silent_turns_request_callback(session, world):
    camp = _campaign(session, world.client_id)
    contact = _contact(session, world.client_id, camp)
    disp, _ = run_scripted(session, contact, camp, ["", ""])
    assert disp == DISPOSITION_CALLBACK_REQUESTED


# 7.5 — three unintelligible turns → callback
def test_three_garbled_turns_request_callback(session, world):
    camp = _campaign(session, world.client_id)
    contact = _contact(session, world.client_id, camp)
    disp, _ = run_scripted(session, contact, camp, ["mmhmm grrbl", "zxqw", "ffft"])
    assert disp == DISPOSITION_CALLBACK_REQUESTED


# 7.6 — Devanagari opt-out is honored immediately
def test_devanagari_opt_out(session, world):
    camp = _campaign(session, world.client_id)
    contact = _contact(session, world.client_id, camp)
    disp, _ = run_scripted(session, contact, camp, ["कृपया बंद करो"])
    assert disp == DISPOSITION_OPT_OUT
    assert contact.dnc is True
    assert session.scalar(select(OptOut).where(OptOut.client_id == world.client_id)) is not None


# 7.7 — Devanagari wrong-number
def test_devanagari_wrong_number(session, world):
    camp = _campaign(session, world.client_id)
    contact = _contact(session, world.client_id, camp)
    disp, _ = run_scripted(session, contact, camp, ["यह गलत नंबर है"])
    assert disp == DISPOSITION_WRONG_NUMBER


# 7.8 — intent priority: opt-out is checked before wrong-number, so it wins on a mixed utterance
def test_optout_beats_wrong_number_on_mixed_intent(session, world):
    camp = _campaign(session, world.client_id)
    contact = _contact(session, world.client_id, camp)
    disp, _ = run_scripted(session, contact, camp, ["stop calling, this is the wrong number"])
    assert disp == DISPOSITION_OPT_OUT


# 7.9 — generic objective discloses honestly when asked "are you AI?" and keeps the call open
def test_generic_objective_discloses_ai_and_continues(session, world):
    camp = _campaign(session, world.client_id, objective=OBJECTIVE_PROMO_OFFER)
    contact = _contact(session, world.client_id, camp, ctx={"service": "facial", "when": "today"})
    conv = GenericObjectiveConversation(
        session, contact, camp, "Glow Salon", OBJECTIVE_PROMO_OFFER, T.log_interest
    )
    turn = conv.handle("wait, are you a bot?")
    assert "automated" in turn.message.lower()
    assert turn.end_call is False
