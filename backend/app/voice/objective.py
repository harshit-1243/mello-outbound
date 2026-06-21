"""Objective registry — maps a campaign's objective_type to its conversation, and a scripted runner.

This is the abstraction Stage 8 extends (add 'renewal' here, nothing else changes). ``run_scripted``
plays a list of caller utterances through the practice-mode brain and returns the final disposition
+ transcript — used by tests and by a future auto-callee simulator to exercise whole campaigns.
"""
from __future__ import annotations

from app.db.models import OBJECTIVE_BOOKING_CONFIRMATION, Client
from app.voice.conversation import BookingConfirmationConversation

_CONVERSATIONS = {
    OBJECTIVE_BOOKING_CONFIRMATION: BookingConfirmationConversation,
}


def make_conversation(session, contact, campaign):
    client = session.get(Client, contact.client_id)
    business = client.business_name if client else "Mello"
    factory = _CONVERSATIONS.get(campaign.objective_type)
    if factory is None:
        raise ValueError(f"No outbound conversation registered for objective {campaign.objective_type!r}")
    return factory(session, contact, campaign, business)


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
