"""Stage 2 — proof the compliance gate refuses to dial when it must.

Pure-function tests cover every block reason deterministically; one DB test proves the opt-out
match survives phone-format differences (the Stage-0 normalization fix the gate depends on).
"""
from __future__ import annotations

import datetime as dt

from app.db.models import (
    CONTACT_DONE,
    CONTACT_PENDING,
    OBJECTIVE_BOOKING_CONFIRMATION,
    Campaign,
    OptOut,
    OutboundContact,
)
from app.voice import compliance as C
from app.voice.phone import normalize_phone, same_number

WS, WE = dt.time(10, 0), dt.time(19, 0)


def _facts(**over):
    base = dict(
        now_local=dt.datetime(2030, 7, 3, 12, 0),  # noon — inside window
        window_start=WS,
        window_end=WE,
        contact_state=CONTACT_PENDING,
        dlt_registered=True,
        opted_out=False,
        consent_basis="existing_customer",
        attempt_count=0,
        max_attempts=3,
        attempts_today=0,
        daily_cap=1,
    )
    base.update(over)
    return base


def test_happy_path_is_eligible():
    assert C.evaluate(**_facts()).eligible


def test_blocks_outside_window():
    r = C.evaluate(**_facts(now_local=dt.datetime(2030, 7, 3, 21, 0)))  # 9pm
    assert not r.eligible and r.reason == C.REASON_OUTSIDE_WINDOW


def test_blocks_before_window_opens():
    r = C.evaluate(**_facts(now_local=dt.datetime(2030, 7, 3, 8, 0)))  # 8am
    assert not r.eligible and r.reason == C.REASON_OUTSIDE_WINDOW


def test_blocks_opted_out():
    r = C.evaluate(**_facts(opted_out=True))
    assert not r.eligible and r.reason == C.REASON_OPTED_OUT


def test_blocks_no_consent():
    r = C.evaluate(**_facts(consent_basis=None))
    assert not r.eligible and r.reason == C.REASON_NO_CONSENT


def test_blocks_max_attempts():
    r = C.evaluate(**_facts(attempt_count=3, max_attempts=3))
    assert not r.eligible and r.reason == C.REASON_MAX_ATTEMPTS


def test_blocks_daily_cap():
    r = C.evaluate(**_facts(attempts_today=1, daily_cap=1))
    assert not r.eligible and r.reason == C.REASON_DAILY_CAP


def test_blocks_dlt_unregistered():
    r = C.evaluate(**_facts(dlt_registered=False))
    assert not r.eligible and r.reason == C.REASON_DLT_UNREGISTERED


def test_blocks_when_not_pending():
    r = C.evaluate(**_facts(contact_state=CONTACT_DONE))
    assert not r.eligible and r.reason == C.REASON_NOT_PENDING


def test_phone_normalization_variants():
    assert normalize_phone("9876500001") == "+919876500001"
    assert normalize_phone("+919876500001") == "+919876500001"
    assert normalize_phone("09876500001") == "+919876500001"
    assert normalize_phone("+91 98765 00001") == "+919876500001"
    assert normalize_phone("notaphone") is None
    assert same_number("9876500001", "+919876500001")


def test_db_optout_blocks_across_phone_formats(session, world, monkeypatch):
    """Opt-out stored in one format must block a contact stored in another (the real bug)."""
    monkeypatch.setattr(C.settings, "outbound_dlt_registered", True)
    cid = world.client_id

    camp = Campaign(
        client_id=cid, name="Confirm tomorrow", objective_type=OBJECTIVE_BOOKING_CONFIRMATION,
        window_start=dt.time(0, 0), window_end=dt.time(23, 59), max_attempts=3, timezone="Asia/Kolkata",
    )
    session.add(camp)
    session.flush()

    contact = OutboundContact(
        client_id=cid, campaign_id=camp.id, phone="+919876500001",
        consent_basis="existing_customer", state=CONTACT_PENDING,
    )
    session.add(contact)
    session.flush()

    # Eligible before any opt-out.
    assert C.is_dial_eligible(session, contact).eligible

    # Person opts out; we store it from a bare 10-digit number (different format than the contact).
    session.add(OptOut(client_id=cid, phone=normalize_phone("9876500001")))
    session.flush()

    r = C.is_dial_eligible(session, contact)
    assert not r.eligible and r.reason == C.REASON_OPTED_OUT
