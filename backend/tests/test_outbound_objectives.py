"""Stage 8 — multiple objectives across sectors, all driven by the same abstraction."""
from __future__ import annotations

import datetime as dt

import pytest

from app.db.models import (
    CONTACT_PENDING,
    DISPOSITION_CONFIRMED,
    DISPOSITION_OPT_OUT,
    DISPOSITION_REFUSED,
    OBJECTIVE_BOOKING_CONFIRMATION,
    OBJECTIVE_FEEDBACK,
    OBJECTIVE_LEAD_QUALIFICATION,
    OBJECTIVE_MEMBERSHIP_RENEWAL,
    OBJECTIVE_NO_SHOW_FOLLOWUP,
    OBJECTIVE_PROMO_OFFER,
    OBJECTIVE_REACTIVATION,
    Campaign,
    OutboundContact,
)
from app.voice import outbound_prompts as P
from app.voice.objective import OBJECTIVES, run_scripted

# Every objective except booking confirmation runs on the generic engine (yes -> confirmed).
GENERIC = [
    OBJECTIVE_MEMBERSHIP_RENEWAL,
    OBJECTIVE_REACTIVATION,
    OBJECTIVE_LEAD_QUALIFICATION,
    OBJECTIVE_NO_SHOW_FOLLOWUP,
    OBJECTIVE_PROMO_OFFER,
    OBJECTIVE_FEEDBACK,
]
ALL = [OBJECTIVE_BOOKING_CONFIRMATION, *GENERIC]


def _campaign(session, cid, objective):
    c = Campaign(
        client_id=cid, name=f"{objective} campaign", objective_type=objective,
        window_start=dt.time(0, 0), window_end=dt.time(23, 59), timezone="Asia/Kolkata",
    )
    session.add(c)
    session.flush()
    return c


def _contact(session, cid, camp):
    c = OutboundContact(
        client_id=cid, campaign_id=camp.id, phone="+919876500001",
        consent_basis="existing_customer", state=CONTACT_PENDING,
        context_json={"service": "Haircut", "when": "tomorrow 4 PM"},
    )
    session.add(c)
    session.flush()
    return c


def test_catalogue_has_multiple_sectors():
    assert len(OBJECTIVES) >= 5
    # every objective declares a label + at least one sector
    for key, meta in OBJECTIVES.items():
        assert meta["label"] and meta["sectors"]
    sectors = {s for m in OBJECTIVES.values() for s in m["sectors"]}
    assert {"Gyms", "Salons", "Clinics"} <= sectors


@pytest.mark.parametrize("objective", ALL)
def test_opening_is_english_and_names_business(objective):
    opening = P.build_opening(objective, "Glow Salon", {"service": "facial", "when": "tomorrow"})
    assert opening.startswith("Hi")
    assert "Glow Salon" in opening
    assert "?" in opening
    low = opening.lower()
    assert "automated" not in low and "robot" not in low


@pytest.mark.parametrize("objective", GENERIC)
def test_generic_objective_yes_completes(session, world, objective):
    camp = _campaign(session, world.client_id, objective)
    contact = _contact(session, world.client_id, camp)
    disp, _ = run_scripted(session, contact, camp, ["yes please"])
    assert disp == DISPOSITION_CONFIRMED


@pytest.mark.parametrize("objective", GENERIC)
def test_generic_objective_no_refuses(session, world, objective):
    camp = _campaign(session, world.client_id, objective)
    contact = _contact(session, world.client_id, camp)
    disp, _ = run_scripted(session, contact, camp, ["no thanks"])
    assert disp == DISPOSITION_REFUSED


@pytest.mark.parametrize("objective", ALL)
def test_every_objective_honors_opt_out(session, world, objective):
    camp = _campaign(session, world.client_id, objective)
    contact = _contact(session, world.client_id, camp)
    disp, _ = run_scripted(session, contact, camp, ["please stop calling me"])
    assert disp == DISPOSITION_OPT_OUT
    assert contact.dnc is True
