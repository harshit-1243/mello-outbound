"""Seed ONE outbound campaign per objective, each with contacts + simulated calls.

Gives the dashboard's Outbound section a live campaign for every call type (renewal, reactivation,
lead-qual, no-show, promo, feedback) — not just booking confirmation. Practice mode only (simulated
telephony; no real dials). Idempotent: skips a campaign whose name already exists.

Run AFTER `python -m app.seed`::

    python -m app.seed_outbound_all
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from app.config import settings

settings.outbound_dlt_registered = True  # practice mode: let the simulated dialer run

from app.db.base import SessionLocal  # noqa: E402
from app.db.init_db import create_all  # noqa: E402
from app.db.models import (  # noqa: E402
    AMD_HUMAN,
    AMD_UNKNOWN,
    AMD_VOICEMAIL,
    CONTACT_PENDING,
    DISPOSITION_CONFIRMED,
    DISPOSITION_NO_ANSWER,
    DISPOSITION_OPT_OUT,
    DISPOSITION_REFUSED,
    OBJECTIVE_FEEDBACK,
    OBJECTIVE_LEAD_QUALIFICATION,
    OBJECTIVE_MEMBERSHIP_RENEWAL,
    OBJECTIVE_NO_SHOW_FOLLOWUP,
    OBJECTIVE_PROMO_OFFER,
    OBJECTIVE_REACTIVATION,
    Campaign,
    Client,
    OutboundContact,
)
from app.voice import dialer as D  # noqa: E402
from app.voice import metrics  # noqa: E402
from app.voice.telephony import SimulatedProvider  # noqa: E402


def _prov(**kw):
    return SimulatedProvider(**kw)


# A realistic disposition mix per contact (name, phone, simulated outcome).
def _mix(prefix: str, base: int):
    return [
        (f"{prefix} One", f"+9198765{base:05d}", _prov(disposition=DISPOSITION_CONFIRMED)),
        (f"{prefix} Two", f"+9198765{base + 1:05d}", _prov(disposition=DISPOSITION_CONFIRMED)),
        (f"{prefix} Three", f"+9198765{base + 2:05d}", _prov(answered=False, amd_result=AMD_UNKNOWN, disposition=DISPOSITION_NO_ANSWER, cost_inr=0.4)),
        (f"{prefix} Four", f"+9198765{base + 3:05d}", _prov(answered=True, amd_result=AMD_HUMAN, disposition=DISPOSITION_REFUSED)),
        (f"{prefix} Five", f"+9198765{base + 4:05d}", _prov(answered=True, amd_result=AMD_VOICEMAIL, disposition=DISPOSITION_CONFIRMED)),
    ]


# (objective, campaign name, context, contacts)
CAMPAIGNS = [
    (OBJECTIVE_MEMBERSHIP_RENEWAL, "Membership renewals — June", {"service": "gym membership", "when": ""}, _mix("Renew", 20)),
    (OBJECTIVE_REACTIVATION, "Win-back lapsed clients", {"service": "haircut", "when": ""}, _mix("Winback", 30)),
    (OBJECTIVE_LEAD_QUALIFICATION, "New lead qualification", {"service": "personal training", "when": ""}, _mix("Lead", 40)),
    (OBJECTIVE_NO_SHOW_FOLLOWUP, "No-show rebooking", {"service": "appointment", "when": "yesterday"}, _mix("NoShow", 50)),
    (OBJECTIVE_PROMO_OFFER, "Monsoon promo offer", {"service": "spa package", "when": ""}, _mix("Promo", 60)),
    (OBJECTIVE_FEEDBACK, "Post-visit feedback", {"service": "salon visit", "when": ""}, _mix("Feedback", 70)),
]


def main() -> None:
    create_all()
    db = SessionLocal()
    try:
        client = db.scalar(select(Client).order_by(Client.id))
        if client is None:
            print("No client found — run `python -m app.seed` first.")
            return

        for objective, name, ctx, contacts in CAMPAIGNS:
            if db.scalar(select(Campaign).where(Campaign.client_id == client.id, Campaign.name == name)):
                print(f"  skip (exists): {name}")
                continue

            camp = Campaign(
                client_id=client.id, name=name, objective_type=objective, status="active",
                window_start=dt.time(0, 0), window_end=dt.time(23, 59), timezone="Asia/Kolkata",
                max_attempts=3, script_params={"daily_cap": 9}, budget_cap_inr=500,
            )
            db.add(camp)
            db.flush()

            order = []
            for cname, phone, prov in contacts:
                c = OutboundContact(
                    client_id=client.id, campaign_id=camp.id, phone=phone, name=cname,
                    consent_basis="existing_customer", state=CONTACT_PENDING,
                    context_json={**ctx, "booking_phone": phone},
                )
                db.add(c)
                db.flush()
                order.append((c.id, prov))
            db.commit()

            for _cid, prov in order:
                D.run_once(db, camp, prov)
            db.commit()

            m = metrics.campaign_metrics(db, camp)
            print(f"  seeded {camp.id:>2} {name:<30} calls={m['calls_made']} booked={m['booked']} answer={m['answer_rate_pct']}%")
    finally:
        db.close()


if __name__ == "__main__":
    main()
