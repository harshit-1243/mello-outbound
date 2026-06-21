"""Stage 5 — the goal-driven bot: opening, outbound tools, and full scripted conversations."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from app.booking.service import BookingService
from app.db.models import (
    CONTACT_PENDING,
    DISPOSITION_CALLBACK_REQUESTED,
    DISPOSITION_CONFIRMED,
    DISPOSITION_OPT_OUT,
    DISPOSITION_REFUSED,
    DISPOSITION_RESCHEDULED,
    DISPOSITION_WRONG_NUMBER,
    OBJECTIVE_BOOKING_CONFIRMATION,
    Campaign,
    OptOut,
    OutboundContact,
)
from app.voice import outbound_prompts as P
from app.voice import outbound_tools as T
from app.voice.objective import run_scripted

BOOKING_PHONE = "9876500001"  # stored format in the booking row


def _campaign(session, cid):
    c = Campaign(
        client_id=cid, name="Confirm", objective_type=OBJECTIVE_BOOKING_CONFIRMATION,
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


def _make_booking(session, world, d=dt.date(2030, 7, 3), t=dt.time(18, 0)):
    svc = BookingService(session, world.client_id)
    return svc.create_booking(name="Cust", phone=BOOKING_PHONE, offering_id=world.badminton_off, date=d, time=t, source="voice")


# ---- opening ----
def test_opening_identifies_business_and_does_not_announce_ai():
    opening = P.build_opening(OBJECTIVE_BOOKING_CONFIRMATION, "Glow Salon", {"service": "Haircut", "when": "tomorrow"})
    assert "Glow Salon" in opening
    assert opening.startswith("Hi")  # English-first opening
    assert "?" in opening  # asks a yes/no consent question
    low = opening.lower()
    assert "automated" not in low and "robot" not in low and " ai " not in low  # no upfront AI disclosure


# ---- tools ----
def test_confirm_tool(session, world):
    camp = _campaign(session, world.client_id)
    contact = _contact(session, world.client_id, camp)
    r = T.confirm_booking(session, contact, camp)
    assert r.ok and r.end_call and r.disposition == DISPOSITION_CONFIRMED


def test_opt_out_tool_persists_dnc(session, world):
    camp = _campaign(session, world.client_id)
    contact = _contact(session, world.client_id, camp)
    r = T.opt_out(session, contact, camp)
    session.flush()
    assert r.disposition == DISPOSITION_OPT_OUT and r.end_call
    assert contact.dnc is True
    row = session.scalar(select(OptOut).where(OptOut.client_id == world.client_id, OptOut.phone == "+919876500001"))
    assert row is not None


def test_cancel_tool_cancels_booking(session, world):
    _make_booking(session, world)
    camp = _campaign(session, world.client_id)
    ctx = {"service": "Badminton", "when": "kal", "booking_phone": BOOKING_PHONE, "booking_date": "2030-07-03", "booking_time": "18:00"}
    contact = _contact(session, world.client_id, camp, ctx=ctx)

    r = T.cancel_booking(session, contact, camp)
    session.flush()
    assert r.disposition == DISPOSITION_REFUSED and r.end_call
    svc = BookingService(session, world.client_id)
    assert svc.find_bookings_for_phone(BOOKING_PHONE) == []  # booking gone


def test_reschedule_tool_moves_booking(session, world):
    _make_booking(session, world, d=dt.date(2030, 7, 3), t=dt.time(18, 0))
    camp = _campaign(session, world.client_id)
    ctx = {"service": "Badminton", "when": "kal", "booking_phone": BOOKING_PHONE, "booking_date": "2030-07-03", "booking_time": "18:00"}
    contact = _contact(session, world.client_id, camp, ctx=ctx)

    r = T.reschedule_booking(session, contact, camp, new_date="2030-07-04", new_time="19:00")
    session.flush()
    assert r.ok and r.disposition == DISPOSITION_RESCHEDULED


# ---- full scripted conversations ----
def test_conv_confirm(session, world):
    camp = _campaign(session, world.client_id)
    contact = _contact(session, world.client_id, camp)
    disp, _ = run_scripted(session, contact, camp, ["haan theek hai"])
    assert disp == DISPOSITION_CONFIRMED


def test_conv_opt_out(session, world):
    camp = _campaign(session, world.client_id)
    contact = _contact(session, world.client_id, camp)
    disp, _ = run_scripted(session, contact, camp, ["please stop calling me"])
    assert disp == DISPOSITION_OPT_OUT
    assert contact.dnc is True
    assert session.scalar(select(OptOut).where(OptOut.client_id == world.client_id)) is not None


def test_conv_busy_requests_callback(session, world):
    camp = _campaign(session, world.client_id)
    contact = _contact(session, world.client_id, camp)
    disp, _ = run_scripted(session, contact, camp, ["main abhi busy hoon"])
    assert disp == DISPOSITION_CALLBACK_REQUESTED


def test_conv_robot_question_then_confirm(session, world):
    camp = _campaign(session, world.client_id)
    contact = _contact(session, world.client_id, camp)
    disp, transcript = run_scripted(session, contact, camp, ["are you a robot?", "haan confirm"])
    assert disp == DISPOSITION_CONFIRMED
    assert any("automated" in msg.lower() for role, msg in transcript)  # disclosed honestly when asked


def test_conv_wrong_number(session, world):
    camp = _campaign(session, world.client_id)
    contact = _contact(session, world.client_id, camp)
    disp, _ = run_scripted(session, contact, camp, ["sorry wrong number"])
    assert disp == DISPOSITION_WRONG_NUMBER


def test_conv_reschedule_unparseable_falls_back_to_callback(session, world):
    camp = _campaign(session, world.client_id)
    contact = _contact(session, world.client_id, camp)
    disp, _ = run_scripted(session, contact, camp, ["mujhe reschedule karna hai", "pata nahi", "pata nahi"])
    assert disp == DISPOSITION_CALLBACK_REQUESTED
