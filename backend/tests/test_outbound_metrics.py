"""Stage 7 — campaign metrics computed from real attempts/contacts."""
from __future__ import annotations

import datetime as dt

from app.db.models import (
    AMD_UNKNOWN,
    AMD_VOICEMAIL,
    CONTACT_PENDING,
    DISPOSITION_CONFIRMED,
    DISPOSITION_NO_ANSWER,
    OBJECTIVE_BOOKING_CONFIRMATION,
    Campaign,
    OutboundContact,
)
from app.voice import compliance as C
from app.voice import dialer as D
from app.voice import metrics
from app.voice.telephony import SimulatedProvider

NOW = dt.datetime(2030, 7, 3, 6, 30)


def _build(session, cid):
    camp = Campaign(
        client_id=cid, name="Confirm Aug", objective_type=OBJECTIVE_BOOKING_CONFIRMATION,
        window_start=dt.time(0, 0), window_end=dt.time(23, 59), timezone="Asia/Kolkata",
        max_attempts=3, script_params={"daily_cap": 9},
    )
    session.add(camp)
    session.flush()
    for ph in ("+919876500001", "+919876500002", "+919876500003"):
        session.add(OutboundContact(client_id=cid, campaign_id=camp.id, phone=ph, consent_basis="existing_customer", state=CONTACT_PENDING))
    session.flush()
    return camp


def test_campaign_metrics(session, world, monkeypatch):
    monkeypatch.setattr(C.settings, "outbound_dlt_registered", True)
    camp = _build(session, world.client_id)

    D.run_once(session, camp, SimulatedProvider(disposition=DISPOSITION_CONFIRMED), now=NOW)  # confirmed (human)
    D.run_once(session, camp, SimulatedProvider(answered=False, amd_result=AMD_UNKNOWN, disposition=DISPOSITION_NO_ANSWER), now=NOW)  # no answer
    D.run_once(session, camp, SimulatedProvider(answered=True, amd_result=AMD_VOICEMAIL, disposition=DISPOSITION_CONFIRMED), now=NOW)  # voicemail

    m = metrics.campaign_metrics(session, camp)
    assert m["calls_made"] == 3
    assert m["answered"] == 2                       # human + voicemail answered; no-answer did not
    assert m["amd_human"] == 1 and m["amd_voicemail"] == 1 and m["amd_unknown"] == 0
    assert m["booked"] == 1 and m["goal_completed"] == 1
    assert m["qualified"] == 1                       # one human reached
    assert m["opt_outs"] == 0
    assert m["avg_handle_seconds"] == 35
    assert m["total_cost_inr"] == 4.5
    assert m["cost_per_success_inr"] == 4.5
    assert m["contacts_total"] == 3


def test_list_and_contacts(session, world, monkeypatch):
    monkeypatch.setattr(C.settings, "outbound_dlt_registered", True)
    camp = _build(session, world.client_id)
    D.run_once(session, camp, SimulatedProvider(disposition=DISPOSITION_CONFIRMED), now=NOW)

    summary = metrics.list_campaigns(session, world.client_id)
    assert any(s["id"] == camp.id and s["booked"] == 1 and s["calls_made"] == 1 for s in summary)

    rows = metrics.campaign_contacts(session, camp.id)
    assert len(rows) == 3
    assert {r["phone"] for r in rows} == {"+919876500001", "+919876500002", "+919876500003"}
