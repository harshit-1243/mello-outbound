"""Stage 4 — answering-machine detection: classify, decide, and prove a machine is never conversed with."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select

from app.db.models import (
    AMD_HUMAN,
    AMD_IVR,
    AMD_UNKNOWN,
    AMD_VOICEMAIL,
    CONTACT_PENDING,
    DISPOSITION_CONFIRMED,
    DISPOSITION_FAILED,
    DISPOSITION_VOICEMAIL,
    OBJECTIVE_BOOKING_CONFIRMATION,
    CallAttempt,
    Campaign,
    OutboundContact,
)
from app.voice import amd
from app.voice import compliance as C
from app.voice import dialer as D
from app.voice.telephony import SimulatedProvider

INSIDE = dt.datetime(2030, 7, 3, 6, 30)  # 12:00 IST, inside a 10-19 window


# ---- classification ----
def test_classify_answeredby():
    assert amd.classify_answeredby("human") == AMD_HUMAN
    assert amd.classify_answeredby("machine_end_beep") == AMD_VOICEMAIL
    assert amd.classify_answeredby("machine_start") == AMD_VOICEMAIL
    assert amd.classify_answeredby("fax") == AMD_IVR
    assert amd.classify_answeredby("") == AMD_UNKNOWN
    assert amd.classify_answeredby(None) == AMD_UNKNOWN


# ---- policy ----
def test_decide_human_converses():
    d = amd.decide(AMD_HUMAN)
    assert d.action == amd.ACTION_CONVERSE and d.disposition is None


def test_decide_voicemail_leaves_one_then_hangs_up():
    first = amd.decide(AMD_VOICEMAIL, voicemail_count=0, voicemail_max=1)
    assert first.action == amd.ACTION_LEAVE_VOICEMAIL and first.disposition == DISPOSITION_VOICEMAIL
    again = amd.decide(AMD_VOICEMAIL, voicemail_count=1, voicemail_max=1)
    assert again.action == amd.ACTION_HANG_UP and again.disposition == DISPOSITION_VOICEMAIL


def test_decide_ivr_and_unknown_hang_up():
    assert amd.decide(AMD_IVR).action == amd.ACTION_HANG_UP
    assert amd.decide(AMD_IVR).disposition == DISPOSITION_FAILED
    assert amd.decide(AMD_UNKNOWN).action == amd.ACTION_HANG_UP


# ---- dialer integration ----
def _campaign(session, cid, **kw):
    c = Campaign(
        client_id=cid, name="C", objective_type=OBJECTIVE_BOOKING_CONFIRMATION,
        window_start=dt.time(10, 0), window_end=dt.time(19, 0), timezone="Asia/Kolkata",
        max_attempts=kw.get("max_attempts", 3), script_params=kw.get("script_params", {}),
        retry_policy=kw.get("retry_policy", {}),
    )
    session.add(c)
    session.flush()
    return c


def _contact(session, cid, camp, phone="+919876500001"):
    c = OutboundContact(client_id=cid, campaign_id=camp.id, phone=phone, consent_basis="existing_customer", state=CONTACT_PENDING)
    session.add(c)
    session.flush()
    return c


def test_voicemail_is_never_conversed_with(session, world, monkeypatch):
    """Provider says 'confirmed' but it's a voicemail — the dialer must record voicemail, not confirmed."""
    monkeypatch.setattr(C.settings, "outbound_dlt_registered", True)
    camp = _campaign(session, world.client_id)
    contact = _contact(session, world.client_id, camp)
    # A machine that (deceptively) reports a conversational disposition — must be ignored.
    prov = SimulatedProvider(answered=True, amd_result=AMD_VOICEMAIL, disposition=DISPOSITION_CONFIRMED)

    r = D.run_once(session, camp, prov, now=INSIDE)

    assert r.disposition == DISPOSITION_VOICEMAIL  # NOT confirmed
    att = session.scalar(select(CallAttempt).where(CallAttempt.contact_id == contact.id))
    assert att.amd_result == AMD_VOICEMAIL and att.disposition == DISPOSITION_VOICEMAIL


def test_ivr_hangs_up_as_failed(session, world, monkeypatch):
    monkeypatch.setattr(C.settings, "outbound_dlt_registered", True)
    camp = _campaign(session, world.client_id)
    contact = _contact(session, world.client_id, camp)
    prov = SimulatedProvider(answered=True, amd_result=AMD_IVR, disposition=DISPOSITION_CONFIRMED)

    r = D.run_once(session, camp, prov, now=INSIDE)

    assert r.disposition == DISPOSITION_FAILED


def test_human_still_converses(session, world, monkeypatch):
    monkeypatch.setattr(C.settings, "outbound_dlt_registered", True)
    camp = _campaign(session, world.client_id)
    _contact(session, world.client_id, camp)
    prov = SimulatedProvider(answered=True, amd_result=AMD_HUMAN, disposition=DISPOSITION_CONFIRMED)

    r = D.run_once(session, camp, prov, now=INSIDE)

    assert r.disposition == DISPOSITION_CONFIRMED  # human reaches the (simulated) bot outcome
