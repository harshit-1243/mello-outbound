"""Objective registry — the menu of outbound objectives across client sectors.

Each objective maps to an opening (outbound_prompts), a set of tools, and a conversation engine.
Booking confirmation has its own engine (it can reschedule/cancel a real booking); the rest share
``GenericObjectiveConversation`` with an objective-specific affirmative tool. Adding a new objective
is: a constant (models), an opening + tools-note (outbound_prompts), and one row here.
``run_scripted`` plays caller turns through the practice-mode brain for tests / simulation.
"""
from __future__ import annotations

from app.db.models import (
    OBJECTIVE_BOOKING_CONFIRMATION,
    OBJECTIVE_FEEDBACK,
    OBJECTIVE_LEAD_QUALIFICATION,
    OBJECTIVE_MEMBERSHIP_RENEWAL,
    OBJECTIVE_NO_SHOW_FOLLOWUP,
    OBJECTIVE_PROMO_OFFER,
    OBJECTIVE_REACTIVATION,
    Client,
)
from app.voice import outbound_tools as T
from app.voice.conversation import BookingConfirmationConversation, GenericObjectiveConversation

# Catalogue shown in the dashboard's campaign builder — label + the client sectors each suits.
OBJECTIVES: dict[str, dict] = {
    OBJECTIVE_BOOKING_CONFIRMATION: {"label": "Booking confirmation", "sectors": ["Salons", "Clinics", "Sports", "Spas", "Coaching"]},
    OBJECTIVE_MEMBERSHIP_RENEWAL: {"label": "Membership renewal", "sectors": ["Gyms", "Sports clubs", "Salons"]},
    OBJECTIVE_REACTIVATION: {"label": "Win-back / reactivation", "sectors": ["Salons", "Gyms", "Clinics", "Spas"]},
    OBJECTIVE_LEAD_QUALIFICATION: {"label": "Lead qualification", "sectors": ["Any (opted-in leads)"]},
    OBJECTIVE_NO_SHOW_FOLLOWUP: {"label": "No-show follow-up", "sectors": ["Clinics", "Salons", "Coaching"]},
    OBJECTIVE_PROMO_OFFER: {"label": "Promo / offer", "sectors": ["Salons", "Gyms", "Retail", "Spas"]},
    OBJECTIVE_FEEDBACK: {"label": "Post-visit feedback", "sectors": ["Any"]},
}

# The tool a "yes" triggers, for each generic (non-booking) objective.
_AFFIRMATIVE = {
    OBJECTIVE_MEMBERSHIP_RENEWAL: T.mark_renewal,
    OBJECTIVE_REACTIVATION: T.log_interest,
    OBJECTIVE_LEAD_QUALIFICATION: T.log_interest,
    OBJECTIVE_NO_SHOW_FOLLOWUP: T.log_interest,
    OBJECTIVE_PROMO_OFFER: T.log_interest,
    OBJECTIVE_FEEDBACK: T.record_feedback,
}


def make_conversation(session, contact, campaign):
    client = session.get(Client, contact.client_id)
    business = client.business_name if client else "Mello"
    ot = campaign.objective_type
    if ot == OBJECTIVE_BOOKING_CONFIRMATION:
        return BookingConfirmationConversation(session, contact, campaign, business)
    affirmative = _AFFIRMATIVE.get(ot)
    if affirmative is None:
        raise ValueError(f"No outbound conversation registered for objective {ot!r}")
    return GenericObjectiveConversation(session, contact, campaign, business, ot, affirmative)


def run_scripted(session, contact, campaign, utterances: list[str]):
    """Drive the conversation with scripted caller turns. Returns (disposition, transcript)."""
    conv = make_conversation(session, contact, campaign)
    transcript = [("mello", conv.opening())]
    disposition = None
    for u in utterances:
        transcript.append(("caller", u))
        turn = conv.handle(u)
        transcript.append(("mello", turn.message))
        if turn.end_call:
            disposition = turn.disposition
            break
    session.flush()
    return disposition or conv.timeout_disposition(), transcript
