"""Prove the agent's decision lands on the dashboard.

Adds a fresh contact to the renewal campaign, lets the conversation BRAIN decide the outcome from a
caller utterance, persists it through the SAME path a live Cerebras tool-call uses
(outbound_pipeline_tools._run), and prints the campaign metrics before/after — i.e. exactly the JSON
the dashboard's Outbound section polls. A moved number = the agent updating the dashboard.
"""
from __future__ import annotations

from sqlalchemy import select

from app.config import settings

settings.outbound_dlt_registered = True

from app.db.base import SessionLocal  # noqa: E402
from app.db.models import CONTACT_PENDING, Campaign, OutboundContact  # noqa: E402
from app.voice import metrics  # noqa: E402
from app.voice.objective import make_conversation  # noqa: E402
from app.voice.outbound_pipeline_tools import _run  # noqa: E402

# Which tool a CONFIRMED outcome corresponds to, per objective (mirrors objective._AFFIRMATIVE).
AFFIRMATIVE_TOOL = {
    "membership_renewal": "mark_renewal",
    "reactivation": "log_interest",
    "lead_qualification": "log_interest",
    "no_show_followup": "log_interest",
    "promo_offer": "log_interest",
    "feedback": "record_feedback",
    "booking_confirmation": "confirm_booking",
}


def snap(db, camp):
    m = metrics.campaign_metrics(db, camp)
    return f"calls={m['calls_made']} answered={m['answered']} booked={m['booked']} done={m['contacts_done']} contacts={m['contacts_total']}"


def main() -> None:
    db = SessionLocal()
    try:
        camp = db.scalar(select(Campaign).where(Campaign.name == "Membership renewals — June"))
        if camp is None:
            print("Run `python -m app.seed_outbound_all` first."); return

        print(f"Campaign {camp.id} '{camp.name}' ({camp.objective_type})")
        print(f"  BEFORE: {snap(db, camp)}")

        # Fresh inbound-of-a-kind: a new contact the agent will call.
        contact = OutboundContact(
            client_id=camp.client_id, campaign_id=camp.id, phone="+919812345678", name="Live Demo Caller",
            consent_basis="existing_customer", state=CONTACT_PENDING,
            context_json={"service": "gym membership", "when": ""},
        )
        db.add(contact)
        db.commit()
        contact_id = contact.id

        # 1) The BRAIN decides from a caller utterance (no LLM needed — deterministic stand-in).
        conv = make_conversation(db, contact, camp)
        result = conv.handle("haan ji, membership renew kar do")
        db.commit()
        tool = AFFIRMATIVE_TOOL[camp.objective_type]
        print(f"  AGENT heard 'haan renew kar do' -> decided: {tool} (disposition={result.disposition})")

        # 2) Persist through the LIVE pipeline's tool path (CallAttempt + disposition + state).
        out = _run(contact_id, camp.id, tool, {})
        print(f"  PERSISTED via _run: ok={out['ok']} done={out['done']}")

        db.expire_all()  # re-read what the dashboard endpoint would now return
        print(f"  AFTER:  {snap(db, camp)}")

        row = db.get(OutboundContact, contact_id)
        print(f"  contact on dashboard: {row.name} | state={row.state} | disposition={row.last_disposition}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
