"""Seed an outbound demo: one campaign + a few contacts, then run ONE simulated call each.

Practice mode only — no real dialing. Gives the dashboard's Outbound section live numbers to show.
Run AFTER `python -m app.seed` (which creates the demo client)::

    python -m app.seed_outbound
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
    DISPOSITION_REFUSED,
    OBJECTIVE_BOOKING_CONFIRMATION,
    Campaign,
    Client,
    OutboundContact,
)
from app.voice import dialer as D  # noqa: E402
from app.voice import metrics  # noqa: E402
from app.voice.telephony import SimulatedProvider  # noqa: E402

# (name, phone, the simulated outcome for that person's one call)
CONTACTS = [
    ("Riya Sharma", "+919876500011", SimulatedProvider(disposition=DISPOSITION_CONFIRMED)),
    ("Neha Mehta", "+919876500012", SimulatedProvider(disposition=DISPOSITION_CONFIRMED)),
    ("Pooja Verma", "+919876500013", SimulatedProvider(answered=False, amd_result=AMD_UNKNOWN, disposition=DISPOSITION_NO_ANSWER, cost_inr=0.4)),
    ("Sneha Iyer", "+919876500014", SimulatedProvider(answered=True, amd_result=AMD_VOICEMAIL, disposition=DISPOSITION_CONFIRMED)),
    ("Aarav Kapoor", "+919876500015", SimulatedProvider(answered=True, amd_result=AMD_HUMAN, disposition=DISPOSITION_REFUSED)),
    ("Diya Nair", "+919876500016", SimulatedProvider(disposition=DISPOSITION_CONFIRMED)),
]


def main() -> None:
    create_all()
    db = SessionLocal()
    try:
        client = db.scalar(select(Client).order_by(Client.id))
        if client is None:
            print("No client found — run `python -m app.seed` first.")
            return

        existing = db.scalar(
            select(Campaign).where(Campaign.client_id == client.id, Campaign.name == "Tomorrow's confirmations")
        )
        if existing:
            print(f"Outbound demo already seeded (campaign id {existing.id}). Nothing to do.")
            return

        camp = Campaign(
            client_id=client.id, name="Tomorrow's confirmations", objective_type=OBJECTIVE_BOOKING_CONFIRMATION,
            status="active", window_start=dt.time(0, 0), window_end=dt.time(23, 59), timezone="Asia/Kolkata",
            max_attempts=3, script_params={"daily_cap": 9}, budget_cap_inr=500,
        )
        db.add(camp)
        db.flush()

        order: list[tuple[int, SimulatedProvider]] = []
        for name, phone, prov in CONTACTS:
            c = OutboundContact(
                client_id=client.id, campaign_id=camp.id, phone=phone, name=name,
                consent_basis="existing_customer", state=CONTACT_PENDING,
                context_json={"service": "Haircut", "when": "tomorrow 4 PM", "booking_phone": phone},
            )
            db.add(c)
            db.flush()
            order.append((c.id, prov))
        db.commit()

        # One simulated call per contact (run_once picks the next pending, in id order).
        for _cid, prov in order:
            D.run_once(db, camp, prov)
        db.commit()

        m = metrics.campaign_metrics(db, camp)
        print(
            f"Seeded campaign {camp.id} '{camp.name}' for {client.business_name}: "
            f"calls={m['calls_made']} answered={m['answered']} booked={m['booked']} "
            f"answer_rate={m['answer_rate_pct']}% spent=Rs{m['spent_inr']}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
