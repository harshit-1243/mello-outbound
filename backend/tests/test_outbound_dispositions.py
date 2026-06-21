"""Stage 6 — disposition handling + retry scheduling, and the dialer wiring it up."""
from __future__ import annotations

import datetime as dt

from app.db.models import (
    CONTACT_DONE,
    CONTACT_EXHAUSTED,
    CONTACT_PENDING,
    DISPOSITION_BUSY,
    DISPOSITION_CONFIRMED,
    DISPOSITION_NO_ANSWER,
    DISPOSITION_REFUSED,
    DISPOSITION_VOICEMAIL,
    OBJECTIVE_BOOKING_CONFIRMATION,
    Campaign,
    OutboundContact,
)
from app.voice import compliance as C
from app.voice import dialer as D
from app.voice import dispositions as DS
from app.voice import outbox
from app.voice.telephony import SimulatedProvider

NOW = dt.datetime(2030, 7, 3, 6, 30)


# ---- plan() ----
def test_terminal_confirmed_fires_confirmation():
    d = DS.plan(DISPOSITION_CONFIRMED, attempt_count=1, max_attempts=3, voicemail_count=0, retry_policy={}, now=NOW)
    assert d.terminal and d.state == CONTACT_DONE and d.next_attempt_at is None and d.fire_confirmation


def test_terminal_refused_no_confirmation():
    d = DS.plan(DISPOSITION_REFUSED, attempt_count=1, max_attempts=3, voicemail_count=0, retry_policy={}, now=NOW)
    assert d.terminal and d.state == CONTACT_DONE and not d.fire_confirmation


def test_no_answer_schedules_backoff():
    d = DS.plan(DISPOSITION_NO_ANSWER, attempt_count=1, max_attempts=3, voicemail_count=0, retry_policy={}, now=NOW)
    assert not d.terminal and d.state == CONTACT_PENDING and d.next_attempt_at == NOW + dt.timedelta(hours=4)


def test_busy_short_backoff_with_override():
    d = DS.plan(DISPOSITION_BUSY, attempt_count=1, max_attempts=3, voicemail_count=0, retry_policy={"busy_minutes": 5}, now=NOW)
    assert d.next_attempt_at == NOW + dt.timedelta(minutes=5)


def test_exhausts_at_max_attempts():
    d = DS.plan(DISPOSITION_NO_ANSWER, attempt_count=3, max_attempts=3, voicemail_count=0, retry_policy={}, now=NOW)
    assert not d.terminal and d.state == CONTACT_EXHAUSTED and d.next_attempt_at is None


def test_voicemail_cap():
    capped = DS.plan(DISPOSITION_VOICEMAIL, attempt_count=1, max_attempts=5, voicemail_count=1, retry_policy={"voicemail_max": 1}, now=NOW)
    assert capped.state == CONTACT_EXHAUSTED
    allowed = DS.plan(DISPOSITION_VOICEMAIL, attempt_count=1, max_attempts=5, voicemail_count=1, retry_policy={"voicemail_max": 2}, now=NOW)
    assert allowed.state == CONTACT_PENDING and allowed.next_attempt_at == NOW + dt.timedelta(hours=4)


# ---- dialer integration ----
def _camp(session, cid, **kw):
    c = Campaign(
        client_id=cid, name="C", objective_type=OBJECTIVE_BOOKING_CONFIRMATION,
        window_start=dt.time(0, 0), window_end=dt.time(23, 59), timezone="Asia/Kolkata",
        max_attempts=kw.get("max_attempts", 3), script_params={"daily_cap": 9}, retry_policy=kw.get("retry_policy", {}),
    )
    session.add(c)
    session.flush()
    return c


def _contact(session, cid, camp):
    c = OutboundContact(client_id=cid, campaign_id=camp.id, phone="+919876500001", consent_basis="existing_customer", state=CONTACT_PENDING)
    session.add(c)
    session.flush()
    return c


def test_dialer_fires_confirmation_on_success(session, world, monkeypatch):
    monkeypatch.setattr(C.settings, "outbound_dlt_registered", True)
    sent = []
    monkeypatch.setattr(outbox, "send_confirmation", lambda s, c, camp, channel="whatsapp": sent.append(c.id) or {"sent": False})
    camp = _camp(session, world.client_id)
    contact = _contact(session, world.client_id, camp)

    D.run_once(session, camp, SimulatedProvider(disposition=DISPOSITION_CONFIRMED), now=NOW)

    assert sent == [contact.id]


def test_dialer_schedules_retry_on_no_answer(session, world, monkeypatch):
    monkeypatch.setattr(C.settings, "outbound_dlt_registered", True)
    camp = _camp(session, world.client_id, retry_policy={"no_answer_hours": 2})
    contact = _contact(session, world.client_id, camp)

    D.run_once(session, camp, SimulatedProvider(answered=False, disposition=DISPOSITION_NO_ANSWER), now=NOW)

    session.refresh(contact)
    assert contact.state == CONTACT_PENDING and contact.next_attempt_at == NOW + dt.timedelta(hours=2)
