"""Stage 3 — the progressive dialer in practice mode (SimulatedProvider, no real calls)."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select

from app.db.models import (
    CONTACT_DONE,
    CONTACT_EXHAUSTED,
    CONTACT_PENDING,
    CONTACT_SKIPPED,
    DISPOSITION_NO_ANSWER,
    OBJECTIVE_BOOKING_CONFIRMATION,
    AMD_UNKNOWN,
    CallAttempt,
    Campaign,
    OptOut,
    OutboundContact,
)
from app.voice import compliance as C
from app.voice import dialer as D
from app.voice.phone import normalize_phone
from app.voice.telephony import SimulatedProvider

# UTC instants chosen so the Asia/Kolkata local clock lands inside / outside a 10:00-19:00 window.
INSIDE = dt.datetime(2030, 7, 3, 6, 30)   # 12:00 IST
OUTSIDE = dt.datetime(2030, 7, 3, 16, 30)  # 22:00 IST


def _campaign(session, cid, **kw):
    c = Campaign(
        client_id=cid, name="C", objective_type=OBJECTIVE_BOOKING_CONFIRMATION,
        window_start=dt.time(10, 0), window_end=dt.time(19, 0), timezone="Asia/Kolkata",
        max_attempts=kw.get("max_attempts", 3), script_params=kw.get("script_params", {}),
        budget_cap_inr=kw.get("budget_cap_inr", 0), spent_inr=kw.get("spent_inr", 0),
    )
    session.add(c)
    session.flush()
    return c


def _contact(session, cid, camp, phone="+919876500001", consent="existing_customer"):
    c = OutboundContact(
        client_id=cid, campaign_id=camp.id, phone=phone, consent_basis=consent, state=CONTACT_PENDING,
    )
    session.add(c)
    session.flush()
    return c


def _attempts(session, contact_id):
    return session.scalar(select(func.count()).select_from(CallAttempt).where(CallAttempt.contact_id == contact_id)) or 0


def test_dials_eligible_contact(session, world, monkeypatch):
    monkeypatch.setattr(C.settings, "outbound_dlt_registered", True)
    camp = _campaign(session, world.client_id)
    contact = _contact(session, world.client_id, camp)

    r = D.run_once(session, camp, SimulatedProvider(), now=INSIDE)

    assert r.status == "dialed" and r.disposition == "confirmed"
    session.refresh(contact)
    assert contact.state == CONTACT_DONE
    assert contact.attempt_count == 1
    assert _attempts(session, contact.id) == 1
    assert float(camp.spent_inr) == 1.5


def test_skips_opted_out_contact(session, world, monkeypatch):
    monkeypatch.setattr(C.settings, "outbound_dlt_registered", True)
    camp = _campaign(session, world.client_id)
    contact = _contact(session, world.client_id, camp)
    session.add(OptOut(client_id=world.client_id, phone=normalize_phone("9876500001")))  # different format
    session.flush()

    r = D.run_once(session, camp, SimulatedProvider(), now=INSIDE)

    assert r.status == "skipped" and r.reason == C.REASON_OPTED_OUT
    session.refresh(contact)
    assert contact.state == CONTACT_SKIPPED
    assert _attempts(session, contact.id) == 0  # never dialed


def test_blocked_outside_window(session, world, monkeypatch):
    monkeypatch.setattr(C.settings, "outbound_dlt_registered", True)
    camp = _campaign(session, world.client_id)
    contact = _contact(session, world.client_id, camp)

    r = D.run_once(session, camp, SimulatedProvider(), now=OUTSIDE)

    assert r.status == "blocked" and r.reason == C.REASON_OUTSIDE_WINDOW
    session.refresh(contact)
    assert contact.state == CONTACT_PENDING  # left to try later
    assert _attempts(session, contact.id) == 0


def test_budget_cap_stops_dialing(session, world, monkeypatch):
    monkeypatch.setattr(C.settings, "outbound_dlt_registered", True)
    camp = _campaign(session, world.client_id, budget_cap_inr=1, spent_inr=1)
    contact = _contact(session, world.client_id, camp)

    r = D.run_once(session, camp, SimulatedProvider(), now=INSIDE)

    assert r.status == "budget_exhausted"
    assert _attempts(session, contact.id) == 0


def test_no_answer_retries_then_exhausts(session, world, monkeypatch):
    monkeypatch.setattr(C.settings, "outbound_dlt_registered", True)
    camp = _campaign(session, world.client_id, max_attempts=2, script_params={"daily_cap": 5})
    contact = _contact(session, world.client_id, camp)
    prov = SimulatedProvider(answered=False, amd_result=AMD_UNKNOWN, disposition=DISPOSITION_NO_ANSWER, cost_inr=0.5)
    # Stage 6: a no-answer schedules a backoff, so the 2nd attempt is only due later.
    later = INSIDE + dt.timedelta(hours=5)  # past the default 4h no-answer backoff, still inside window

    r1 = D.run_once(session, camp, prov, now=INSIDE)
    r2 = D.run_once(session, camp, prov, now=later)
    r3 = D.run_once(session, camp, prov, now=later)

    assert r1.status == "dialed" and r2.status == "dialed"
    assert r3.status == "no_eligible"
    session.refresh(contact)
    assert contact.state == CONTACT_EXHAUSTED
    assert contact.attempt_count == 2
    assert _attempts(session, contact.id) == 2


def test_progressive_dials_distinct_contacts(session, world, monkeypatch):
    monkeypatch.setattr(C.settings, "outbound_dlt_registered", True)
    camp = _campaign(session, world.client_id)
    c1 = _contact(session, world.client_id, camp, phone="+919876500001")
    c2 = _contact(session, world.client_id, camp, phone="+919876500002")

    r1 = D.run_once(session, camp, SimulatedProvider(), now=INSIDE)
    r2 = D.run_once(session, camp, SimulatedProvider(), now=INSIDE)

    assert {r1.contact_id, r2.contact_id} == {c1.id, c2.id}  # two different people, no double-dial
    assert r1.status == r2.status == "dialed"
